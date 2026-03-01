"use client";

import { useEffect, useRef, useState, Suspense } from "react";
import { Canvas, useThree } from "@react-three/fiber";
import { OrbitControls, Grid } from "@react-three/drei";
import * as THREE from "three";
import URDFLoader from "urdf-loader";
import type { URDFRobot } from "urdf-loader";

// ---------------------------------------------------------------------------
// URDF Robot model component
// ---------------------------------------------------------------------------

/**
 * Joint mapping: our UI joints array is
 * [shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll, gripper]
 * in DEGREES (first 5) and 0-100 PERCENT (gripper).
 * The URDF joint names match exactly.
 */
const JOINT_NAMES = [
  "shoulder_pan",
  "shoulder_lift",
  "elbow_flex",
  "wrist_flex",
  "wrist_roll",
  "gripper",
];

/**
 * Per-joint corrections to align motor readings with the URDF model.
 *
 * Calibrated from two observations of the same "upright" pose:
 *   Real motor readings:  [-3, 8, -101, 10, -79, 39]°
 *   Sim slider at upright: [0, 112, 80.5, 31, -170.5, 6.5]°
 *
 * Formula: urdf_deg = sign * motor_deg + offset
 *          offset = sim_upright - sign * real_upright
 */
const JOINT_CORRECTIONS = [
  { sign: -1, offsetDeg:   -3 },   // 0 shoulder_pan    0 - (-1)*(-3) = -3
  { sign:  1, offsetDeg:  104 },   // 1 shoulder_lift  112 - (1)*(8)  = 104
  { sign: 1, offsetDeg: -80.5 },   // 2 elbow_flex     80.5 - (1)*(-101) = -80.5 },
  { sign: 1, offsetDeg:   -43 },   // 3 wrist_flex     31 - (-1)*(10) = 41
  { sign:  1, offsetDeg: 0 },  // 4 wrist_roll -170.5 - (1)*(-79) = -91.5
  { sign:  1, offsetDeg:    0 },   // 5 gripper      handled separately
];

/** Convert motor value → URDF joint angle in radians */
function motorToUrdf(index: number, motorValue: number): number {
  if (index === 5) {
    // Gripper: motor 0-100 → URDF [-0.2, 2.0] rad
    const pct = Math.max(0, Math.min(100, motorValue)) / 100;
    return pct - 35;
  }
  const { sign, offsetDeg } = JOINT_CORRECTIONS[index];
  const correctedDeg = sign * motorValue + offsetDeg;
  return correctedDeg * (Math.PI / 180);
}

function RobotModel({ joints }: { joints: number[] }) {
  const groupRef = useRef<THREE.Group>(null);
  const [robot, setRobot] = useState<URDFRobot | null>(null);

  // Load the URDF once
  useEffect(() => {
    const loader = new URDFLoader();
    loader.packages = "";
    loader.load("/robot/so100.urdf", (result) => {
      // Recolor all meshes
      result.traverse((child) => {
        if ((child as THREE.Mesh).isMesh) {
          const mesh = child as THREE.Mesh;
          // Detect motor parts: urdf-loader may use MeshPhongMaterial
          // URDF material "sts3215" = rgba(0.1, 0.1, 0.1) → dark
          // URDF material "3d_printed" = rgba(1.0, 0.82, 0.12) → yellow
          let isMotor = false;
          const mat = mesh.material as THREE.Material & { color?: THREE.Color };
          if (mat?.color) {
            isMotor = mat.color.r < 0.3 && mat.color.g < 0.3 && mat.color.b < 0.3;
          }
          mesh.material = new THREE.MeshStandardMaterial({
            color: isMotor ? "#222222" : "#14b8a6",
            metalness: isMotor ? 0.5 : 0.15,
            roughness: isMotor ? 0.4 : 0.7,
          });
        }
      });

      setRobot(result);
    });
  }, []);

  // Apply joint angles whenever they change
  useEffect(() => {
    if (!robot) return;
    JOINT_NAMES.forEach((name, i) => {
      const joint = robot.joints[name];
      if (joint) {
        const angleRad = motorToUrdf(i, joints[i] ?? 0);
        joint.setJointValue(angleRad);
      }
    });
  }, [robot, joints]);

  // Add robot to the scene
  useEffect(() => {
    if (!robot || !groupRef.current) return;
    // Clear previous
    while (groupRef.current.children.length > 0) {
      groupRef.current.remove(groupRef.current.children[0]);
    }
    groupRef.current.add(robot);
  }, [robot]);

  return <group ref={groupRef} rotation={[-Math.PI / 2, 0, 0]} />;
}

// ---------------------------------------------------------------------------
// Scene setup (camera, lights, ground)
// ---------------------------------------------------------------------------

function SceneSetup() {
  const { camera } = useThree();

  useEffect(() => {
    camera.position.set(0.3, 0.25, 0.3);
    camera.lookAt(0, 0.1, 0);
  }, [camera]);

  return null;
}

// ---------------------------------------------------------------------------
// Exported ArmSimulator component
// ---------------------------------------------------------------------------

interface ArmSimulatorProps {
  /** 6 joint angles in degrees: [shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll, gripper] */
  joints: number[];
  /** Optional CSS class for the container */
  className?: string;
}

export default function ArmSimulator({ joints, className }: ArmSimulatorProps) {
  return (
    <div className={className ?? "w-full h-full min-h-[300px]"}>
      <Canvas
        shadows
        gl={{ antialias: true, alpha: true }}
        dpr={[1, 2]}
        style={{ background: "linear-gradient(180deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%)" }}
      >
        <SceneSetup />

        {/* Lighting */}
        <ambientLight intensity={0.4} />
        <directionalLight position={[2, 3, 2]} intensity={1.2} castShadow />
        <directionalLight position={[-1, 2, -1]} intensity={0.4} />
        <pointLight position={[0, 0.3, 0]} intensity={0.3} color="#37e0d8" />

        {/* Ground grid */}
        <Grid
          args={[2, 2]}
          cellSize={0.02}
          cellThickness={0.5}
          cellColor="#37e0d8"
          sectionSize={0.1}
          sectionThickness={1}
          sectionColor="#37e0d8"
          fadeDistance={1}
          fadeStrength={1}
          followCamera={false}
          infiniteGrid
        />

        {/* Robot */}
        <Suspense fallback={null}>
          <RobotModel joints={joints} />
        </Suspense>

        {/* Camera controls */}
        <OrbitControls
          target={[0, 0.1, 0]}
          minDistance={0.1}
          maxDistance={1}
          enablePan={true}
          enableDamping
          dampingFactor={0.1}
        />
      </Canvas>
    </div>
  );
}
