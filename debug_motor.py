"""
Diagnostic: test SO100MotorController (same path as move_robot.py)
to verify normalized read/write works end-to-end.
"""
import time
from src.motor_control import SO100MotorController

PORT = "COM7"

ctrl = SO100MotorController()
result = ctrl.connect(PORT)
print(f"Connect: {result}")

# 1) Read current positions (normalized degrees)
pos = ctrl.read_positions()
print(f"\nPositions after connect: {pos}")
wr_before = pos["positions_deg"]["wrist_roll"]

# 2) Enable torque
print(f"\nEnable torque: {ctrl.enable_torque()}")

# 3) Move wrist_roll by +10 degrees
target = wr_before + 10
print(f"\nWriting wrist_roll: {wr_before:.1f}° → {target:.1f}°")
w = ctrl.write_positions({"wrist_roll": target})
print(f"  Write result: {w}")

# 4) Wait and read
time.sleep(2.0)
pos2 = ctrl.read_positions()
wr_after = pos2["positions_deg"]["wrist_roll"]
print(f"\n  After 2s: wrist_roll = {wr_after:.1f}° (expected ~{target:.1f}°)")
print(f"  Moved: {abs(wr_after - wr_before) > 1.0}")

# 5) Restore
print(f"\nRestoring to {wr_before:.1f}°...")
ctrl.write_positions({"wrist_roll": wr_before})
time.sleep(1.5)

# 6) Disable torque and disconnect
ctrl.disable_torque()
ctrl.disconnect()
print("Done.")
