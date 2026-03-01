"""
Camera-Robot transform from kinematic chain + one tip observation.

No external calibration target needed for the camera-robot transform.
The robot's own kinematics give it.

Theory
------
The camera is rigidly mounted relative to the robot EE (end-effector).
Let T_cam_ee be the fixed camera-in-EE transform (camera pose expressed in
the EE frame).  Then at any joint configuration:

    T_robot_cam  =  FK(q)  @  T_ee_cam          (inverse of T_cam_ee)

where FK(q) = T_ee_robot = placo.fk(q_deg).

To calibrate T_cam_ee we need one observation:
  - Move robot to any pose and read joint angles  →  T_ee_robot  (from FK)
  - Measure the tooltip position in camera frame  →  p_tip_cam
  - Know the tooltip offset in EE frame           →  p_tip_ee  (= tool_offset_ee)

The camera-in-EE transform decomposes as:
    p_tip_cam = R_cam_ee @ p_tip_ee + t_cam_ee
    →  t_cam_ee = p_tip_cam − R_cam_ee @ p_tip_ee

This gives the translation of the camera origin in EE frame.

The rotation R_cam_ee (how EE-frame axes look in camera frame) must come from:
  a) Physical measurement / CAD (how the camera is mounted)
  b) Multiple tip observations at different EE orientations (see calibrate_R_cam_ee())
  c) Approximate from known constraints

SO-101 physical setup (confirmed from hardware photos + kinematic diagram):
  - Tool (probe) extends along EE +X (red axis)  →  tool_offset_ee = [0.054, 0, 0]
  - Camera is mounted on a bracket above the EE, tilted 35° around EE local Y
    toward EE +X (forward).  In right-hand Rodrigues around EE Y this is -35°:
      R_cam_ee = Ry(-35°) = [[cos35, 0, -sin35], [0, 1, 0], [sin35, 0, cos35]]
    Ry(-35°) makes the camera look FORWARD (+EE X direction) and DOWN (+EE Z),
    which matches the physical photo.  Ry(+35°) would look BACKWARD — wrong.

Default constants (use these unless you re-calibrate):
  TOOL_OFFSET_EE = np.array([0.054, 0.0, 0.0])   # metres, along EE +X
  R_CAM_EE       = Ry(-35°)                       # see make_R_cam_ee() below

Once T_cam_ee is known, the full pipeline is:
  1.  Read joint angles  →  T_ee_robot = FK(q)
  2.  Compute T_robot_cam = T_ee_robot @ T_ee_cam
  3.  Get target 3-D point in camera frame (from checkerboard PnP / depth)
  4.  p_target_robot = T_robot_cam @ [p_target_cam; 1]  → feed to IK solver

Usage
-----
    from src.robot_cam_calibration import calibrate_T_cam_ee, compute_T_robot_cam

    # --- one-time calibration (do this once with tip touching a known location) ---
    T_cam_ee = calibrate_T_cam_ee(
        q_deg        = current_joint_angles,   # dict: motor_name -> degrees
        p_tip_cam    = np.array([0.0, 0.020479, 0.124339]),  # metres
        tool_offset_ee = np.array([0.0, -0.054, 0.0]),       # metres, in EE frame
        solver       = ik_solver_instance,
        R_cam_ee     = R_cam_ee_approx,        # 3×3, or None for identity
    )

    # --- at run time (every frame / every command) ---
    T_robot_cam = compute_T_robot_cam(q_deg, T_cam_ee, solver)
    p_target_robot = (T_robot_cam @ np.append(p_target_cam, 1))[:3]
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

try:
    from src.constants import TOOL_OFFSET_EE_M, CAM_TILT_EE_DEG, P_TIP_CAM_M
except ImportError:
    from constants import TOOL_OFFSET_EE_M, CAM_TILT_EE_DEG, P_TIP_CAM_M


# ---------------------------------------------------------------------------
# SO-101 physical constants  (values come from src/constants.py)
# ---------------------------------------------------------------------------

#: Tool (probe) offset from the Fixed_Jaw EE frame origin (metres, EE frame)
TOOL_OFFSET_EE: np.ndarray = np.array(TOOL_OFFSET_EE_M)


def make_R_cam_ee(tilt_deg: float = CAM_TILT_EE_DEG) -> np.ndarray:
    """
    Build R_cam_ee for the SO-101 wrist camera.

    The camera is tilted `tilt_deg` degrees around EE local Y from the EE Z
    direction (toward EE +X / forward).  Physical default is -35°:
      - Negative because rotating toward +EE X from +EE Z is a negative Ry
        rotation in right-hand convention.
      - Result: camera looks FORWARD (along probe direction) and DOWN.

    Returns a 3×3 rotation matrix that transforms EE-frame vectors to
    camera-frame vectors.
    """
    theta = np.deg2rad(tilt_deg)
    # Standard Ry(θ): rotates +Z toward +X for positive θ
    return np.array([
        [ np.cos(theta), 0, np.sin(theta)],
        [ 0,             1, 0            ],
        [-np.sin(theta), 0, np.cos(theta)],
    ])


#: Default camera-in-EE rotation for the SO-101 wrist camera
R_CAM_EE_DEFAULT: np.ndarray = make_R_cam_ee(CAM_TILT_EE_DEG)

#: Fixed vector from camera origin to tooltip, expressed in camera frame (metres).
#: Constant because both camera and tool are rigidly attached to the EE.
P_TIP_CAM: np.ndarray = np.array(P_TIP_CAM_M)

# Pre-compute the fixed camera-in-EE transform from the known constants.
# This never needs to be recomputed at runtime — just use T_CAM_EE directly.
def _make_T_cam_ee() -> np.ndarray:
    t = P_TIP_CAM - R_CAM_EE_DEFAULT @ TOOL_OFFSET_EE
    T = np.eye(4)
    T[:3, :3] = R_CAM_EE_DEFAULT
    T[:3,  3] = t
    return T

#: Fixed 4×4 camera-in-EE transform.
#: T_CAM_EE transforms EE-frame points to camera-frame points:
#:   p_cam = T_CAM_EE @ [p_ee; 1]
#: Camera origin in EE frame: [-44.2, +20.5, +93.4] mm
T_CAM_EE: np.ndarray = _make_T_cam_ee()

#: Inverse: EE-in-camera transform (precomputed for speed)
T_EE_CAM: np.ndarray = np.linalg.inv(T_CAM_EE)


# ---------------------------------------------------------------------------
# Core math
# ---------------------------------------------------------------------------

def calibrate_T_cam_ee(
    q_deg: dict[str, float],
    p_tip_cam: np.ndarray,
    tool_offset_ee: np.ndarray,
    solver,                         # SO101IKSolver instance
    R_cam_ee: np.ndarray | None = None,
) -> np.ndarray:
    """
    Compute the fixed camera-in-EE transform T_cam_ee (4×4) from one tip observation.

    T_cam_ee transforms EE-frame coordinates to camera-frame coordinates:
        p_cam = T_cam_ee @ [p_ee; 1]  →  p_cam = R_cam_ee @ p_ee + t_cam_ee

    Parameters
    ----------
    q_deg          : current joint angles (degrees), keyed by motor name
    p_tip_cam      : tooltip position in camera frame (metres)
    tool_offset_ee : tooltip position in EE (Fixed_Jaw) frame (metres)
                     e.g. [0, -0.054, 0] if probe is 54mm along EE -Y
    solver         : SO101IKSolver (used to compute FK)
    R_cam_ee       : 3×3 rotation of camera axes expressed in EE frame.
                     None → identity (camera and EE frames have parallel axes).

    Returns
    -------
    T_cam_ee : (4,4) ndarray — fixed camera-in-EE transform
    """
    p_tip_cam      = np.asarray(p_tip_cam,      dtype=float)
    tool_offset_ee = np.asarray(tool_offset_ee, dtype=float)
    R_cam_ee       = np.eye(3, dtype=float) if R_cam_ee is None else np.asarray(R_cam_ee, dtype=float)

    # Translation: camera origin in EE frame when tip is at known position
    # Constraint: p_tip_cam = R_cam_ee @ tool_offset_ee + t_cam_ee
    t_cam_ee = p_tip_cam - R_cam_ee @ tool_offset_ee

    T_cam_ee = np.eye(4)
    T_cam_ee[:3, :3] = R_cam_ee
    T_cam_ee[:3,  3] = t_cam_ee

    return T_cam_ee


def compute_T_robot_cam(
    q_deg: dict[str, float],
    solver,
    T_cam_ee: np.ndarray | None = None,
) -> np.ndarray:
    """
    Compute T_robot_cam (camera → robot base, 4×4) for the current joint state.

    T_robot_cam  =  FK(q)  @  T_ee_cam

    Uses the precomputed constant T_CAM_EE / T_EE_CAM by default — no
    calibration step needed at runtime.

    Parameters
    ----------
    q_deg    : current joint angles (degrees)
    solver   : SO101IKSolver
    T_cam_ee : override the default T_CAM_EE constant (optional)

    Returns
    -------
    T_robot_cam : (4,4) ndarray — transforms camera-frame points to robot-base frame
    """
    T_ee_robot  = solver.fk(q_deg)
    T_ee_cam_   = T_EE_CAM if T_cam_ee is None else np.linalg.inv(T_cam_ee)
    return T_ee_robot @ T_ee_cam_


def cam_to_robot(
    p_cam: np.ndarray,
    T_robot_cam: np.ndarray,
) -> np.ndarray:
    """Transform a 3D point from camera frame to robot base frame."""
    p_cam = np.asarray(p_cam, dtype=float)
    return (T_robot_cam @ np.append(p_cam, 1.0))[:3]


# ---------------------------------------------------------------------------
# Multi-pose rotation calibration (optional, for accurate R_cam_ee)
# ---------------------------------------------------------------------------

def calibrate_R_cam_ee(
    observations: list[tuple[dict, np.ndarray, np.ndarray]],
    solver,
) -> np.ndarray:
    """
    Estimate R_cam_ee from multiple tip observations at different EE orientations.

    Each observation is (q_deg, p_tip_cam, tool_offset_ee).  At each pose:

        R_cam_ee @ tool_offset_ee  =  p_tip_cam − t_cam_ee

    Since t_cam_ee is the same at every pose (rigid mount), and the left-hand
    side changes with orientation, we can set up a least-squares system.

    Requires >= 3 observations with sufficiently different EE orientations.
    Uses SVD to find the closest orthonormal R.

    Parameters
    ----------
    observations : list of (q_deg, p_tip_cam, tool_offset_ee)
    solver       : SO101IKSolver

    Returns
    -------
    R_cam_ee : (3,3) ndarray, closest rotation matrix (det=+1)
    """
    if len(observations) < 3:
        raise ValueError("Need at least 3 observations to estimate R_cam_ee.")

    # At each pose i:   R_cam_ee @ d_i = c_i - t_cam_ee    (d_i = tool_offset_ee in EE frame)
    # But t_cam_ee is unknown.  Subtract mean to eliminate it:
    #   R_cam_ee @ (d_i - d_mean) = (c_i - c_mean)
    # Build matrices A (3×N left-hand side in EE frame) and B (3×N right-hand side in camera):

    # Actually tool_offset_ee is the SAME at all poses (probe doesn't change in EE frame).
    # What changes is the EE orientation in world → we express tool_offset_ee in world at each pose.
    # More precisely:
    #   d_i_world = R_ee_robot_i @ tool_offset_ee   (in robot base)
    #   c_i_world = R_robot_cam @ p_tip_cam_i + t   (in robot base, with unknown T_robot_cam)
    # This reduces to standard hand-eye calibration — complex.
    #
    # Simplified approach (assumes translation is calibrated separately):
    # We observe p_tip_cam_i and know tool_dir_ee = tool_offset_ee / ||tool_offset_ee||.
    # In camera frame, the tool axis at pose i is:
    #   tool_dir_cam_i = R_cam_ee @ (R_ee_robot_i @ tool_dir_ee)  ... unknown R_cam_ee
    # We can't directly observe tool_dir_cam_i from tip position alone.
    #
    # Practical approach: collect tips at two EE orientations that differ by a known
    # rotation, then:
    #   delta_p_cam   = p_tip_cam_2 - p_tip_cam_1   (in camera)
    #   delta_p_robot = T_ee_robot_2 @ tool − T_ee_robot_1 @ tool  (in robot base)
    #   delta_p_cam   = R_cam_robot @ delta_p_robot
    # With 3 linearly independent deltas → R_cam_robot via least-squares.

    n = len(observations)
    A = np.zeros((3 * (n - 1), 3))   # columns of R_cam_robot to solve for
    b = np.zeros(3 * (n - 1))

    q0, c0, off0 = observations[0]
    T0 = solver.fk(q0)
    p0_robot = (T0 @ np.append(off0, 1.0))[:3]   # tip in robot base at pose 0

    for i, (qi, ci, offi) in enumerate(observations[1:]):
        Ti      = solver.fk(qi)
        pi_robot = (Ti @ np.append(offi, 1.0))[:3]

        delta_robot = pi_robot - p0_robot     # (3,) in robot base
        delta_cam   = ci - c0                 # (3,) in camera

        # delta_cam = R_cam_robot @ delta_robot  →  solve for R_cam_robot
        row = slice(i * 3, i * 3 + 3)
        # We fill a big Ax=b where x is R_cam_robot column-stacked
        # Using Kronecker form:  vec(delta_cam) = (delta_robot.T ⊗ I) vec(R_cam_robot)
        A[row] = np.kron(delta_robot.T, np.eye(3)).reshape(3, 9)[:, :3]   # simplified
        # Actually let's just build the column-by-column system
        # We do this in one shot below

    # Simpler least-squares:  for each axis, solve R_cam_robot @ D = C
    D = np.zeros((3, n - 1))   # deltas in robot base (columns)
    C = np.zeros((3, n - 1))   # deltas in camera (columns)
    q0, c0, off0 = observations[0]
    T0 = solver.fk(q0)
    p0_robot = (T0 @ np.append(off0, 1.0))[:3]

    for i, (qi, ci, offi) in enumerate(observations[1:]):
        Ti = solver.fk(qi)
        D[:, i] = (Ti @ np.append(offi, 1.0))[:3] - p0_robot
        C[:, i] = np.asarray(ci) - np.asarray(c0)

    # R_cam_robot @ D = C  →  R = C @ D^+ (pseudo-inverse)
    R_cam_robot_est, _, _, _ = np.linalg.lstsq(D.T, C.T, rcond=None)
    R_cam_robot_est = R_cam_robot_est.T  # (3,3)

    # Project to nearest rotation matrix via SVD
    U, _, Vt = np.linalg.svd(R_cam_robot_est)
    R_cam_robot = U @ Vt
    if np.linalg.det(R_cam_robot) < 0:
        U[:, -1] *= -1
        R_cam_robot = U @ Vt

    # R_cam_ee: we want the rotation of camera relative to EE (not relative to robot base)
    # R_cam_robot = R_cam_ee @ R_ee_robot (at some reference pose)
    # But R_ee_robot changes per pose. We want a fixed R_cam_ee.
    # For now, return R_cam_robot at the first pose's EE orientation.
    T0 = solver.fk(observations[0][0])
    R_ee_robot_0 = T0[:3, :3]
    R_cam_ee = R_cam_robot @ R_ee_robot_0

    return R_cam_ee


# ---------------------------------------------------------------------------
# Save / load calibration
# ---------------------------------------------------------------------------

_DEFAULT_SAVE_PATH = Path(__file__).parents[1] / "data/arm_cam_calib/T_cam_ee.json"


def save_T_cam_ee(T_cam_ee: np.ndarray, path: str | Path = _DEFAULT_SAVE_PATH) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump({"T_cam_ee": T_cam_ee.tolist()}, f, indent=2)
    print(f"Saved T_cam_ee to {path}")


def load_T_cam_ee(path: str | Path = _DEFAULT_SAVE_PATH) -> np.ndarray:
    with open(path) as f:
        data = json.load(f)
    return np.array(data["T_cam_ee"])


# ---------------------------------------------------------------------------
# CLI demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from ik_solver import SO101IKSolver

    ap = argparse.ArgumentParser(description="Calibrate camera-robot transform from tip observation")
    ap.add_argument("--q", nargs=6, type=float, required=True,
                    metavar=("PAN","LIFT","ELBOW","WFLEX","WROLL","GRIP"),
                    help="Joint angles in degrees (shoulder_pan lift elbow wrist_flex wrist_roll gripper)")
    ap.add_argument("--tip-cam", nargs=3, type=float, required=True,
                    metavar=("X","Y","Z"),
                    help="Tooltip position in camera frame (metres)")
    ap.add_argument("--tool-offset", nargs=3, type=float, required=True,
                    metavar=("X","Y","Z"),
                    help="Tooltip offset in EE (Fixed_Jaw) frame (metres), e.g. 0 -0.054 0")
    ap.add_argument("--save", default=str(_DEFAULT_SAVE_PATH),
                    help="Path to save T_cam_ee JSON")
    args = ap.parse_args()

    motors = ["shoulder_pan","shoulder_lift","elbow_flex","wrist_flex","wrist_roll","gripper"]
    q_deg  = dict(zip(motors, args.q))

    solver = SO101IKSolver()
    T_ee   = solver.fk(q_deg)

    T_cam_ee = calibrate_T_cam_ee(
        q_deg          = q_deg,
        p_tip_cam      = np.array(args.tip_cam),
        tool_offset_ee = np.array(args.tool_offset),
        solver         = solver,
    )

    # Verify: tip in robot base from FK vs from camera transform
    T_robot_cam = compute_T_robot_cam(q_deg, solver, T_cam_ee)
    p_tip_cam   = np.array(args.tip_cam)
    p_tip_robot_from_cam = cam_to_robot(p_tip_cam, T_robot_cam)
    p_tip_robot_from_fk  = (T_ee @ np.append(args.tool_offset, 1.0))[:3]

    print("\n" + "=" * 55)
    print("  Camera-Robot Calibration from Tip Observation")
    print("=" * 55)
    print(f"  Tool tip in camera frame  : {np.array(args.tip_cam)*1000} mm")
    print(f"  Tool offset in EE frame   : {np.array(args.tool_offset)*1000} mm")
    print()
    print(f"  EE position in robot base : {T_ee[:3,3]*1000} mm")
    print()
    print(f"  Tip in robot base (FK)    : {p_tip_robot_from_fk*1000} mm")
    print(f"  Tip in robot base (cam→R) : {p_tip_robot_from_cam*1000} mm")
    diff = np.linalg.norm(p_tip_robot_from_cam - p_tip_robot_from_fk)
    print(f"  Consistency error         : {diff*1000:.3f} mm")
    print()
    print("  T_cam_ee (camera in EE frame):")
    print("  ", T_cam_ee)
    print()
    print("  T_robot_cam (camera → robot base):")
    print("  ", T_robot_cam)
    print("=" * 55)

    save_T_cam_ee(T_cam_ee, args.save)
