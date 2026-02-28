#!/usr/bin/env python
"""
move_robot.py — Interactive CLI to test-drive the SO-ARM100.

Usage:
    uv run python move_robot.py              # auto-detect port
    uv run python move_robot.py --port COM7  # explicit port

Commands (once connected):
    read          — read & print current joint positions
    home          — move to home position (0 -90 90 90 -90 90)
    zero          — move all joints to 0°
    move J0 J1 J2 J3 J4 J5 — move to specified angles (degrees)
    joint <idx> <deg>       — move a single joint (0-5) to <deg>
    wave          — small demo wave on wrist_roll
    limp          — disable torque (arm goes limp)
    hold          — enable torque (arm holds position)
    fk            — run forward kinematics on current pose
    ik X Y Z      — solve IK for (x, y, z) and move there
    quit / exit   — disconnect and exit
"""

import argparse
import sys
import time


def list_ports():
    """Pretty-print available serial ports."""
    import serial.tools.list_ports

    ports = list(serial.tools.list_ports.comports())
    if not ports:
        print("  (no serial ports found)")
        return
    for p in ports:
        marker = ""
        desc = (p.description or "").upper()
        hwid = (p.hwid or "").upper()
        if "CH343" in desc or "CH340" in desc or "1A86" in hwid:
            marker = "  <-- likely robot"
        print(f"  {p.device}: {p.description}{marker}")


def main():
    parser = argparse.ArgumentParser(description="Test-move the SO-ARM100 robot")
    parser.add_argument("--port", type=str, default=None, help="Serial port (e.g. COM7). Auto-detected if omitted.")
    args = parser.parse_args()

    print("=" * 60)
    print("  SO-ARM100 Motor Test Script")
    print("=" * 60)

    # ── List ports ──
    print("\nAvailable serial ports:")
    list_ports()

    # ── Auto-detect or use explicit port ──
    from src.motor_control import SO100MotorController, find_robot_port, MOTOR_NAMES

    port = args.port or find_robot_port()
    if not port:
        print("\n[!] Could not auto-detect robot port.")
        port = input("Enter port manually (e.g. COM7): ").strip()
        if not port:
            print("No port given, exiting.")
            sys.exit(1)

    # ── Connect ──
    print(f"\nConnecting to {port} ...")
    ctrl = SO100MotorController()
    result = ctrl.connect(port)

    if result.get("status") == "error":
        print(f"[ERROR] {result['error']}")
        sys.exit(1)

    print(f"[OK] Connected on {result['port']}")

    # Read initial positions
    pos = ctrl.read_positions()
    if "positions_deg" in pos:
        print("\nCurrent positions:")
        for name, deg in pos["positions_deg"].items():
            print(f"  {name:20s}: {deg:8.2f}°")
    else:
        print(f"  Warning: {pos.get('error', 'unknown error')}")

    # ── REPL ──
    HOME = [0.0, -90.0, 90.0, 90.0, -90.0, 90.0]

    print("\nType 'help' for commands, 'quit' to exit.\n")
    while True:
        try:
            line = input("robot> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not line:
            continue

        parts = line.split()
        cmd = parts[0].lower()

        # ── read ──
        if cmd == "read":
            pos = ctrl.read_positions()
            if "positions_deg" in pos:
                for name, deg in pos["positions_deg"].items():
                    print(f"  {name:20s}: {deg:8.2f}°")
                vals = pos.get("positions_list", [])
                if vals:
                    print(f"  → [{', '.join(f'{v:.1f}' for v in vals)}]")
            else:
                print(f"  Error: {pos.get('error')}")

        # ── home ──
        elif cmd == "home":
            print(f"  Moving to home: {HOME}")
            r = ctrl.write_joint_array(HOME)
            print(f"  {r}")
            time.sleep(1.5)

        # ── zero ──
        elif cmd == "zero":
            zeros = [0.0] * 6
            print(f"  Moving to zero: {zeros}")
            r = ctrl.write_joint_array(zeros)
            print(f"  {r}")
            time.sleep(1.5)

        # ── move J0 J1 J2 J3 J4 J5 ──
        elif cmd == "move":
            if len(parts) != 7:
                print("  Usage: move J0 J1 J2 J3 J4 J5  (6 angles in degrees)")
                continue
            try:
                angles = [float(x) for x in parts[1:]]
            except ValueError:
                print("  Invalid numbers.")
                continue
            print(f"  Moving to: {angles}")
            r = ctrl.write_joint_array(angles)
            print(f"  {r}")
            time.sleep(1.0)

        # ── joint <idx> <deg> ──
        elif cmd == "joint":
            if len(parts) != 3:
                print("  Usage: joint <idx 0-5> <degrees>")
                continue
            try:
                idx = int(parts[1])
                deg = float(parts[2])
            except ValueError:
                print("  Invalid input.")
                continue
            if not 0 <= idx <= 5:
                print("  Index must be 0-5.")
                continue
            name = MOTOR_NAMES[idx]
            print(f"  Moving {name} (joint {idx}) to {deg}°")
            r = ctrl.write_positions({name: deg})
            print(f"  {r}")
            time.sleep(1.0)

        # ── wave demo ──
        elif cmd == "wave":
            print("  Waving wrist_roll ±20° (3 cycles) ...")
            pos = ctrl.read_positions()
            if "positions_deg" not in pos:
                print("  Cannot read positions.")
                continue
            base = pos["positions_deg"].get("wrist_roll", 0.0)
            for _ in range(3):
                ctrl.write_positions({"wrist_roll": base + 20.0})
                time.sleep(0.5)
                ctrl.write_positions({"wrist_roll": base - 20.0})
                time.sleep(0.5)
            ctrl.write_positions({"wrist_roll": base})
            print("  Done.")

        # ── limp (disable torque) ──
        elif cmd == "limp":
            r = ctrl.disable_torque()
            print(f"  {r}")

        # ── hold (enable torque) ──
        elif cmd == "hold":
            r = ctrl.enable_torque()
            print(f"  {r}")

        # ── fk ──
        elif cmd == "fk":
            pos = ctrl.read_positions()
            if "positions_list" not in pos:
                print("  Cannot read positions.")
                continue
            try:
                import numpy as np
                from src.kinematics import get_kinematics

                kin = get_kinematics()
                q_rad = np.deg2rad(pos["positions_list"])
                ee = kin.get_ee_position(q_rad)
                print(f"  End-effector position:")
                print(f"    x={ee['x']:.4f}  y={ee['y']:.4f}  z={ee['z']:.4f} m")
                print(f"    roll={ee['roll']:.1f}  pitch={ee['pitch']:.1f}  yaw={ee['yaw']:.1f}°")
            except Exception as e:
                print(f"  FK error: {e}")

        # ── ik X Y Z ──
        elif cmd == "ik":
            if len(parts) != 4:
                print("  Usage: ik X Y Z  (metres)")
                continue
            try:
                x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
            except ValueError:
                print("  Invalid numbers.")
                continue
            try:
                import numpy as np
                from src.kinematics import get_kinematics

                kin = get_kinematics()
                # Use current pose as initial guess
                pos = ctrl.read_positions()
                init = None
                if "positions_list" in pos:
                    init = np.deg2rad(pos["positions_list"])

                result = kin.inverse_kinematics(
                    target_xyz=(x, y, z),
                    q_init_mech=init,
                )

                if result["success"]:
                    print(f"  IK converged (error: {result['error_mm']:.3f} mm)")
                    joints = result["joints_deg"]
                    print(f"  Joints: [{', '.join(f'{v:.1f}' for v in joints)}]")
                    confirm = input("  Send to robot? [Y/n] ").strip().lower()
                    if confirm in ("", "y", "yes"):
                        r = ctrl.write_joint_array(joints)
                        print(f"  {r}")
                    else:
                        print("  Skipped.")
                else:
                    print(f"  IK did NOT converge (error: {result['error_mm']:.3f} mm)")
                    print(f"  Joints: {result['joints_deg']}")
            except Exception as e:
                print(f"  IK error: {e}")

        # ── help ──
        elif cmd == "help":
            print("  Commands:")
            print("    read                  — read current joint positions")
            print("    home                  — move to home pose")
            print("    zero                  — move all joints to 0°")
            print("    move J0 J1 J2 J3 J4 J5 — move to angles (degrees)")
            print("    joint <0-5> <deg>     — move single joint")
            print("    wave                  — small wrist_roll demo")
            print("    limp                  — disable torque")
            print("    hold                  — enable torque")
            print("    fk                    — FK on current pose")
            print("    ik X Y Z             — solve IK and optionally move")
            print("    quit                  — disconnect and exit")

        # ── quit ──
        elif cmd in ("quit", "exit", "q"):
            break

        else:
            print(f"  Unknown command: {cmd}. Type 'help'.")

    # ── Cleanup ──
    print("Disconnecting...")
    ctrl.disconnect()
    print("Done.")


if __name__ == "__main__":
    main()
