"""
Validation of SO101IKSolver.

The SO-101 placo solver operates in the URDF/placo coordinate frame.
The MuJoCo simulation uses a DIFFERENT frame:
  - MuJoCo Base body is rotated 90° around Z  (euler="0 0 1.5708")
  - MuJoCo ee_site is at Fixed_Jaw + [0,-0.06,0] with a -90°Z/-90°X rotation
  - MuJoCo joint limits differ from URDF (e.g. Pitch: -190° to +10° vs -90° to +90°)

Because of these fundamental frame differences, cross-validating placo FK positions
against MuJoCo ee_site positions in a naive way is meaningless.  Instead we:

  1. Test PLACO self-consistency: FK → IK → FK must close the loop
  2. Test tool offset math (geometrically correct in any frame)
  3. Test trajectory joint limits (using URDF limits, not MuJoCo limits)
  4. Test trajectory smoothness
  5. Quantify the MuJoCo ↔ placo frame transform (informational only)

Run from the project root:
    uv run python src/validate_ik.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

PROJECT = Path(__file__).parents[1]
HW_ROOT = Path("/Users/davidkorcak/Documents/eth/sem2/robot_learning/hw2_robot_control_mdps")
XML_PATH = HW_ROOT / "so101_gym/assets/so100_pos_ctrl.xml"

sys.path.insert(0, str(PROJECT / "src"))

import mujoco
from ik_solver import SO101IKSolver, _PLACO_TO_MOTOR, _LIMITS_DEG

# ---------------------------------------------------------------------------
# MuJoCo joint order (matches MuJoCo qpos[:] indexing)
# ---------------------------------------------------------------------------
MOTOR_ORDER = [
    "shoulder_pan",   # qpos[0]  Rotation     joint
    "shoulder_lift",  # qpos[1]  Pitch         joint
    "elbow_flex",     # qpos[2]  Elbow         joint
    "wrist_flex",     # qpos[3]  Wrist_Pitch   joint
    "wrist_roll",     # qpos[4]  Wrist_Roll    joint (note: joint name in MuJoCo XML)
    "gripper",        # qpos[5]  Jaw           joint
]

# MuJoCo home (radians) — from lerobot SO-101 documentation
HOME_QPOS = np.array([0.0, -1.57, 1.0, 1.0, 0.0, 0.02239])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def q_rad_to_cmd(q_rad: np.ndarray) -> dict[str, float]:
    """Convert (6,) radian MuJoCo-order array to motor-name degree dict."""
    return {m: float(np.rad2deg(q_rad[i])) for i, m in enumerate(MOTOR_ORDER)}


def cmd_to_q_rad(cmd: dict[str, float]) -> np.ndarray:
    """Convert motor-name degree dict to (6,) radian MuJoCo-order array."""
    return np.array([np.deg2rad(cmd[m]) for m in MOTOR_ORDER])


def mujoco_ee_pos(model, data, q_rad: np.ndarray) -> np.ndarray:
    """Run MuJoCo FK and return ee_site world position."""
    data.qpos[:len(q_rad)] = q_rad
    mujoco.mj_kinematics(model, data)
    mujoco.mj_comPos(model, data)
    return data.site("ee_site").xpos.copy()


def placo_sample_configs(n: int, rng: np.random.Generator) -> list[dict[str, float]]:
    """Sample n joint configs uniformly within URDF joint limits (degrees)."""
    configs = []
    for _ in range(n):
        cmd = {m: rng.uniform(lo, hi) for m, (lo, hi) in _LIMITS_DEG.items()}
        configs.append(cmd)
    return configs


# ---------------------------------------------------------------------------
# Test framework
# ---------------------------------------------------------------------------

PASS = "\033[92m✓ PASS\033[0m"
FAIL = "\033[91m✗ FAIL\033[0m"
results: list[tuple[str, bool, str]] = []


def report(name: str, ok: bool, detail: str = "") -> None:
    tag = PASS if ok else FAIL
    results.append((name, ok, detail))
    print(f"  {tag}  {name}")
    if detail:
        for line in detail.strip().splitlines():
            print(f"       {line}")


# ===========================================================================
# 0. MuJoCo frame info (informational — not pass/fail)
# ===========================================================================

def print_frame_info(solver: SO101IKSolver) -> None:
    """Print the frame relationship between MuJoCo ee_site and placo Fixed_Jaw."""
    print("\n── Frame info: MuJoCo ee_site vs placo Fixed_Jaw ──")
    model = mujoco.MjModel.from_xml_path(str(XML_PATH))
    data  = mujoco.MjData(model)

    # MuJoCo prints joint limits
    print("  MuJoCo joint ranges (rad → deg):")
    for i, name in enumerate(MOTOR_ORDER):
        lo, hi = model.jnt_range[i]
        print(f"    {name:20s}: [{np.rad2deg(lo):.1f}°, {np.rad2deg(hi):.1f}°]"
              f"  (URDF/placo: [{_LIMITS_DEG[name][0]:.1f}°, {_LIMITS_DEG[name][1]:.1f}°])")

    # Frame positions at zero config (all joints = 0)
    mj_zero = mujoco_ee_pos(model, data, np.zeros(6))
    pl_zero = solver.fk({m: 0.0 for m in MOTOR_ORDER})[:3, 3]
    print(f"\n  At zero config (all joints = 0 rad):")
    print(f"    MuJoCo  ee_site   : {mj_zero.round(4)} m")
    print(f"    Placo   Fixed_Jaw : {pl_zero.round(4)} m")
    print(f"  NOTE: Frames differ because MuJoCo base has euler='0 0 1.5708'")
    print(f"        and ee_site is offset [0,-0.06,0] from Fixed_Jaw with a -90°Z/-90°X rotation.")


# ===========================================================================
# 1. Placo FK self-consistency
# ===========================================================================

def test_placo_fk_consistency(solver: SO101IKSolver, n: int = 20) -> None:
    print("\n── Test 1: Placo FK self-consistency ──")
    rng     = np.random.default_rng(42)
    configs = placo_sample_configs(n, rng)

    # FK should map joints → EE position deterministically
    # Re-evaluate the same config twice and check it's identical
    all_ok = True
    max_err = 0.0
    for cmd in configs:
        p1 = solver.fk(cmd)[:3, 3]
        p2 = solver.fk(cmd)[:3, 3]
        err = np.linalg.norm(p1 - p2)
        max_err = max(max_err, err)
        if err > 1e-9:
            all_ok = False

    report(
        "Placo FK is deterministic (same config → same EE)",
        all_ok,
        f"max deviation across {n} configs: {max_err*1e9:.3f} nm",
    )

    # FK at home → EE should be in front of robot (placo frame: +Y forward roughly)
    q_home = q_rad_to_cmd(HOME_QPOS)
    T_home = solver.fk(q_home)
    p_home = T_home[:3, 3]
    print(f"  Placo FK at home config: Fixed_Jaw = {p_home.round(4)} m")
    report(
        "Placo FK at home: EE is in valid workspace (|pos| in [0.1, 0.6] m)",
        0.1 < np.linalg.norm(p_home) < 0.6,
        f"‖p_home‖ = {np.linalg.norm(p_home)*1000:.1f} mm",
    )


# ===========================================================================
# 2. Placo IK self-consistency (FK → IK → FK closes the loop)
# ===========================================================================

def test_placo_ik_consistency(solver: SO101IKSolver, n: int = 30) -> None:
    print("\n── Test 2: Placo IK self-consistency (FK → IK → FK) ──")
    rng     = np.random.default_rng(7)
    # Sample reachable configs within URDF limits
    # Keep shoulder_lift in a reasonable range to avoid degenerate poses
    configs = []
    for _ in range(n):
        cmd = {
            "shoulder_pan":  rng.uniform(-60, 60),
            "shoulder_lift": rng.uniform(-70, 70),
            "elbow_flex":    rng.uniform(-70, 60),
            "wrist_flex":    rng.uniform(-70, 70),
            "wrist_roll":    rng.uniform(-90, 90),
            "gripper":       rng.uniform(0, 30),
        }
        configs.append(cmd)

    tip_errors_mm = []
    for q_ref in configs:
        # FK: find the EE position for this config
        target_pos = solver.fk(q_ref)[:3, 3]

        # IK: solve from a nearby init
        q_init = {m: v + rng.uniform(-5, 5) for m, v in q_ref.items()}
        q_sol  = solver.ik(q_init, target_pos, tol_m=1e-4)

        # FK of solution: should match target
        achieved = solver.fk(q_sol)[:3, 3]
        err_mm   = np.linalg.norm(achieved - target_pos) * 1000
        tip_errors_mm.append(err_mm)

    tip_errors_mm = np.array(tip_errors_mm)
    ok = tip_errors_mm.mean() < 3.0 and tip_errors_mm.max() < 10.0

    report(
        "Placo IK → FK loop closes (mean < 3 mm, max < 10 mm)",
        ok,
        f"samples={n}  mean={tip_errors_mm.mean():.2f} mm  "
        f"max={tip_errors_mm.max():.2f} mm  "
        f"std={tip_errors_mm.std():.2f} mm",
    )


# ===========================================================================
# 3. Tool offset math
# ===========================================================================

def test_tool_offset() -> None:
    print("\n── Test 3: Tool offset math ──")

    q_home   = q_rad_to_cmd(HOME_QPOS)
    base_sol = SO101IKSolver(tool_offset=[0, 0, 0])
    T_ee     = base_sol.fk(q_home)
    R_ee, p_ee = T_ee[:3, :3], T_ee[:3, 3]

    offsets_to_test = [
        np.array([0.00,  0.00, -0.05]),   # 5 cm along EE -Z
        np.array([0.02,  0.00,  0.00]),   # 2 cm along EE +X
        np.array([0.00,  0.03,  0.00]),   # 3 cm along EE +Y
        np.array([0.01, -0.02,  0.03]),   # arbitrary 3D offset
    ]

    all_ok = True
    details = []
    for off in offsets_to_test:
        sol      = SO101IKSolver(tool_offset=off)
        p_tip, _ = sol.tool_tip_pose(q_home)
        expected = p_ee + R_ee @ off
        err_mm   = np.linalg.norm(p_tip - expected) * 1000
        ok       = err_mm < 0.1
        all_ok  &= ok
        details.append(f"offset={np.round(off*100,1)} cm  err={err_mm:.4f} mm  {'ok' if ok else 'FAIL'}")

    report("Tool offset correctly shifts tip by R_ee @ offset", all_ok, "\n".join(details))

    # IK with tool offset: solver must land tip, not EE frame, on target
    off = np.array([0.0, 0.0, -0.04])
    sol = SO101IKSolver(tool_offset=off)

    # Use a target that is reachable: offset from home tip in placo frame
    home_tip, _ = sol.tool_tip_pose(q_home)
    target_tip  = home_tip + np.array([0.03, 0.0, -0.02])

    q_sol       = sol.ik(q_home, target_tip, tol_m=1e-4)
    achieved, _ = sol.tool_tip_pose(q_sol)
    err_mm      = np.linalg.norm(achieved - target_tip) * 1000

    report(
        "IK with tool offset: tip reaches target (< 5 mm)",
        err_mm < 5.0,
        f"target:   {target_tip.round(4)} m\n"
        f"achieved: {achieved.round(4)} m\n"
        f"error:    {err_mm:.2f} mm",
    )


# ===========================================================================
# 4. Joint limits respected during plan_motion
# ===========================================================================

def test_joint_limits(solver: SO101IKSolver) -> None:
    print("\n── Test 4: Joint limits in plan_motion trajectories ──")

    rng = np.random.default_rng(99)
    # Generate start/end configs that are within URDF limits
    starts = placo_sample_configs(5, rng)
    ends   = placo_sample_configs(5, rng)

    violations = 0
    total      = 0

    for q_s, q_e in zip(starts, ends):
        traj = solver.plan_motion(q_s, q_e, n_steps=25)
        for wp in traj:
            total += 1
            for motor, val in wp.items():
                lo, hi = _LIMITS_DEG[motor]
                if val < lo - 0.5 or val > hi + 0.5:
                    violations += 1

    report(
        "All trajectory waypoints within URDF joint limits",
        violations == 0,
        f"checked {total} waypoints across 5 trajectories — {violations} violations",
    )


# ===========================================================================
# 5. Trajectory smoothness
# ===========================================================================

def test_trajectory_smoothness(solver: SO101IKSolver) -> None:
    print("\n── Test 5: Trajectory smoothness ──")

    rng = np.random.default_rng(13)
    q_s = q_rad_to_cmd(HOME_QPOS)
    # Pick a target slightly perturbed from home
    target = solver.fk(q_s)[:3, 3] + np.array([0.04, 0.02, -0.03])
    q_e    = solver.ik(q_s, target, tol_m=1e-4)

    traj = solver.plan_motion(q_s, q_e, n_steps=50)

    max_deg_step = 0.0
    for a, b in zip(traj[:-1], traj[1:]):
        for m in MOTOR_ORDER:
            max_deg_step = max(max_deg_step, abs(b[m] - a[m]))

    report(
        "Cosine trajectory has no large inter-step jumps (< 5°/step with 50 steps)",
        max_deg_step < 5.0,
        f"max per-step joint change = {max_deg_step:.3f}°",
    )

    # Check monotone in joint space (cosine interp is monotone start→end)
    # at least for each joint, all changes should be same sign
    for m in MOTOR_ORDER:
        vals = [wp[m] for wp in traj]
        diffs = np.diff(vals)
        monotone = np.all(diffs >= -0.01) or np.all(diffs <= 0.01)
        if not monotone:
            report(
                f"Joint {m} trajectory is monotone",
                False,
                f"diffs range: [{diffs.min():.3f}, {diffs.max():.3f}]",
            )
            return
    report("All joints move monotonically from start to end", True, "")


# ===========================================================================
# 6. ik_from_tip_to_tip round-trip
# ===========================================================================

def test_tip_to_tip(solver: SO101IKSolver) -> None:
    print("\n── Test 6: ik_from_tip_to_tip() ──")

    q_now   = q_rad_to_cmd(HOME_QPOS)
    cur_tip, _ = solver.tool_tip_pose(q_now)
    # Small reachable perturbation
    delta      = np.array([0.03, -0.02, -0.01])
    target_tip = cur_tip + delta

    q_sol = solver.ik_from_tip_to_tip(q_now, cur_tip, target_tip, tol_m=1e-4)
    achieved, _ = solver.tool_tip_pose(q_sol)
    err_mm = np.linalg.norm(achieved - target_tip) * 1000

    report(
        "ik_from_tip_to_tip reaches target (< 5 mm)",
        err_mm < 5.0,
        f"Δ requested: {(delta*1000).round(1)} mm\n"
        f"Δ achieved:  {((achieved - cur_tip)*1000).round(1)} mm\n"
        f"error:       {err_mm:.2f} mm",
    )


# ===========================================================================
# Main
# ===========================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  SO-101 IK Solver Validation")
    print("=" * 60)

    solver = SO101IKSolver(tool_offset=[0, 0, 0])

    print_frame_info(solver)  # informational, no pass/fail

    test_placo_fk_consistency(solver, n=20)
    test_placo_ik_consistency(solver, n=30)
    test_tool_offset()
    test_joint_limits(solver)
    test_trajectory_smoothness(solver)
    test_tip_to_tip(solver)

    # ── Summary ──
    print("\n" + "=" * 60)
    passed = sum(1 for _, ok, _ in results if ok)
    total  = len(results)
    print(f"  Results: {passed}/{total} passed")
    print("=" * 60)
    for name, ok, _ in results:
        tag = "✓" if ok else "✗"
        print(f"  {tag}  {name}")
    print()

    if passed < total:
        sys.exit(1)
