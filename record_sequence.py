"""
Record sequence: Home → Pos1 → Home → Pos2
Stay 7 seconds at each position.
Uses the server API for IK + motor control.
"""

import requests, time, sys

API = "http://localhost:8000"
SPEED = 10  # slow & safe
HOLD_SEC = 3

HOME = [3, -26, -7, 92, -65, 39]  # degrees

POS1 = {"x": 0.0466, "y": -0.3202, "z": 0.0099, "roll": 87.5, "pitch": 1.2, "yaw": 34.6}
POS2 = {"x": 0.0160, "y": -0.297, "z": 0.0110, "roll": 90.7, "pitch": -0.3, "yaw": 28.5}


def check_server():
    r = requests.get(f"{API}/api/health")
    r.raise_for_status()
    print("✅ Server online")


def ensure_connected():
    r = requests.get(f"{API}/api/motor/status")
    data = r.json()
    if data.get("connected"):
        print(f"✅ Robot connected on {data['port']}")
        return
    print("Connecting to robot...")
    r = requests.post(f"{API}/api/motor/connect", json={})
    r.raise_for_status()
    print(f"✅ Connected on {r.json()['port']}")


def move_to(joints_deg, label="target"):
    """Send joint angles to robot and wait for it to arrive."""
    print(f"  → Moving to {label}: {[round(j,1) for j in joints_deg]}")
    r = requests.post(f"{API}/api/motor/move", json={"joints_deg": joints_deg, "speed": SPEED})
    r.raise_for_status()
    print(f"  ✅ Sent to {r.json()['motors_moved']} motors")


def solve_ik(pos, label="target"):
    """Solve IK for a position and return joint angles."""
    print(f"  Solving IK for {label}...")
    r = requests.post(f"{API}/api/kinematics/ik", json={
        "x": pos["x"], "y": pos["y"], "z": pos["z"],
        "roll": pos.get("roll"), "pitch": pos.get("pitch"), "yaw": pos.get("yaw"),
        "gripper_deg": 39.0,  # keep gripper same as home
    })
    r.raise_for_status()
    data = r.json()
    joints = data["joints_list"]
    err = data["error_mm"]
    ok = data["success"]
    print(f"  IK result: error={err:.2f}mm  success={ok}")
    print(f"  Joints: {[round(j,1) for j in joints]}")
    if not ok:
        print(f"  ⚠️  IK error > 10mm — proceed anyway? (y/n)")
        if input().strip().lower() != "y":
            sys.exit(1)
    return joints


def hold(seconds, label):
    """Hold position for N seconds with countdown."""
    for remaining in range(seconds, 0, -1):
        print(f"  ⏱  {label} — holding {remaining}s...", end="\r")
        time.sleep(1)
    print(f"  ⏱  {label} — done!              ")


def main():
    check_server()
    ensure_connected()

    # Solve IK for both positions up front
    print("\n── Solving IK for Pos 1 ──")
    joints_pos1 = solve_ik(POS1, "Pos1")

    print("\n── Solving IK for Pos 2 ──")
    joints_pos2 = solve_ik(POS2, "Pos2")

    input("\nPress Enter to start the sequence (Home → Pos1 → Home → Pos2 → Home)...")

    # Step 1: Home
    print("\n══ Step 1/5: HOME ══")
    move_to(HOME, "Home")
    hold(HOLD_SEC, "Home")

    # Step 2: Pos 1
    print("\n══ Step 2/5: POSITION 1 ══")
    move_to(joints_pos1, "Pos1")
    hold(HOLD_SEC, "Pos1")

    # Step 3: Home again
    print("\n══ Step 3/5: HOME ══")
    move_to(HOME, "Home")
    hold(HOLD_SEC, "Home")

    # Step 4: Pos 2
    print("\n══ Step 4/5: POSITION 2 ══")
    move_to(joints_pos2, "Pos2")
    hold(HOLD_SEC, "Pos2")

    # Step 5: Home (final)
    print("\n══ Step 5/5: HOME ══")
    move_to(HOME, "Home")
    hold(HOLD_SEC, "Home")

    print("\n✅ Sequence complete!")


if __name__ == "__main__":
    main()
