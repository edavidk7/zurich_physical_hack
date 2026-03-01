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

# Camera tilt applied as Rx(tilt_deg) in the camera frame, which rotates the
# optical axis (cam +Z = EE +X at zero tilt) toward cam +Y (= EE +Z).
# Positive = tilts optical axis downward toward the workspace (EE +Z direction).
# Physical mount tilt is +35° (camera looks past the probe tip toward the board).
CAM_TILT_EE_DEG: float = 35.0

# Tooltip position measured in the camera frame (metres).
# Used to derive the fixed camera-in-EE transform T_CAM_EE at startup.
# Re-run robot_cam_calibration.py to update this after re-mounting the camera.
#
# WARNING: T_CAM_EE is very sensitive to these values.  A 1 mm error here
# translates directly into a 1 mm translation error in the camera-EE frame,
# which is amplified by the arm lever when transforming to robot base coords.
# If camera-to-robot results are inaccurate, re-measure these first.
TOOL_INTERSECT_DIST = 0.11
INTERSECT_TO_TIP = 0.03
INTERSECT_ANGLE = np.deg2rad(35)
P_TIP_CAM_M: list[float] = [
    0.01,
    -np.sin(INTERSECT_ANGLE) * INTERSECT_TO_TIP,
    TOOL_INTERSECT_DIST + np.cos(INTERSECT_ANGLE) * INTERSECT_TO_TIP,
]

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

# Safety clearance above the computed target position (metres, in robot Z-up frame).
# The tool tip will stop this far above the target instead of touching it.
# Set to 0.0 to disable.
WORKSPACE_SAFETY_Z_M: float = 0.010  # 10 mm

# ── ArUco markers ─────────────────────────────────────────────────────────

# Physical side length of one ArUco marker (millimetres).
# Must match the printed sheet (generate_aruco_sheet.py default is 18 mm).
ARUCO_MARKER_SIZE_MM: float = 18.0

# Sheet grid layout — must match generate_aruco_sheet.py.
# Markers are numbered row-major: ID = row * ARUCO_SHEET_COLS + col.
ARUCO_SHEET_COLS: int = 8  # markers per row
ARUCO_SHEET_ROWS: int = 12  # rows on the sheet

# Gap between adjacent markers on the sheet (millimetres).
ARUCO_SHEET_GAP_MM: float = 4.5  # 0.45 cm

# Set to False to exclude the gripper motor from all reads/writes (e.g. not connected).
GRIPPER_ENABLED: bool = False

# Number of ArUco markers (closest to image centre) used for pose estimation.
# Using more markers gives more constraints but very-edge markers can hurt accuracy.
ARUCO_POSE_K_MARKERS: int = 3

# ── Camera capture ────────────────────────────────────────────────────────────

CAMERA_WIDTH: int = 1280
CAMERA_HEIGHT: int = 720
CAMERA_JPEG_QUALITY: int = 85
