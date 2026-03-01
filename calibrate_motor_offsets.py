#!/usr/bin/env python3
"""
Motor-to-URDF offset calibration for SO-101 arm.

Uses the unit-specific follower-arm config (data/my_awesome_follower_arm.json)
to know the raw servo limits per joint.  Drives each joint to both limits
automatically, then asks the operator one yes/no question per joint to resolve
the sign direction.  Saves sign + offset_deg to:

    data/arm_cam_calib/motor_calibration.json

motor_control.py loads that file at runtime; it falls back to the hardcoded
defaults if the file is missing.

Usage
-----
    uv run python calibrate_motor_offsets.py
    uv run python calibrate_motor_offsets.py --port /dev/tty.usbmodem1234
    uv run python calibrate_motor_offsets.py --arm-config data/my_awesome_follower_arm.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# URDF joint limits (degrees) — from ik_solver._LIMITS_DEG
# These are the angles the PLACO model uses; sign/offset map motor→URDF.
# ---------------------------------------------------------------------------
URDF_LIMITS: dict[str, tuple[float, float]] = {
    "shoulder_pan":  (-91.7,  91.7),
    "shoulder_lift": (-90.0,  90.0),
    "elbow_flex":    (-91.7,  80.2),
    "wrist_flex":    (-95.7,  95.7),
    "wrist_roll":    (-180.0, 180.0),
    # gripper excluded
}

ARM_JOINTS = list(URDF_LIMITS.keys())

# Raw-to-motor-degree formula (homing_offset=0, STS3215 with 4096 steps/rev)
STEPS_PER_REV = 4096
MIDPOINT = 2048


def raw_to_motor_deg(raw: int) -> float:
    """Convert raw servo count → motor-native degrees (homing_offset=0)."""
    return (raw - MIDPOINT) * 360.0 / STEPS_PER_REV


def motor_deg_to_raw(deg: float) -> int:
    """Convert motor-native degrees → raw servo count."""
    return int(round(deg * STEPS_PER_REV / 360.0 + MIDPOINT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ask_yn(prompt: str) -> bool:
    while True:
        ans = input(f"{prompt} [y/n]: ").strip().lower()
        if ans in ("y", "yes"):
            return True
        if ans in ("n", "no"):
            return False


def _wait_and_read(bus, joint: str, seconds: float = 1.5) -> float:
    """Wait for motion to complete, then read position for `joint`."""
    time.sleep(seconds)
    pos = bus.sync_read("Present_Position")
    return float(pos[joint])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Calibrate motor→URDF joint offsets")
    ap.add_argument("--port", default=None, help="Serial port (auto-detect if omitted)")
    ap.add_argument(
        "--arm-config",
        default="data/my_awesome_follower_arm.json",
        help="Path to follower-arm JSON config (has homing_offset, range_min, range_max)",
    )
    ap.add_argument(
        "--out",
        default="data/arm_cam_calib/motor_calibration.json",
        help="Output calibration JSON",
    )
    ap.add_argument(
        "--speed", type=int, default=150,
        help="Raw Goal_Velocity for limit moves (0-4095, default 150 = slow)",
    )
    args = ap.parse_args()

    # ── Load arm config ────────────────────────────────────────────────────
    arm_cfg_path = Path(args.arm_config)
    if not arm_cfg_path.exists():
        print(f"ERROR: arm config not found: {arm_cfg_path}")
        sys.exit(1)
    with open(arm_cfg_path) as f:
        arm_cfg: dict = json.load(f)
    print(f"Loaded arm config: {arm_cfg_path}")

    # ── Auto-detect port ───────────────────────────────────────────────────
    port = args.port
    if not port:
        from src.motor_control import find_robot_port
        port = find_robot_port()
        if not port:
            print("ERROR: No robot port found. Specify with --port")
            sys.exit(1)
    print(f"Using port: {port}")

    # ── Connect motor bus (5 arm joints only, gripper excluded) ────────────
    from lerobot.motors import Motor, MotorNormMode
    from lerobot.motors.feetech import FeetechMotorsBus
    from lerobot.motors.motors_bus import MotorCalibration

    motors = {
        name: Motor(arm_cfg[name]["id"], "sts3215", MotorNormMode.DEGREES)
        for name in ARM_JOINTS
    }
    calibration = {
        name: MotorCalibration(
            id=arm_cfg[name]["id"],
            drive_mode=arm_cfg[name]["drive_mode"],
            homing_offset=0,      # keep raw-centered so formula is predictable
            range_min=0,
            range_max=STEPS_PER_REV - 1,
        )
        for name in ARM_JOINTS
    }
    bus = FeetechMotorsBus(port=port, motors=motors, calibration=calibration)
    bus.connect(handshake=False)
    print("Connected.\n")

    # Enable torque & set slow speed
    bus.sync_write("Torque_Enable", {m: 1 for m in ARM_JOINTS})
    bus.sync_write("Goal_Velocity", {m: args.speed for m in ARM_JOINTS})
    print(f"Torque ON, speed={args.speed} (raw Goal_Velocity).\n")

    results: dict[str, dict] = {}

    try:
        for joint in ARM_JOINTS:
            cfg = arm_cfg[joint]
            raw_min = cfg["range_min"]
            raw_max = cfg["range_max"]
            deg_min = raw_to_motor_deg(raw_min)
            deg_max = raw_to_motor_deg(raw_max)

            urdf_lo, urdf_hi = URDF_LIMITS[joint]

            print(f"{'='*60}")
            print(f"  Joint: {joint}")
            print(f"  Physical range (raw):  [{raw_min}, {raw_max}]")
            print(f"  Motor-deg range:       [{deg_min:.1f}°, {deg_max:.1f}°]")
            print(f"  URDF limits:           [{urdf_lo}°, {urdf_hi}°]")
            print(f"{'='*60}")

            # ── Move to raw_min ─────────────────────────────────────────────
            input(f"  Press Enter to drive '{joint}' to its RAW-MIN limit ({raw_min}) …")
            bus.sync_write("Goal_Position", {joint: deg_min})
            motor_at_raw_min = _wait_and_read(bus, joint, seconds=2.0)
            print(f"  Motor reading at raw_min: {motor_at_raw_min:.2f}°")

            # ── Move to raw_max ─────────────────────────────────────────────
            input(f"  Press Enter to drive '{joint}' to its RAW-MAX limit ({raw_max}) …")
            bus.sync_write("Goal_Position", {joint: deg_max})
            motor_at_raw_max = _wait_and_read(bus, joint, seconds=2.0)
            print(f"  Motor reading at raw_max: {motor_at_raw_max:.2f}°")

            # ── Determine sign ──────────────────────────────────────────────
            # The arm is now at raw_max.  Ask if this looks like the URDF min.
            print()
            print(f"  The arm is currently at '{joint}' RAW-MAX position.")
            print(f"  URDF-min means: {'most negative angle, e.g. fully retracted/rotated negative'}")
            raw_max_is_urdf_min = _ask_yn(
                f"  Does the current (raw_max) position look like the URDF MINIMUM ({urdf_lo}°)?"
            )

            if raw_max_is_urdf_min:
                # raw_max → urdf_min,  raw_min → urdf_max
                sign_float = (urdf_lo - urdf_hi) / (motor_at_raw_max - motor_at_raw_min)
            else:
                # raw_max → urdf_max,  raw_min → urdf_min
                sign_float = (urdf_hi - urdf_lo) / (motor_at_raw_max - motor_at_raw_min)

            sign = int(round(sign_float))
            if sign == 0:
                sign = 1  # fallback
            offset_recomputed = (
                urdf_lo - sign * motor_at_raw_min
                if not raw_max_is_urdf_min
                else urdf_lo - sign * motor_at_raw_max
            )

            print(f"\n  sign={sign},  offset={offset_recomputed:.2f}°  "
                  f"  (raw sign estimate: {sign_float:.3f})")

            # Verify: at motor_at_raw_min → urdf should be ≈ urdf_lo or urdf_hi
            urdf_check_min = sign * motor_at_raw_min + offset_recomputed
            urdf_check_max = sign * motor_at_raw_max + offset_recomputed
            print(f"  Verify: raw_min motor={motor_at_raw_min:.1f}° → urdf={urdf_check_min:.1f}°  "
                  f"(expected ≈ {urdf_lo if not raw_max_is_urdf_min else urdf_hi}°)")
            print(f"  Verify: raw_max motor={motor_at_raw_max:.1f}° → urdf={urdf_check_max:.1f}°  "
                  f"(expected ≈ {urdf_lo if raw_max_is_urdf_min else urdf_hi}°)")

            results[joint] = {"sign": sign, "offset_deg": round(offset_recomputed, 2)}
            print()

    finally:
        # Return each joint to its midpoint and disable torque
        print("Returning joints to midpoint and disabling torque …")
        bus.sync_write("Goal_Position", {m: 0.0 for m in ARM_JOINTS})
        time.sleep(2.0)
        bus.sync_write("Torque_Enable", {m: 0 for m in ARM_JOINTS})
        bus.disconnect(disable_torque=False)
        print("Disconnected.\n")

    # ── Save ───────────────────────────────────────────────────────────────
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)

    print("=" * 60)
    print(f"Calibration saved to: {out_path}")
    print(json.dumps(results, indent=2))
    print()
    print("Restart the server to pick up the new calibration.")
    print("=" * 60)


if __name__ == "__main__":
    main()
