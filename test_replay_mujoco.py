#!/usr/bin/env python3
"""
Replay a pre-computed IK trajectory in MuJoCo viewer.

Usage:
    # Step 1: generate trajectory (uses project venv with placo)
    .venv/bin/python test_pipeline_sim.py   # saves test_trajectory_data.json

    # Step 2: replay in MuJoCo (uses mjpython)
    mjpython test_replay_mujoco.py
    mjpython test_replay_mujoco.py --data test_trajectory_data.json --delay 0.08
"""

import json
import time
import numpy as np
import mujoco
import mujoco.viewer

SIM_DIR = "/Users/davidkorcak/Documents/eth/sem2/robot_learning/hw2_robot_control_mdps"
XML_PATH = f"{SIM_DIR}/so101_gym/assets/so100_pos_ctrl.xml"

# IK motor names → MuJoCo joint names
MOTOR_TO_MUJOCO = {
    "shoulder_pan": "Rotation",
    "shoulder_lift": "Pitch",
    "elbow_flex": "Elbow",
    "wrist_flex": "Wrist_Pitch",
    "wrist_roll": "Wrist_Roll",
    "gripper": "Jaw",
}


def set_joints(model, data, q_deg: dict[str, float]):
    """Set MuJoCo joint qpos + actuator ctrl from motor-name degrees dict."""
    for motor, deg in q_deg.items():
        mj_name = MOTOR_TO_MUJOCO.get(motor)
        if mj_name is None:
            continue
        rad = np.deg2rad(deg)
        jid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, mj_name)
        if jid >= 0:
            data.qpos[model.jnt_qposadr[jid]] = rad
        aid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_ACTUATOR, mj_name)
        if aid >= 0:
            data.ctrl[aid] = rad


def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="test_trajectory_data.json")
    ap.add_argument("--delay", type=float, default=0.08)
    args = ap.parse_args()

    with open(args.data) as f:
        tdata = json.load(f)

    trajectory = tdata["trajectory"]
    target = np.array(tdata["target_robot_m"])
    q_start = tdata["q_current_deg"]
    q_end = tdata["q_target_deg"]
    ik_error = tdata["ik_error_m"]
    dist = tdata["distance_m"]

    print(f"Target:     {target}")
    print(f"Distance:   {dist * 100:.1f} cm")
    print(f"IK error:   {ik_error * 1000:.2f} mm")
    print(f"Waypoints:  {len(trajectory)}")
    print(f"Start:      { {k: round(v, 1) for k, v in q_start.items()} }")
    print(f"End:        { {k: round(v, 1) for k, v in q_end.items()} }")
    print()

    model = mujoco.MjModel.from_xml_path(XML_PATH)
    data = mujoco.MjData(model)

    # Set initial position
    set_joints(model, data, q_start)
    mujoco.mj_forward(model, data)

    # Place target marker (green sphere)
    if model.nmocap > 0:
        data.mocap_pos[0] = target

    print("Launching viewer...")
    with mujoco.viewer.launch_passive(model, data) as viewer:
        # Show home for 2s
        t0 = time.time()
        while time.time() - t0 < 2.0 and viewer.is_running():
            mujoco.mj_step(model, data)
            viewer.sync()
            time.sleep(0.01)

        # Replay trajectory
        print("Replaying trajectory...")
        for i, wp in enumerate(trajectory):
            if not viewer.is_running():
                break
            set_joints(model, data, wp)
            for _ in range(20):
                mujoco.mj_step(model, data)
            viewer.sync()
            if i % 10 == 0 or i == len(trajectory) - 1:
                print(f"  waypoint {i}/{len(trajectory) - 1}")
            time.sleep(args.delay)

        print("Trajectory complete. Close the viewer to exit.")
        while viewer.is_running():
            mujoco.mj_step(model, data)
            viewer.sync()
            time.sleep(0.01)


if __name__ == "__main__":
    main()
