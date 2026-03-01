#!/usr/bin/env python3
"""
Test the full run-step pipeline WITHOUT hardware.

Simulates:
  - A target position in robot base frame (as if ArUco + cam-to-robot produced it)
  - Current joint angles (home / zero config)

Runs the real:
  - IK solver
  - Motion planner (cosine-interpolated trajectory)
  - FK verification at every waypoint

Outputs:
  - Joint trajectory table
  - Tip position at each waypoint
  - 3D matplotlib plot of the tip path + start/end markers
"""

import json
import numpy as np
import matplotlib

matplotlib.use("Agg")  # headless — saves to PNG
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401

from src.ik_solver import SO101IKSolver


def main():
    # ── Load the real plan step ──────────────────────────────────────────
    with open("data/plans/latest_plan.json") as f:
        plan = json.load(f)

    steps = plan["plan"]["task_plan"]["steps"]
    # Pick the PROBE step (step_id 3) — that's the one with probe_positive
    probe_step = next(s for s in steps if s.get("action") == "PROBE")
    print(f"Plan step: {probe_step['description']}")
    print(f"  probe_positive: {probe_step['parameters'].get('probe_positive')}")
    print()

    # ── Solver ───────────────────────────────────────────────────────────
    solver = SO101IKSolver()

    # ── Current joint state (simulated: home position) ───────────────────
    q_current = solver.zero_command()
    current_tip = solver.current_tip_pos(q_current)
    print("=== Current (home) configuration ===")
    solver.print_status(q_current)
    print()

    # ── Simulated target in robot base frame ─────────────────────────────
    # Realistic target: 10cm forward, 15cm down-Y, 5cm above base
    # (well within the arm's reachable workspace for probing an Arduino)
    target_robot = np.array([0.10, -0.15, 0.05])
    delta = target_robot - current_tip
    dist_m = float(np.linalg.norm(delta))

    print(f"=== Target ===")
    print(f"  position (robot frame): {target_robot} m")
    print(f"  delta from current tip: {delta.round(4)} m")
    print(f"  distance:               {dist_m * 100:.2f} cm")
    print()

    # ── Solve IK ─────────────────────────────────────────────────────────
    q_target = solver.ik(q_current, target_robot)
    achieved_tip = solver.current_tip_pos(q_target)
    ik_error = np.linalg.norm(achieved_tip - target_robot)

    print("=== IK Solution ===")
    print(f"  target joints (deg): { {k: round(v, 2) for k, v in q_target.items()} }")
    solver.print_status(q_target)
    print(f"  IK error: {ik_error * 1000:.3f} mm")
    print()

    # ── Plan trajectory ──────────────────────────────────────────────────
    n_steps = 40
    trajectory = solver.plan_motion(q_current, q_target, n_steps=n_steps)

    # ── Evaluate FK at every waypoint ────────────────────────────────────
    tip_positions = []
    print(f"=== Trajectory ({n_steps} waypoints) ===")
    print(
        f"{'step':>4s}  {'shoulder_pan':>12s} {'shoulder_lift':>13s} "
        f"{'elbow_flex':>10s} {'wrist_flex':>10s} {'wrist_roll':>10s} "
        f"{'tip_x':>7s} {'tip_y':>7s} {'tip_z':>7s}"
    )
    print("-" * 110)

    for i, wp in enumerate(trajectory):
        tip = solver.current_tip_pos(wp)
        tip_positions.append(tip.copy())
        if i % 5 == 0 or i == n_steps - 1:
            print(
                f"{i:4d}  {wp['shoulder_pan']:12.2f} {wp['shoulder_lift']:13.2f} "
                f"{wp['elbow_flex']:10.2f} {wp['wrist_flex']:10.2f} "
                f"{wp['wrist_roll']:10.2f} "
                f"{tip[0]:7.4f} {tip[1]:7.4f} {tip[2]:7.4f}"
            )

    tips = np.array(tip_positions)
    print()

    # ── Sanity checks ────────────────────────────────────────────────────
    final_tip = tips[-1]
    final_err = np.linalg.norm(final_tip - target_robot)
    print(f"=== Verification ===")
    print(f"  Start tip:  {tips[0].round(5)}")
    print(f"  End tip:    {final_tip.round(5)}")
    print(f"  Target:     {target_robot.round(5)}")
    print(f"  Final error: {final_err * 1000:.3f} mm")
    print(
        f"  Max inter-waypoint jump: "
        f"{max(np.linalg.norm(tips[i + 1] - tips[i]) for i in range(len(tips) - 1)) * 1000:.2f} mm"
    )
    print()

    # ── 3D Plot ──────────────────────────────────────────────────────────
    fig = plt.figure(figsize=(12, 8))
    ax = fig.add_subplot(111, projection="3d")

    # Trajectory path
    ax.plot(tips[:, 0], tips[:, 1], tips[:, 2], "b-", linewidth=2, label="Trajectory")

    # Start and end markers
    ax.scatter(
        *tips[0], color="green", s=100, marker="o", label=f"Start (home)", zorder=5
    )
    ax.scatter(
        *final_tip, color="red", s=100, marker="^", label=f"End (IK solution)", zorder=5
    )
    ax.scatter(
        *target_robot, color="orange", s=120, marker="*", label=f"Target", zorder=5
    )

    # Waypoint dots
    ax.scatter(tips[::5, 0], tips[::5, 1], tips[::5, 2], color="blue", s=15, alpha=0.5)

    ax.set_xlabel("X (m) - forward")
    ax.set_ylabel("Y (m) - left")
    ax.set_zlabel("Z (m) - up")
    ax.set_title(
        f"SO-101 IK Trajectory — {probe_step['parameters']['probe_positive']}\n"
        f"Distance: {dist_m * 100:.1f} cm | IK error: {ik_error * 1000:.2f} mm | "
        f"{n_steps} waypoints"
    )
    ax.legend(loc="upper left")

    # Equal aspect ratio
    max_range = (
        np.array([np.ptp(tips[:, 0]), np.ptp(tips[:, 1]), np.ptp(tips[:, 2])]).max()
        / 2.0
    )
    mid = tips.mean(axis=0)
    ax.set_xlim(mid[0] - max_range * 1.2, mid[0] + max_range * 1.2)
    ax.set_ylim(mid[1] - max_range * 1.2, mid[1] + max_range * 1.2)
    ax.set_zlim(mid[2] - max_range * 1.2, mid[2] + max_range * 1.2)

    out_path = "test_trajectory.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"Saved 3D trajectory plot to {out_path}")

    # ── Joint angle plot ─────────────────────────────────────────────────
    fig2, axes = plt.subplots(2, 3, figsize=(15, 8))
    joint_names = [
        "shoulder_pan",
        "shoulder_lift",
        "elbow_flex",
        "wrist_flex",
        "wrist_roll",
        "gripper",
    ]

    for idx, (ax2, name) in enumerate(zip(axes.flat, joint_names)):
        values = [wp[name] for wp in trajectory]
        ax2.plot(values, "b-", linewidth=1.5)
        ax2.axhline(
            y=q_current[name], color="g", linestyle="--", alpha=0.5, label="start"
        )
        ax2.axhline(y=q_target[name], color="r", linestyle="--", alpha=0.5, label="end")
        ax2.set_title(name)
        ax2.set_xlabel("step")
        ax2.set_ylabel("degrees")
        ax2.legend(fontsize=8)
        ax2.grid(True, alpha=0.3)

    fig2.suptitle(
        f"Joint Trajectories — {n_steps} waypoints (cosine interpolation)", fontsize=13
    )
    fig2.tight_layout()

    out_path2 = "test_joints.png"
    fig2.savefig(out_path2, dpi=150, bbox_inches="tight")
    print(f"Saved joint trajectory plot to {out_path2}")

    # ── Save trajectory data for MuJoCo replay ────────────────────────────
    traj_data = {
        "target_robot_m": target_robot.tolist(),
        "current_tip_m": current_tip.tolist(),
        "delta_m": delta.tolist(),
        "distance_m": round(dist_m, 5),
        "q_current_deg": {k: round(v, 2) for k, v in q_current.items()},
        "q_target_deg": {k: round(v, 2) for k, v in q_target.items()},
        "ik_error_m": round(ik_error, 6),
        "motion_steps": n_steps,
        "trajectory": [{k: round(v, 4) for k, v in wp.items()} for wp in trajectory],
        "tip_positions_m": tips.round(6).tolist(),
    }

    traj_json_path = "test_trajectory_data.json"
    with open(traj_json_path, "w") as f:
        json.dump(traj_data, f, indent=2)
    print(f"Saved trajectory data to {traj_json_path}")
    print()

    # ── Summary dict (what run-step would return) ────────────────────────
    print("=== Simulated /api/execute/run-step response (key fields) ===")
    response = {
        "status": "pending_confirmation",
        "target_robot_m": target_robot.tolist(),
        "current_tip_m": current_tip.tolist(),
        "delta_m": delta.tolist(),
        "distance_m": round(dist_m, 5),
        "q_current_deg": {k: round(v, 2) for k, v in q_current.items()},
        "q_target_deg": {k: round(v, 2) for k, v in q_target.items()},
        "ik_error_m": round(ik_error, 6),
        "motion_steps": n_steps,
    }
    print(json.dumps(response, indent=2))


if __name__ == "__main__":
    main()
