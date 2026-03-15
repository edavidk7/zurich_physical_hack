"""
SO-101 Inverse Kinematics Solver
=================================
Uses lerobot's RobotKinematics (placo/pinocchio backend) for FK/IK.

This replaces direct placo usage with lerobot's official kinematics wrapper,
which handles URDF loading, mesh stripping, and frame management internally.

Tool offset
-----------
The probe extends beyond the robot's wrist.  Supply a 3-D vector in the
*end-effector's local frame* (Fixed_Jaw frame) and the solver will account
for it automatically:

    solver = SO101IKSolver(tool_offset=[0, 0, -0.05])   # 5 cm along EE -Z
    cmd = solver.ik(current_joints, target_pos_world)

Command format
--------------
All public methods use dicts keyed by SO-101 motor names, values in degrees:
    {"shoulder_pan": 0.0, "shoulder_lift": -45.0, "elbow_flex": 90.0,
     "wrist_flex": 0.0, "wrist_roll": 0.0, "gripper": 0.0}

Usage
-----
    solver = SO101IKSolver(tool_offset=[0, 0, -0.03])

    # current joint state (read from robot)
    q_now = {"shoulder_pan": 10, "shoulder_lift": -20, ...}

    # target tip position in robot base frame (metres)
    target = np.array([0.15, -0.10, 0.05])

    # solve and generate smooth trajectory
    q_target = solver.ik(q_now, target)
    trajectory = solver.plan_motion(q_now, q_target, n_steps=30)

    for waypoint in trajectory:
        robot.send(waypoint)   # each waypoint is a command dict
"""

from __future__ import annotations

import importlib.resources
import re
import tempfile
from pathlib import Path
from typing import Sequence

import numpy as np

try:
    from src.constants import TOOL_OFFSET_EE_M as _DEFAULT_TOOL_OFFSET
except ImportError:
    from constants import TOOL_OFFSET_EE_M as _DEFAULT_TOOL_OFFSET

# ---------------------------------------------------------------------------
# URDF location — resolved via lerobot's bundled resources
# ---------------------------------------------------------------------------


def _find_urdf() -> str:
    """Locate the SO-100 URDF bundled with the lerobot package.

    Tries several strategies in order:
      1. importlib.resources (clean, works with installed packages)
      2. Walk site-packages for the known resource path (fallback)
    """
    # Strategy 1: importlib.resources
    try:
        ref = importlib.resources.files("resources") / "urdf" / "so-100" / "urdf" / "so-100.urdf"
        p = Path(str(ref))
        if p.exists():
            return str(p)
    except Exception:
        pass

    # Strategy 2: search site-packages
    import site

    for sp in site.getsitepackages() + [site.getusersitepackages()]:
        candidate = Path(sp) / "resources" / "urdf" / "so-100" / "urdf" / "so-100.urdf"
        if candidate.exists():
            return str(candidate)

    # Strategy 3: brute-force search in common .venv locations
    import sys

    for p in sys.path:
        candidate = Path(p) / "resources" / "urdf" / "so-100" / "urdf" / "so-100.urdf"
        if candidate.exists():
            return str(candidate)

    raise FileNotFoundError("Could not locate SO-100 URDF. Ensure lerobot is installed with the kinematics extra: pip install lerobot[kinematics]")


_STRIPPED_URDF: str | None = None  # cached path to the mesh-free copy


def _get_stripped_urdf() -> str:
    """Return path to a mesh-stripped copy of the URDF (created once).

    Placo cannot resolve package:// mesh URIs, so we strip all <visual>
    and <collision> blocks before loading.
    """
    global _STRIPPED_URDF
    if _STRIPPED_URDF and Path(_STRIPPED_URDF).exists():
        return _STRIPPED_URDF

    text = Path(_find_urdf()).read_text()
    text = re.sub(r"<visual>.*?</visual>", "", text, flags=re.DOTALL)
    text = re.sub(r"<collision>.*?</collision>", "", text, flags=re.DOTALL)

    tmp = tempfile.NamedTemporaryFile(suffix=".urdf", delete=False, mode="w")
    tmp.write(text)
    tmp.close()
    _STRIPPED_URDF = tmp.name
    return _STRIPPED_URDF


# ---------------------------------------------------------------------------
# Joint name mappings
# ---------------------------------------------------------------------------

# lerobot / placo joint names → SO-101 motor names
_PLACO_TO_MOTOR = {
    "Rotation": "shoulder_pan",
    "Pitch": "shoulder_lift",
    "Elbow": "elbow_flex",
    "Wrist_Pitch": "wrist_flex",
    "Wrist_Roll": "wrist_roll",
    "Jaw": "gripper",
}
_MOTOR_TO_PLACO = {v: k for k, v in _PLACO_TO_MOTOR.items()}

# Arm joints used for IK (gripper is kept fixed during IK)
_ARM_JOINTS_PLACO = ["Rotation", "Pitch", "Elbow", "Wrist_Pitch", "Wrist_Roll"]
_ARM_JOINTS_MOTOR = [_PLACO_TO_MOTOR[j] for j in _ARM_JOINTS_PLACO]

_EE_FRAME = "Fixed_Jaw"  # end-effector frame in the URDF / placo model

# Motor degree limits (from URDF, converted)
_LIMITS_DEG = {
    "shoulder_pan": (-91.7, 91.7),
    "shoulder_lift": (-90.0, 90.0),
    "elbow_flex": (-91.7, 80.2),
    "wrist_flex": (-95.7, 95.7),
    "wrist_roll": (-180.0, 180.0),
    "gripper": (-12.0, 85.9),
}

ZERO_COMMAND: dict[str, float] = {m: 0.0 for m in _PLACO_TO_MOTOR.values()}


# ---------------------------------------------------------------------------
# Main solver
# ---------------------------------------------------------------------------


class SO101IKSolver:
    """
    IK solver for the SO-101 arm using lerobot's RobotKinematics.

    Parameters
    ----------
    tool_offset : 3-sequence of float
        Offset of the actual tool tip from the Fixed_Jaw origin, expressed in
        the Fixed_Jaw (end-effector) local frame, in metres.
        Example: [0.059, 0, 0] means the tip is 5.9 cm along the EE +X axis.
    urdf_path : str or None
        Override path to the SO-100 URDF. If None, auto-detected from lerobot.
    """

    def __init__(
        self,
        tool_offset: Sequence[float] = _DEFAULT_TOOL_OFFSET,
        urdf_path: str | None = None,
    ) -> None:
        from lerobot.model.kinematics import RobotKinematics

        self.tool_offset = np.asarray(tool_offset, dtype=float)

        urdf = urdf_path or _get_stripped_urdf()

        # lerobot's RobotKinematics wraps placo internally.
        # joint_names must be the PLACO/URDF names, not motor names.
        self._kin = RobotKinematics(
            urdf_path=urdf,
            target_frame_name=_EE_FRAME,
            joint_names=list(_PLACO_TO_MOTOR.keys()),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _motor_to_placo_rad(self, q_deg: dict[str, float]) -> dict[str, float]:
        """Convert motor-name degrees dict → placo-name radians dict."""
        return {_MOTOR_TO_PLACO[motor]: np.deg2rad(deg) for motor, deg in q_deg.items() if motor in _MOTOR_TO_PLACO}

    def _placo_rad_to_motor_deg(self, q_rad: dict[str, float]) -> dict[str, float]:
        """Convert placo-name radians dict → motor-name degrees dict."""
        return {_PLACO_TO_MOTOR[placo]: float(np.rad2deg(rad)) for placo, rad in q_rad.items() if placo in _PLACO_TO_MOTOR}

    def _clip(self, q_deg: dict[str, float]) -> dict[str, float]:
        """Clip each joint to its degree limits."""
        return {m: float(np.clip(v, *_LIMITS_DEG[m])) for m, v in q_deg.items()}

    # ------------------------------------------------------------------
    # Forward kinematics
    # ------------------------------------------------------------------

    def fk(self, q_deg: dict[str, float]) -> np.ndarray:
        """
        Forward kinematics.

        Returns the 4×4 world transform of the Fixed_Jaw (end-effector) frame.
        """
        joint_names = list(_PLACO_TO_MOTOR.keys())
        q_array = np.array([q_deg[_PLACO_TO_MOTOR[j]] for j in joint_names])
        return self._kin.forward_kinematics(q_array).copy()

    def tool_tip_pose(self, q_deg: dict[str, float]) -> tuple[np.ndarray, np.ndarray]:
        """
        Compute the current tool-tip position and orientation.

        Returns
        -------
        pos : np.ndarray shape (3,)
            Tool tip position in the robot base frame (metres).
        R   : np.ndarray shape (3, 3)
            Orientation of the end-effector frame (= tool frame).
        """
        T = self.fk(q_deg)
        R = T[:3, :3]
        p_ee = T[:3, 3]
        p_tip = p_ee + R @ self.tool_offset
        return p_tip, R

    # ------------------------------------------------------------------
    # Inverse kinematics
    # ------------------------------------------------------------------

    def ik(
        self,
        q_current_deg: dict[str, float],
        target_pos: np.ndarray | Sequence[float],
        target_R: np.ndarray | None = None,
        pos_weight: float = 1.0,
        orient_weight: float = 0.01,
        max_iter: int = 200,
        tol_m: float = 1e-4,
    ) -> dict[str, float]:
        """
        Solve IK for the arm joints (gripper held fixed).

        Uses lerobot's RobotKinematics internally, which delegates to placo's
        KinematicsSolver. The tool offset is accounted for by adjusting the
        EE target so that the physical tip reaches target_pos.

        Parameters
        ----------
        q_current_deg : dict
            Current joint angles in degrees (all 6 joints).  Used as initial guess.
        target_pos : array-like (3,)
            Desired tool-tip position in the robot base frame (metres).
        target_R : (3,3) ndarray or None
            Desired EE orientation.  When None the current orientation is kept
            (position-only IK with soft orientation).
        pos_weight, orient_weight
            Weights for position vs orientation objectives.
        max_iter : int
            Maximum solver iterations.
        tol_m : float
            Convergence tolerance on tip-position error (metres).

        Returns
        -------
        dict  Motor-name → degrees, clipped to joint limits.
              Gripper value is copied from q_current_deg unchanged.
        """
        target_pos = np.asarray(target_pos, dtype=float)

        # Access the underlying placo objects from RobotKinematics
        robot = self._kin.robot
        solver = self._kin.solver

        # Set initial guess
        q_rad = self._motor_to_placo_rad(q_current_deg)
        for placo_name, rad in q_rad.items():
            robot.set_joint(placo_name, rad)
        robot.update_kinematics()

        task = self._kin.tip_frame

        fixed_orient = target_R is not None

        T_target = np.eye(4)
        if fixed_orient:
            T_target[:3, :3] = target_R
            T_target[:3, 3] = target_pos - target_R @ self.tool_offset
            task.T_world_frame = T_target

        task.configure(_EE_FRAME, "soft", pos_weight, orient_weight)

        for _ in range(max_iter):
            if not fixed_orient:
                T_ee_cur = robot.get_T_world_frame(_EE_FRAME)
                R_cur = T_ee_cur[:3, :3]
                T_target[:3, :3] = R_cur
                T_target[:3, 3] = target_pos - R_cur @ self.tool_offset
                task.T_world_frame = T_target

            solver.solve(True)
            robot.update_kinematics()

            # Check tip position error
            T_ee = robot.get_T_world_frame(_EE_FRAME)
            tip = T_ee[:3, 3] + T_ee[:3, :3] @ self.tool_offset
            if np.linalg.norm(tip - target_pos) < tol_m:
                break

        # Read result
        q_result = {motor: float(np.rad2deg(robot.get_joint(_MOTOR_TO_PLACO[motor]))) for motor in _PLACO_TO_MOTOR.values()}

        # Preserve gripper from initial command
        q_result["gripper"] = q_current_deg.get("gripper", 0.0)

        return self._clip(q_result)

    def ik_from_tip_to_tip(
        self,
        q_current_deg: dict[str, float],
        current_tip_pos: np.ndarray | Sequence[float],
        target_tip_pos: np.ndarray | Sequence[float],
        target_R: np.ndarray | None = None,
        **ik_kwargs,
    ) -> dict[str, float]:
        """
        Convenience wrapper: move the tool tip from *current_tip_pos* to
        *target_tip_pos*.  Both positions in robot base frame (metres).

        The current_tip_pos is used only for logging; the IK is solved
        purely from target_tip_pos.
        """
        current_tip_pos = np.asarray(current_tip_pos, dtype=float)
        target_tip_pos = np.asarray(target_tip_pos, dtype=float)
        delta = target_tip_pos - current_tip_pos
        print(f"[IK] tip move  Δ = {delta * 1000} mm  (‖Δ‖ = {np.linalg.norm(delta) * 1000:.1f} mm)")
        return self.ik(q_current_deg, target_tip_pos, target_R=target_R, **ik_kwargs)

    # ------------------------------------------------------------------
    # Motion planning
    # ------------------------------------------------------------------

    def plan_motion(
        self,
        q_start_deg: dict[str, float],
        q_end_deg: dict[str, float],
        n_steps: int = 20,
    ) -> list[dict[str, float]]:
        """
        Generate a smooth joint-space trajectory from start to end.

        Returns a list of n_steps command dicts (including start and end).
        Each dict maps motor name → degrees.
        Uses cosine interpolation for smoother acceleration profile.
        """
        motors = list(q_start_deg.keys())
        start = np.array([q_start_deg[m] for m in motors])
        end = np.array([q_end_deg[m] for m in motors])

        waypoints = []
        for t in np.linspace(0, 1, n_steps):
            alpha = 0.5 * (1 - np.cos(np.pi * t))
            q = start + alpha * (end - start)
            waypoints.append({m: float(v) for m, v in zip(motors, q)})
        return waypoints

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def current_tip_pos(self, q_deg: dict[str, float]) -> np.ndarray:
        """Return the current tool-tip position (metres) given joint angles."""
        pos, _ = self.tool_tip_pose(q_deg)
        return pos

    @staticmethod
    def zero_command() -> dict[str, float]:
        """Return a home command (all joints at 0 degrees)."""
        return dict(ZERO_COMMAND)

    def print_status(self, q_deg: dict[str, float]) -> None:
        """Print FK and tip position for the given joint config."""
        T = self.fk(q_deg)
        tip, R = self.tool_tip_pose(q_deg)
        print("EE  position :", T[:3, 3].round(4), "m")
        print("Tip position :", tip.round(4), "m")
        print("EE  rotation :\n", R.round(4))


# ---------------------------------------------------------------------------
# CLI smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="SO-101 IK smoke-test (lerobot backend)")
    ap.add_argument("--tool-offset", nargs=3, type=float, default=[0, 0, 0], metavar=("X", "Y", "Z"), help="Tool offset in EE local frame (metres)")
    ap.add_argument("--target", nargs=3, type=float, required=True, metavar=("X", "Y", "Z"), help="Target tip position in robot base frame (metres)")
    ap.add_argument("--steps", type=int, default=20, help="Trajectory waypoints")
    args = ap.parse_args()

    solver = SO101IKSolver(tool_offset=args.tool_offset)

    q0 = solver.zero_command()
    print("=== Zero config ===")
    solver.print_status(q0)

    print("\n=== Solving IK ===")
    q_target = solver.ik(q0, np.array(args.target))
    print("Target joints (deg):", {k: round(v, 2) for k, v in q_target.items()})

    solver.print_status(q_target)

    print(f"\n=== Trajectory ({args.steps} steps) ===")
    traj = solver.plan_motion(q0, q_target, n_steps=args.steps)
    for i, wp in enumerate(traj):
        print(f"  step {i:3d}:", {k: round(v, 1) for k, v in wp.items()})
