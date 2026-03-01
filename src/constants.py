"""
Workspace and robot accessory constants.

All physical measurements, sensor offsets, and configuration values that
describe the hardware setup live here.  Edit this file whenever the
calibration changes (new tool, re-mounted camera, different checkerboard).
"""

import numpy as np
# ── Tool (probe / tip) ────────────────────────────────────────────────────────

# Offset of the tool tip from the Fixed_Jaw end-effector frame origin,
# expressed in the EE (Fixed_Jaw) frame, in metres.
# For the SO-101 the probe extends along EE +X.
TOOL_OFFSET_EE_M: list[float] = [0.059, 0.0, 0.0]
# TOOL_OFFSET_EE_M: list[float] = [0.0, 0.0, 0.0]


# ── Camera mount ──────────────────────────────────────────────────────────────

# Camera tilt around EE local Y axis (degrees).
# Negative = tilts toward EE +X (forward); physical mount is –35°.
# A positive value would point the camera backwards — wrong for this setup.
CAM_TILT_EE_DEG: float = -35.0

# Tooltip position measured in the camera frame (metres).
# Used to derive the fixed camera-in-EE transform T_CAM_EE at startup.
# Re-run robot_cam_calibration.py to update this after re-mounting the camera.
TOOL_INTERSECT_DIST = 0.0115
INTERSECT_TO_TIP = 0.0020
INTERSECT_ANGLE = np.deg2rad(35)
P_TIP_CAM_M: list[float] = [0.001, -0.001, TOOL_INTERSECT_DIST + np.cos(INTERSECT_ANGLE) * INTERSECT_TO_TIP]

# ── Workspace checkerboard ────────────────────────────────────────────────────

# Physical side length of one checkerboard square (millimetres).
# Used as the fallback when "square_size_mm" is absent from calibration.json.
BOARD_SQUARE_SIZE_MM: float = 9.5

# Inner-corner grid of the *full* calibration board (rows × cols).
# A 7×10 physical board has 6×9 inner corners.
# These are the fallback defaults; the live values come from
# "board_rows" / "board_cols" fields in data/arm_cam_calib/calibration.json.
BOARD_ROWS: int = 28
BOARD_COLS: int = 20

# Height of the target / workspace plane above the checkerboard surface (metres).
# "3 mm" means the PCB or component being probed sits 3 mm above the board.
WORKSPACE_PLANE_OFFSET_M: float = 0.003

# ── Camera capture ────────────────────────────────────────────────────────────

CAMERA_WIDTH: int = 1280
CAMERA_HEIGHT: int = 720
CAMERA_JPEG_QUALITY: int = 85
