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
                self._bus.connect(handshake=True)

                # Configure for position mode
                from lerobot.motors.feetech import OperatingMode

                with self._bus.torque_disabled():
                    self._bus.configure_motors()
                    for motor in self._bus.motors:
                        self._bus.write("Operating_Mode", motor, OperatingMode.POSITION.value)
                        self._bus.write("P_Coefficient", motor, 16)
                        self._bus.write("I_Coefficient", motor, 0)
                        self._bus.write("D_Coefficient", motor, 32)

                        if motor == "gripper":
                            self._bus.write("Max_Torque_Limit", motor, 500)
                            self._bus.write("Protection_Current", motor, 250)
                            self._bus.write("Overload_Torque", motor, 25)

                self._port = port
                self._connected = True
                logger.info(f"Connected to SO-ARM100 on {port}")
                return {"status": "connected", "port": port}

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
                self._bus.disconnect(disable_torque=True)
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

                # Ensure torque is enabled so the servos actually move
                self._bus.enable_torque(list(valid.keys()))

                # Set speed before writing goal position
                for motor in valid:
                    self._bus.write("Goal_Velocity", motor, self._speed)

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
                self._bus.enable_torque()
                return {"status": "torque_enabled"}
            except Exception as e:
                return {"error": str(e)}

    def disable_torque(self) -> dict:
        """Disable torque on all motors (arm goes limp)."""
        with self._lock:
            if not self.is_connected:
                return {"error": "Not connected to robot"}
            try:
                self._bus.disable_torque()
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
    """Auto-detect the robot's serial port (looks for CH343/CH340 USB serial)."""
    try:
        import serial.tools.list_ports

        for p in serial.tools.list_ports.comports():
            desc = (p.description or "").upper()
            hwid = (p.hwid or "").upper()
            # Skip Bluetooth ports
            if "BLUETOOTH" in desc or "BTHENUM" in hwid:
                continue
            # Match CH343/CH340 USB-to-serial adapters used by SO-ARM100
            if "CH343" in desc or "CH340" in desc or "CH343" in hwid or "CH340" in hwid:
                return p.device
            # Also match by USB VID:PID for WCH (1A86)
            if "VID:PID=1A86" in hwid or "VID_1A86" in hwid:
                return p.device
    except Exception:
        pass
    return None
