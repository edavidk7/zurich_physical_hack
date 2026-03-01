"""
Motor Control for SO-ARM100

Wraps lerobot's FeetechMotorsBus to provide direct servo control.
Supports connecting, reading positions, and writing goal positions.
"""

import logging
import threading
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Motor names and IDs matching the SO-ARM100 hardware
MOTOR_NAMES = [
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_roll",
    "gripper",
]
MOTOR_IDS = [1, 2, 3, 4, 5, 6]


@dataclass
class MotorStatus:
    connected: bool
    port: str | None
    positions_deg: dict[str, float] | None
    error: str | None = None


class SO100MotorController:
    """
    Controls the SO-ARM100 robot arm via Feetech STS3215 servos.

    Uses lerobot's FeetechMotorsBus for serial communication.
    The controller manages connection lifecycle and provides
    thread-safe read/write operations.
    """

    def __init__(self):
        self._bus = None
        self._port: str | None = None
        self._lock = threading.Lock()
        self._connected = False
        self._speed: int = 200  # Goal_Velocity (0-4095), ~0.732 rpm/unit. 200 ≈ slow & safe

    @property
    def is_connected(self) -> bool:
        return self._connected and self._bus is not None

    def connect(self, port: str = "COM7") -> dict:
        """Connect to the robot on the given serial port."""
        with self._lock:
            if self._connected and self._bus is not None:
                return {"status": "already_connected", "port": self._port}

            try:
                from lerobot.motors import Motor, MotorNormMode
                from lerobot.motors.feetech import FeetechMotorsBus
                from lerobot.motors.motors_bus import MotorCalibration

                norm = MotorNormMode.DEGREES
                motors = {
                    name: Motor(mid, "sts3215", norm)
                    for name, mid in zip(MOTOR_NAMES[:5], MOTOR_IDS[:5])
                }
                # Gripper uses 0-100 range normalization
                motors["gripper"] = Motor(6, "sts3215", MotorNormMode.RANGE_0_100)

                # Default calibration: full STS3215 range (0-4095).
                # DEGREES: 0° = raw 2048 (midpoint), ±180° = full range
                # RANGE_0_100: 0% = raw 0, 100% = raw 4095
                calibration = {
                    name: MotorCalibration(
                        id=mid,
                        drive_mode=0,
                        homing_offset=0,
                        range_min=0,
                        range_max=4095,
                    )
                    for name, mid in zip(MOTOR_NAMES, MOTOR_IDS)
                }

                self._bus = FeetechMotorsBus(
                    port=port, motors=motors, calibration=calibration
                )
                # handshake=False skips the motor-ID bus scan, which reliably
                # fails on macOS (USB-CDC driver timing / baud-rate quirks).
                self._bus.connect(handshake=False)

                # Configure for position mode.
                # STS3215 motors default to Status_Return_Level=1 (ACK reads only,
                # not writes), so individual write() calls raise "no status packet"
                # on macOS.  Use sync_write (broadcast, no ACK expected) instead,
                # and make the whole block non-fatal — motors are pre-configured
                # at the factory and work without explicit PID setup.
                from lerobot.motors.feetech import OperatingMode

                motor_names = list(motors.keys())

                # Read present positions BEFORE touching any registers so we
                # can immediately park Goal_Position there — the arm won't
                # move when torque is (re-)enabled.
                present: dict = {}
                try:
                    present = self._bus.sync_read("Present_Position")
                    self._bus.sync_write("Goal_Position", present)
                    logger.info(f"Parked Goal_Position at current pose: {present}")
                except Exception as park_err:
                    logger.warning(f"Could not read/park positions (non-fatal): {park_err}")

                # Apply operating mode and PID config, then keep torque ON.
                try:
                    self._bus.sync_write("Operating_Mode", {m: OperatingMode.POSITION.value for m in motor_names})
                    self._bus.sync_write("P_Coefficient",  {m: 16 for m in motor_names})
                    self._bus.sync_write("I_Coefficient",  {m: 0  for m in motor_names})
                    self._bus.sync_write("D_Coefficient",  {m: 32 for m in motor_names})
                except Exception as cfg_err:
                    logger.warning(f"Motor configuration skipped (non-fatal): {cfg_err}")

                try:
                    self._bus.sync_write("Torque_Enable", {m: 1 for m in motor_names})
                except Exception as te_err:
                    logger.warning(f"Torque enable skipped (non-fatal): {te_err}")

                self._port = port
                self._connected = True
                logger.info(f"Connected to SO-ARM100 on {port}")
                return {
                    "status": "connected",
                    "port": port,
                    "positions_deg": {k: float(v) for k, v in present.items()} if present else None,
                }

            except Exception as e:
                self._bus = None
                self._connected = False
                logger.error(f"Failed to connect on {port}: {e}")
                return {"status": "error", "error": str(e), "port": port}

    def disconnect(self) -> dict:
        """Disconnect from the robot, disabling torque first."""
        with self._lock:
            if not self._connected or self._bus is None:
                return {"status": "not_connected"}
            try:
                # Disable torque via sync_write before closing (no ACK needed)
                self._bus.sync_write("Torque_Enable", {m: 0 for m in MOTOR_NAMES})
            except Exception as e:
                logger.warning(f"Torque disable on disconnect failed (non-fatal): {e}")
            try:
                self._bus.disconnect(disable_torque=False)
            except Exception as e:
                logger.warning(f"Error during disconnect: {e}")
            finally:
                self._bus = None
                self._connected = False
                self._port = None
            return {"status": "disconnected"}

    def read_positions(self) -> dict:
        """Read current joint positions in degrees."""
        with self._lock:
            if not self.is_connected:
                return {"error": "Not connected to robot"}
            try:
                positions = self._bus.sync_read("Present_Position")
                return {
                    "positions_deg": {k: float(v) for k, v in positions.items()},
                    "positions_list": [float(positions.get(n, 0.0)) for n in MOTOR_NAMES[:5]]
                    + [float(positions.get("gripper", 0.0))],
                }
            except Exception as e:
                logger.error(f"Read error: {e}")
                return {"error": str(e)}

    def set_speed(self, speed: int) -> dict:
        """Set the movement speed for all motors.

        Args:
            speed: 1-100 percentage scale.
                   1 = slowest (Goal_Velocity=50),
                   50 = moderate (Goal_Velocity=~2070),
                   100 = maximum (Goal_Velocity=4095).
                   The raw Goal_Velocity register value is stored.
        """
        # Clamp and convert to raw Goal_Velocity (50–4095)
        speed = max(1, min(100, speed))
        raw = int(50 + ((speed - 1) / 99) * (4095 - 50))
        self._speed = raw
        with self._lock:
            if self.is_connected:
                try:
                    for motor in MOTOR_NAMES:
                        self._bus.write("Goal_Velocity", motor, raw)
                except Exception as e:
                    logger.warning(f"Failed to set speed: {e}")
        logger.info(f"Speed set to {speed}/100 (raw Goal_Velocity={raw})")
        return {"status": "ok", "speed": speed, "raw_velocity": raw}

    def write_positions(self, positions_deg: dict[str, float]) -> dict:
        """
        Write goal positions to the robot motors.

        Args:
            positions_deg: Dict mapping motor name -> target angle in degrees.
                           Only the motors specified will be moved.
        """
        with self._lock:
            if not self.is_connected:
                return {"error": "Not connected to robot"}
            try:
                # Validate motor names
                valid = {k: v for k, v in positions_deg.items() if k in MOTOR_NAMES}
                if not valid:
                    return {"error": "No valid motor names provided"}

                # Ensure torque is enabled so the servos actually move.
                # Use sync_write (no ACK) to avoid "no status packet" on macOS.
                try:
                    self._bus.sync_write("Torque_Enable", {m: 1 for m in valid})
                except Exception as e:
                    logger.warning(f"Torque enable skipped (non-fatal): {e}")

                # Set speed via sync_write before writing goal position
                try:
                    self._bus.sync_write("Goal_Velocity", {m: self._speed for m in valid})
                except Exception as e:
                    logger.warning(f"Speed set skipped (non-fatal): {e}")

                self._bus.sync_write("Goal_Position", valid)
                logger.info(f"Wrote positions: {valid}")
                return {"status": "ok", "motors_moved": list(valid.keys())}
            except Exception as e:
                logger.error(f"Write error: {e}")
                return {"error": str(e)}

    def write_joint_array(self, joints_deg: list[float], speed: int | None = None) -> dict:
        """
        Write goal positions from a flat list of 6 joint angles in degrees.

        Order: shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll, gripper

        Args:
            joints_deg: 6 joint angles in degrees.
            speed: Optional speed 1-100. If provided, updates the speed before moving.
        """
        if len(joints_deg) != 6:
            return {"error": f"Expected 6 joint values, got {len(joints_deg)}"}
        if speed is not None:
            self.set_speed(speed)
        pos = {name: val for name, val in zip(MOTOR_NAMES, joints_deg)}
        return self.write_positions(pos)

    def enable_torque(self) -> dict:
        """Enable torque on all motors."""
        with self._lock:
            if not self.is_connected:
                return {"error": "Not connected to robot"}
            try:
                self._bus.sync_write("Torque_Enable", {m: 1 for m in MOTOR_NAMES})
                return {"status": "torque_enabled"}
            except Exception as e:
                return {"error": str(e)}

    def disable_torque(self) -> dict:
        """Disable torque on all motors (arm goes limp)."""
        with self._lock:
            if not self.is_connected:
                return {"error": "Not connected to robot"}
            try:
                self._bus.sync_write("Torque_Enable", {m: 0 for m in MOTOR_NAMES})
                return {"status": "torque_disabled"}
            except Exception as e:
                return {"error": str(e)}

    def get_status(self) -> MotorStatus:
        """Get current controller status."""
        if not self.is_connected:
            return MotorStatus(connected=False, port=None, positions_deg=None)
        result = self.read_positions()
        return MotorStatus(
            connected=True,
            port=self._port,
            positions_deg=result.get("positions_deg"),
            error=result.get("error"),
        )


# ── Singleton ──

_controller: SO100MotorController | None = None
_ctrl_lock = threading.Lock()


def get_motor_controller() -> SO100MotorController:
    """Get the singleton motor controller instance."""
    global _controller
    with _ctrl_lock:
        if _controller is None:
            _controller = SO100MotorController()
        return _controller


def find_robot_port() -> str | None:
    """Auto-detect the robot's serial port (looks for CH343/CH340 USB serial).

    On macOS the WCH CH343/CH340 chip often enumerates via the built-in
    CDC-ACM driver and shows up as /dev/cu.usbmodem* with no "CH340" string
    in the description.  We therefore also match by WCH VID (0x1A86) and by
    the usbmodem device-name pattern.
    """
    import platform
    try:
        import serial.tools.list_ports

        candidates = []
        for p in serial.tools.list_ports.comports():
            desc = (p.description or "").upper()
            hwid = (p.hwid or "").upper()
            device = p.device or ""

            # Skip Bluetooth ports
            if "BLUETOOTH" in desc or "BTHENUM" in hwid:
                continue

            # Explicit CH343/CH340 description match (Linux / Windows)
            if "CH343" in desc or "CH340" in desc or "CH343" in hwid or "CH340" in hwid:
                return device

            # WCH USB VID (0x1A86) — covers macOS usbmodem enumeration
            if "VID:PID=1A86" in hwid or "VID_1A86" in hwid:
                return device

            # macOS fallback: collect /dev/cu.usbmodem* ports (non-Bluetooth)
            if platform.system() == "Darwin" and "usbmodem" in device.lower():
                candidates.append(device)

        # Return the first usbmodem candidate if nothing better was found
        if candidates:
            return candidates[0]

    except Exception:
        pass
    return None
