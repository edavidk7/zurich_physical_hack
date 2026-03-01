#!/usr/bin/env python3
"""
Test the IK pipeline in the MuJoCo SO-100 simulator.

1. Runs the placo IK solver to compute a trajectory from home → target
2. Replays that trajectory in MuJoCo with the 3D viewer open
3. Shows a green target sphere at the desired position

Usage:
    .venv/bin/python test_pipeline_mujoco.py
    .venv/bin/python test_pipeline_mujoco.py --target 0.15 -0.05 0.05
"""

import json
import time
import numpy as np
import mujoco
import mujoco.viewer

from src.ik_solver import SO101IKSolver

# ── MuJoCo model path ────────────────────────────────────────────────────
SIM_DIR = "/Users/davidkorcak/Documents/eth/sem2/robot_learning/hw2_robot_control_mdps"
XML_PATH = f"{SIM_DIR}/so101_gym/assets/so100_pos_ctrl.xml"

# ── Joint name mapping: IK solver motor names → MuJoCo joint names ───────
MOTOR_TO_MUJOCO = {
    "shoulder_pan": "Rotation",
    "shoulder_lift": "Pitch",
    "elbow_flex": "Elbow",
    "wrist_flex": "Wrist_Pitch",
    "wrist_roll": "Wrist_Roll",
    "gripper": "Jaw",
}


def motor_deg_to_mujoco_rad(q_deg: dict[str, float]) -> dict[str, float]:
    """Convert motor-name degrees dict → MuJoCo joint-name radians dict."""
    return {
        MOTOR_TO_MUJOCO[motor]: np.deg2rad(deg)
        for motor, deg in q_deg.items()
        if motor in MOTOR_TO_MUJOCO
    }


def set_mujoco_joints(model, data, q_rad: dict[str, float]):
    """Set MuJoCo joint positions (qpos) and actuator targets (ctrl)."""
    for joint_name, rad_val in q_rad.items():
        jid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, joint_name)
        if jid >= 0:
            qpos_adr = model.jnt_qposadr[jid]
            data.qpos[qpos_adr] = rad_val
        aid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_ACTUATOR, joint_name)
        if aid >= 0:
            data.ctrl[aid] = rad_val


def main():
    import argparse

    ap = argparse.ArgumentParser(description="MuJoCo IK trajectory test")
    ap.add_argument(
        "--target",
        nargs=3,
        type=float,
        default=[0.15, -0.05, 0.05],
        metavar=("X", "Y", "Z"),
        help="Target tip position in robot base frame (metres)",
    )
    ap.add_argument("--steps", type=int, default=40, help="Trajectory waypoints")
    ap.add_argument(
        "--delay", type=float, default=0.08, help="Seconds between waypoints in viewer"
    )
    args = ap.parse_args()

    target_robot = np.array(args.target)
    n_steps = args.steps

    # ── Load plan step info ──────────────────────────────────────────────
    with open("data/plans/latest_plan.json") as f:
        plan = json.load(f)
    probe_step = next(
        s for s in plan["plan"]["task_plan"]["steps"] if s.get("action") == "PROBE"
    )
    print(f"Plan step: {probe_step['description']}")
    print(f"  probe_positive: {probe_step['parameters'].get('probe_positive')}")
    print()

    # ── IK solver ────────────────────────────────────────────────────────
    solver = SO101IKSolver()
    q_current = solver.zero_command()
    current_tip = solver.current_tip_pos(q_current)

    print("=== Home configuration ===")
    solver.print_status(q_current)
    print()

    delta = target_robot - current_tip
    dist_m = float(np.linalg.norm(delta))
    print(f"=== Target ===")
    print(f"  position: {target_robot} m")
    print(f"  delta:    {delta.round(4)} m")
    print(f"  distance: {dist_m * 100:.2f} cm")
    print()

    # ── Solve IK ─────────────────────────────────────────────────────────
    q_target = solver.ik(q_current, target_robot)
    achieved_tip = solver.current_tip_pos(q_target)
    ik_error = np.linalg.norm(achieved_tip - target_robot)

    print("=== IK Solution ===")
    print(f"  joints (deg): { {k: round(v, 2) for k, v in q_target.items()} }")
    solver.print_status(q_target)
    print(f"  IK error: {ik_error * 1000:.3f} mm")
    print()

    # ── Plan trajectory ──────────────────────────────────────────────────
    trajectory = solver.plan_motion(q_current, q_target, n_steps=n_steps)
    print(f"Planned {n_steps}-waypoint trajectory")

    # Print a few waypoints
    for i in range(0, len(trajectory), 10):
        wp = trajectory[i]
        tip = solver.current_tip_pos(wp)
        print(f"  step {i:3d}: tip={tip.round(4)}")
    tip_final = solver.current_tip_pos(trajectory[-1])
    print(f"  step {len(trajectory) - 1:3d}: tip={tip_final.round(4)} (final)")
    print()

    # ── MuJoCo simulation ────────────────────────────────────────────────
    print("=== Launching MuJoCo viewer ===")
    print(f"  XML: {XML_PATH}")
    print(f"  Target: {target_robot}")
    print(f"  Waypoints: {n_steps}, delay: {args.delay}s each")
    print()

    model = mujoco.MjModel.from_xml_path(XML_PATH)
    data = mujoco.MjData(model)

    # Set initial home position
    q0_rad = motor_deg_to_mujoco_rad(q_current)
    set_mujoco_joints(model, data, q0_rad)
    mujoco.mj_forward(model, data)

    # Set the mocap target sphere to the target position
    if model.nmocap > 0:
        data.mocap_pos[0] = target_robot

    with mujoco.viewer.launch_passive(model, data) as viewer:
        # Let user see the initial state
        print("Showing home position for 2 seconds...")
        t0 = time.time()
        while time.time() - t0 < 2.0 and viewer.is_running():
            mujoco.mj_step(model, data)
            viewer.sync()
            time.sleep(0.01)

        # Replay trajectory
        print("Replaying trajectory...")
        for i, wp in enumerate(trajectory):
            if not viewer.is_running():
                print("Viewer closed, stopping.")
                break

            q_rad = motor_deg_to_mujoco_rad(wp)
            set_mujoco_joints(model, data, q_rad)

            # Step the simulation a few times to let PD controllers settle
            for _ in range(20):
                mujoco.mj_step(model, data)

            viewer.sync()

            if i % 10 == 0 or i == len(trajectory) - 1:
                tip = solver.current_tip_pos(wp)
                print(f"  waypoint {i:3d}/{n_steps - 1}: tip={tip.round(4)}")

            time.sleep(args.delay)

        # Hold final position
        print()
        print("Trajectory complete. Holding final position.")
        print(f"  Target:   {target_robot.round(5)}")
        print(f"  Achieved: {achieved_tip.round(5)}")
        print(f"  IK error: {ik_error * 1000:.2f} mm")
        print()
        print("Close the viewer window to exit.")

        while viewer.is_running():
            mujoco.mj_step(model, data)
            viewer.sync()
            time.sleep(0.01)


if __name__ == "__main__":
    main()
