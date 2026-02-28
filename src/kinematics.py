"""
Inverse Kinematics for SO-ARM100 / SO-ARM101

Ported from Argo-Robot/controls (MIT License, Leonardo Bertelli)
  https://github.com/Argo-Robot/controls

DH-based forward/inverse kinematics with Damped Least Squares IK solver,
SLERP orientation interpolation, and mechanical ↔ DH angle conversions
for the SO-ARM100 5-DOF robotic arm.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from scipy.spatial.transform import Rotation as R


# ── utility helpers ──────────────────────────────────────────────────────────

class RobotUtils:
    """Static math utilities for robotics."""

    @staticmethod
    def inv_homog_mat(T: np.ndarray) -> np.ndarray:
        """Efficient inverse of a 4×4 homogeneous transform."""
        Rot = T[:3, :3]
        t = T[:3, 3]
        T_inv = np.eye(4)
        T_inv[:3, :3] = Rot.T
        T_inv[:3, 3] = -Rot.T @ t
        return T_inv

    @staticmethod
    def calc_lin_err(T_current: np.ndarray, T_desired: np.ndarray) -> np.ndarray:
        """Position error (3-vector)."""
        return T_desired[:3, 3] - T_current[:3, 3]

    @staticmethod
    def calc_ang_err(T_current: np.ndarray, T_desired: np.ndarray) -> np.ndarray:
        """Angular error via cross-product formula (3-vector)."""
        Rc = T_current[:3, :3]
        Rd = T_desired[:3, :3]
        return 0.5 * (
            np.cross(Rc[:, 0], Rd[:, 0])
            + np.cross(Rc[:, 1], Rd[:, 1])
            + np.cross(Rc[:, 2], Rd[:, 2])
        )

    @staticmethod
    def calc_dh_matrix(dh: list, theta: float) -> np.ndarray:
        """Standard DH transformation matrix."""
        _, d, a, alpha = dh
        ct, st = np.cos(theta), np.sin(theta)
        ca, sa = np.cos(alpha), np.sin(alpha)
        return np.array([
            [ct, -st * ca,  st * sa, a * ct],
            [st,  ct * ca, -ct * sa, a * st],
            [0,   sa,       ca,      d     ],
            [0,   0,        0,       1     ],
        ])

    @staticmethod
    def dls_right_pseudoinv(J: np.ndarray, lambda_val: float = 0.001) -> np.ndarray:
        """Damped Least Squares right pseudo-inverse."""
        JT = J.T
        JTJ = JT @ J
        return np.linalg.inv(JTJ + lambda_val * np.eye(JTJ.shape[0])) @ JT

    @staticmethod
    def calc_distance(p1: np.ndarray, p2: np.ndarray) -> float:
        return float(np.linalg.norm(p2 - p1))


# ── SO-ARM100 robot model (DH convention) ───────────────────────────────────

@dataclass
class SO100Model:
    """
    SO-ARM100 robot described by its DH table.

    DH table (standard convention): [theta, d, a, alpha]
    Joint order: shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll
    The 6th motor (gripper) is not part of the kinematic chain.
    """

    # DH table — theta column is the variable, rest are constants
    dh_table: list = field(default_factory=lambda: [
        [0, 0.0542, 0.0304, np.pi / 2],  # Joint 1 – shoulder_pan
        [0, 0.0,    0.116,  0.0       ],  # Joint 2 – shoulder_lift
        [0, 0.0,    0.1347, 0.0       ],  # Joint 3 – elbow_flex
        [0, 0.0,    0.0,   -np.pi / 2 ],  # Joint 4 – wrist_flex
        [0, 0.0609, 0.0,    0.0       ],  # Joint 5 – wrist_roll
    ])

    # worldTbase: base-frame DH aligned wrt SO100 simulator
    worldTbase: np.ndarray = field(default_factory=lambda: np.array([
        [ 0.0,  1.0,  0.0,  0.0   ],
        [-1.0,  0.0,  0.0, -0.0453],
        [ 0.0,  0.0,  1.0,  0.0647],
        [ 0.0,  0.0,  0.0,  1.0   ],
    ]))

    # nTtool: n-frame DH → tool (end-effector)
    nTtool: np.ndarray = field(default_factory=lambda: np.array([
        [ 0.0,  0.0, -1.0,  0.0],
        [ 1.0,  0.0,  0.0,  0.0],
        [ 0.0, -1.0,  0.0,  0.0],
        [ 0.0,  0.0,  0.0,  1.0],
    ]))

    # Mechanical joint limits (radians) — 6 values (includes gripper)
    mech_joint_limits_low: np.ndarray = field(
        default_factory=lambda: np.array([-2.2, -3.1416, 0.0, -2.0, -3.1416, -0.2])
    )
    mech_joint_limits_up: np.ndarray = field(
        default_factory=lambda: np.array([2.2, 0.2, 3.1416, 1.8, 3.1416, 2.0])
    )

    # Motor names matching lerobot convention
    motor_names: list = field(default_factory=lambda: [
        "shoulder_pan", "shoulder_lift", "elbow_flex",
        "wrist_flex", "wrist_roll", "gripper",
    ])

    # ── DH ↔ mechanical angle conversions ──

    @staticmethod
    def _beta() -> float:
        return np.deg2rad(14.45)

    def mech_to_dh(self, q_mech: np.ndarray) -> np.ndarray:
        """Convert 6-DOF mechanical angles → 5-DOF DH angles (drops gripper)."""
        beta = self._beta()
        q_dh = np.zeros(5)
        q_dh[0] =  q_mech[0]
        q_dh[1] = -q_mech[1] - beta
        q_dh[2] = -q_mech[2] + beta
        q_dh[3] = -q_mech[3] - np.pi / 2
        q_dh[4] = -q_mech[4] - np.pi / 2
        return q_dh

    def dh_to_mech(self, q_dh: np.ndarray) -> np.ndarray:
        """Convert 5-DOF DH angles → 5-DOF mechanical angles (no gripper)."""
        beta = self._beta()
        q_mech = np.zeros(5)
        q_mech[0] =  q_dh[0]
        q_mech[1] = -q_dh[1] - beta
        q_mech[2] = -q_dh[2] + beta
        q_mech[3] = -q_dh[3] - np.pi / 2
        q_mech[4] = -q_dh[4] - np.pi / 2
        return q_mech

    @property
    def n_joints(self) -> int:
        return len(self.dh_table)


# ── Kinematics engine ───────────────────────────────────────────────────────

class SOArmKinematics:
    """
    Forward & inverse kinematics for SO-ARM100 using DH convention.

    All public methods work in **mechanical angles** (6-DOF, radians).
    Internally converts to DH angles for computation.
    """

    def __init__(self, model: Optional[SO100Model] = None):
        self.model = model or SO100Model()

    # ── forward kinematics ───────────────────────────────────────────────

    def _fk_baseTn(self, q_dh: np.ndarray) -> np.ndarray:
        """FK from base to n-frame (DH chain only)."""
        T = np.eye(4)
        for i in range(len(q_dh)):
            T = T @ RobotUtils.calc_dh_matrix(self.model.dh_table[i], q_dh[i])
        return T

    def forward_kinematics(self, q_mech: np.ndarray) -> np.ndarray:
        """
        Compute end-effector pose (4×4 homogeneous matrix) from mechanical angles.

        Parameters
        ----------
        q_mech : array-like, shape (6,)
            Mechanical joint angles in radians
            [shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll, gripper].

        Returns
        -------
        worldTtool : ndarray, shape (4, 4)
            End-effector pose in world frame.
        """
        q_mech = np.asarray(q_mech, dtype=float)
        q_dh = self.model.mech_to_dh(q_mech)
        baseTn = self._fk_baseTn(q_dh)
        return self.model.worldTbase @ baseTn @ self.model.nTtool

    def get_ee_position(self, q_mech: np.ndarray) -> dict:
        """
        Return end-effector position + orientation from mechanical angles.

        Returns dict with keys: x, y, z (metres), roll, pitch, yaw (degrees).
        """
        T = self.forward_kinematics(q_mech)
        pos = T[:3, 3]
        rpy = R.from_matrix(T[:3, :3]).as_euler("xyz", degrees=True)
        return {
            "x": float(pos[0]),
            "y": float(pos[1]),
            "z": float(pos[2]),
            "roll": float(rpy[0]),
            "pitch": float(rpy[1]),
            "yaw": float(rpy[2]),
        }

    # ── geometric Jacobian ───────────────────────────────────────────────

    def _jacobian_base(self, q_dh: np.ndarray) -> np.ndarray:
        """6×5 geometric Jacobian in base frame."""
        DOF = len(q_dh)
        J = np.zeros((6, DOF))
        P = np.zeros((3, DOF + 1))
        z = np.zeros((3, DOF + 1))
        base_P_i = np.eye(4)

        z[:, 0] = np.array([0, 0, 1])

        for i in range(DOF):
            i_T_ip1 = RobotUtils.calc_dh_matrix(self.model.dh_table[i], q_dh[i])
            base_P_i = base_P_i @ i_T_ip1
            P[:, i + 1] = base_P_i[:3, 3]
            z[:, i + 1] = base_P_i[:3, 2]

        for i in range(DOF):
            J[:3, i] = np.cross(z[:, i], P[:, DOF] - P[:, i])
            J[3:, i] = z[:, i]

        return J

    # ── inverse kinematics ───────────────────────────────────────────────

    def _ik_step(
        self,
        q_dh: np.ndarray,
        T_desired_baseTn: np.ndarray,
        use_orientation: bool = True,
        k: float = 0.8,
        n_iter: int = 50,
    ) -> np.ndarray:
        """One IK interpolation step (DH space)."""
        q = q_dh.copy()
        for _ in range(n_iter):
            T_current = self._fk_baseTn(q)
            err_lin = RobotUtils.calc_lin_err(T_current, T_desired_baseTn)

            if use_orientation:
                err_ang = RobotUtils.calc_ang_err(T_current, T_desired_baseTn)
                error = np.concatenate((err_lin, err_ang))
                J = self._jacobian_base(q)
            else:
                error = err_lin
                J = self._jacobian_base(q)[:3, :]

            if np.linalg.norm(error) < 1e-5:
                break

            J_pinv = RobotUtils.dls_right_pseudoinv(J)
            q = q + k * (J_pinv @ error)

        return q

    def _interp_poses(
        self,
        T_start: np.ndarray,
        T_final: np.ndarray,
        freq: float = 100,
        trans_speed: float = 0.1,
        rot_speed: float = 0.5,
    ) -> list[np.ndarray]:
        """Generate interpolated poses (SLERP for orientation)."""
        t_start = T_start[:3, 3]
        t_final = T_final[:3, 3]
        R_start = T_start[:3, :3]
        R_final = T_final[:3, :3]
        q_s = R.from_matrix(R_start).as_quat()
        q_f = R.from_matrix(R_final).as_quat()

        trans_dist = np.linalg.norm(t_final - t_start)
        t_trans = trans_dist / trans_speed if trans_speed > 0 else 0

        rotvec = R.from_matrix(R_final @ R_start.T).as_rotvec()
        ang_dist = np.linalg.norm(rotvec)
        t_rot = ang_dist / rot_speed if rot_speed > 0 else 0

        total_time = max(t_trans, t_rot)
        n_steps = max(1, int(np.ceil(freq * total_time)))

        q_s = q_s / np.linalg.norm(q_s)
        q_f = q_f / np.linalg.norm(q_f)
        dot = np.dot(q_s, q_f)
        if dot < 0:
            q_f = -q_f
            dot = -dot
        dot = np.clip(dot, -1.0, 1.0)
        theta = np.arccos(dot)
        sin_theta = np.sin(theta)

        poses = []
        for i in range(n_steps + 1):
            s = i / n_steps if n_steps > 0 else 1.0
            t_interp = (1 - s) * t_start + s * t_final
            if np.isclose(sin_theta, 0.0):
                q_interp = q_f
            else:
                theta_t = theta * s
                w0 = np.sin(theta - theta_t) / sin_theta
                w1 = np.sin(theta_t) / sin_theta
                q_interp = w0 * q_s + w1 * q_f
            q_interp = q_interp / np.linalg.norm(q_interp)

            T = np.eye(4)
            T[:3, :3] = R.from_quat(q_interp).as_matrix()
            T[:3, 3] = t_interp
            poses.append(T)

        return poses

    def inverse_kinematics(
        self,
        target_xyz: tuple[float, float, float],
        target_rpy_deg: Optional[tuple[float, float, float]] = None,
        q_init_mech: Optional[np.ndarray] = None,
        gripper: float = 0.0,
        use_orientation: bool = True,
        k: float = 0.8,
        n_iter: int = 50,
    ) -> dict:
        """
        Compute joint angles to reach a target end-effector position.

        Parameters
        ----------
        target_xyz : (x, y, z)
            Desired end-effector position in metres (world frame).
        target_rpy_deg : (roll, pitch, yaw) or None
            Desired orientation in degrees. If None, orientation is not tracked.
        q_init_mech : array-like, shape (6,), optional
            Initial joint guess (mechanical angles, radians).
            Defaults to a neutral "home" pose.
        gripper : float
            Gripper angle in radians (passed through unchanged).
        use_orientation : bool
            Whether to track orientation in IK.
        k : float
            IK gain (0 < k ≤ 1).
        n_iter : int
            Max iterations per interpolation step.

        Returns
        -------
        dict with keys:
            joints_deg : list[float] — 6 mechanical joint angles (degrees)
            joints_rad : list[float] — 6 mechanical joint angles (radians)
            joint_names : list[str]
            ee_position : dict — achieved end-effector position
            error_mm : float — position error in millimetres
            success : bool
        """
        if target_rpy_deg is None:
            use_orientation = False

        # Default home pose (mechanical)
        if q_init_mech is None:
            q_init_mech = np.array([0.0, -np.pi / 2, np.pi / 2, np.pi / 2, -np.pi / 2, np.pi / 2])
        else:
            q_init_mech = np.asarray(q_init_mech, dtype=float)

        # Build target 4×4
        T_goal = np.eye(4)
        T_goal[:3, 3] = target_xyz
        if target_rpy_deg is not None:
            rpy_rad = np.deg2rad(target_rpy_deg)
            T_goal[:3, :3] = R.from_euler("xyz", rpy_rad).as_matrix()
        else:
            # Use orientation from start pose
            T_start = self.forward_kinematics(q_init_mech)
            T_goal[:3, :3] = T_start[:3, :3]

        # Convert to DH
        q_init_dh = self.model.mech_to_dh(q_init_mech)

        # Convert goal from worldTtool → baseTn
        desired_baseTn = (
            RobotUtils.inv_homog_mat(self.model.worldTbase)
            @ T_goal
            @ RobotUtils.inv_homog_mat(self.model.nTtool)
        )

        # Interpolate from current to goal
        current_baseTn = self._fk_baseTn(q_init_dh)
        interp_poses = self._interp_poses(current_baseTn, desired_baseTn)

        q_dh = q_init_dh.copy()
        for T_interp in interp_poses:
            q_dh = self._ik_step(q_dh, T_interp, use_orientation, k, n_iter)

        # Convert result back to mechanical angles
        q_mech_5 = self.model.dh_to_mech(q_dh)
        q_mech_6 = np.append(q_mech_5, gripper)

        # Verify result
        T_achieved = self.forward_kinematics(q_mech_6)
        err_lin = RobotUtils.calc_lin_err(T_achieved, T_goal)
        error_m = float(np.linalg.norm(err_lin))

        ee_pos = self.get_ee_position(q_mech_6)

        return {
            "joints_deg": np.rad2deg(q_mech_6).tolist(),
            "joints_rad": q_mech_6.tolist(),
            "joint_names": self.model.motor_names,
            "ee_position": ee_pos,
            "error_mm": round(error_m * 1000, 3),
            "success": error_m < 0.01,  # < 10 mm
        }

    def check_joint_limits(self, q_mech: np.ndarray) -> list[str]:
        """Check if mechanical angles are within limits. Returns list of violations."""
        q_mech = np.asarray(q_mech, dtype=float)
        violations = []
        for i in range(len(q_mech)):
            lo = self.model.mech_joint_limits_low[i]
            hi = self.model.mech_joint_limits_up[i]
            if not (lo <= q_mech[i] <= hi):
                violations.append(
                    f"{self.model.motor_names[i]}: {np.rad2deg(q_mech[i]):.1f}° "
                    f"outside [{np.rad2deg(lo):.1f}°, {np.rad2deg(hi):.1f}°]"
                )
        return violations


# ── Convenience singleton ────────────────────────────────────────────────────

_kin: Optional[SOArmKinematics] = None


def get_kinematics() -> SOArmKinematics:
    global _kin
    if _kin is None:
        _kin = SOArmKinematics()
    return _kin


# ── CLI for quick testing ───────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse, json

    parser = argparse.ArgumentParser(description="SO-ARM100 FK/IK tool")
    sub = parser.add_subparsers(dest="cmd")

    # FK subcommand
    fk_p = sub.add_parser("fk", help="Forward kinematics: joints → EE pose")
    fk_p.add_argument("joints", nargs=6, type=float,
                       help="6 joint angles in degrees (shoulder_pan shoulder_lift elbow_flex wrist_flex wrist_roll gripper)")

    # IK subcommand
    ik_p = sub.add_parser("ik", help="Inverse kinematics: EE position → joints")
    ik_p.add_argument("--xyz", nargs=3, type=float, required=True,
                       help="Target x y z in metres")
    ik_p.add_argument("--rpy", nargs=3, type=float, default=None,
                       help="Target roll pitch yaw in degrees (optional)")
    ik_p.add_argument("--init", nargs=6, type=float, default=None,
                       help="Initial joint guess in degrees (optional)")

    args = parser.parse_args()
    kin = get_kinematics()

    if args.cmd == "fk":
        q_deg = np.array(args.joints)
        q_rad = np.deg2rad(q_deg)
        result = kin.get_ee_position(q_rad)
        print(f"\nJoints (deg): {q_deg.tolist()}")
        print(f"EE position:  x={result['x']:.4f}  y={result['y']:.4f}  z={result['z']:.4f} m")
        print(f"EE orient:    roll={result['roll']:.2f}  pitch={result['pitch']:.2f}  yaw={result['yaw']:.2f} deg")

    elif args.cmd == "ik":
        init = np.deg2rad(args.init) if args.init else None
        result = kin.inverse_kinematics(
            target_xyz=tuple(args.xyz),
            target_rpy_deg=tuple(args.rpy) if args.rpy else None,
            q_init_mech=init,
        )
        print(f"\nTarget:  xyz={args.xyz}")
        print(f"Success: {result['success']}  (error={result['error_mm']:.3f} mm)")
        print(f"Joints (deg):  {[f'{j:.2f}' for j in result['joints_deg']]}")
        print(f"Achieved EE:   x={result['ee_position']['x']:.4f}  y={result['ee_position']['y']:.4f}  z={result['ee_position']['z']:.4f} m")
        violations = kin.check_joint_limits(np.array(result["joints_rad"]))
        if violations:
            print(f"⚠ Joint limit violations: {violations}")
        else:
            print("✓ All joints within limits")

    else:
        # Default demo
        print("SO-ARM100 Kinematics Demo")
        print("=" * 50)

        # Home pose
        q_home = np.array([0.0, -90.0, 90.0, 90.0, -90.0, 90.0])
        q_home_rad = np.deg2rad(q_home)
        ee = kin.get_ee_position(q_home_rad)
        print(f"\nHome pose joints (deg): {q_home.tolist()}")
        print(f"Home EE:  x={ee['x']:.4f}  y={ee['y']:.4f}  z={ee['z']:.4f} m")
        print(f"          roll={ee['roll']:.2f}  pitch={ee['pitch']:.2f}  yaw={ee['yaw']:.2f} deg")

        # IK to a nearby point
        target = (ee["x"], ee["y"], ee["z"] - 0.05)
        print(f"\nIK target: move down 50mm → xyz={target}")
        result = kin.inverse_kinematics(target_xyz=target, q_init_mech=q_home_rad)
        print(f"Success: {result['success']}  error={result['error_mm']:.3f} mm")
        print(f"Joints (deg): {[f'{j:.2f}' for j in result['joints_deg']]}")

        print("\nUsage:")
        print("  uv run python src/kinematics.py fk 0 -90 90 90 -90 90")
        print("  uv run python src/kinematics.py ik --xyz 0.0 -0.2 0.15")
        print("  uv run python src/kinematics.py ik --xyz 0.0 -0.2 0.15 --rpy 0 90 0")
