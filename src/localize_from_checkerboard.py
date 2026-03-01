"""
Camera pose from 4 checkerboard square corners + 3D keypoint localisation.

Instead of detecting the full checkerboard automatically, the user identifies
4 pixel coordinates that are the 4 corners of ONE square on the board
(in order: top-left, top-right, bottom-right, bottom-left going around the square).
The known square side length gives the scale, and solvePnP (IPPE) recovers the
full camera-to-board transform.

Pipeline
--------
1. Load image + camera calibration
2. Accept 4 corner pixels (interactive click or --corners arg)
3. solvePnP (IPPE) → camera-to-board pose (R, t)
4. Cast a ray through the keypoint pixel
5. Intersect ray with the target plane (board Z = plane_offset_m)
6. Report 3D position in board frame and camera frame

Coordinate frames
-----------------
* Camera frame : OpenCV convention (Z forward, X right, Y down)
* Board frame  : origin at the TOP-LEFT corner of the selected square,
                 X pointing RIGHT (to top-right corner),
                 Y pointing DOWN  (to bottom-left corner),
                 Z pointing OUT of the board (towards the camera when viewed front-on)
  → "3 mm above the board" = Z = +0.003 m in board frame

Usage (interactive — click 4 corners in order TL→TR→BR→BL)
------------------------------------------------------------
    uv run python src/localize_from_checkerboard.py \\
        --image data/arduino/planning_image.jpeg \\
        --pixel 673 160 \\
        --plane-offset 0.003 \\
        --interactive

Usage (supply 4 corners directly)
----------------------------------
    uv run python src/localize_from_checkerboard.py \\
        --image data/arduino/planning_image.jpeg \\
        --pixel 673 160 \\
        --corners 120 80  170 80  170 130  120 130 \\
        --plane-offset 0.003 \\
        --save output_annotated.jpg

Python API
----------
    from src.localize_from_checkerboard import localize_keypoint
    result = localize_keypoint(
        image_path="...",
        keypoint_px=(673, 160),
        square_corners_px=[(120,80),(170,80),(170,130),(120,130)],
        plane_offset_m=0.003,
    )
    print(result["pos_board_m"])   # metres in board frame
    print(result["pos_cam_m"])     # metres in camera frame
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import NamedTuple

import cv2
import numpy as np

try:
    from src.constants import (
        BOARD_ROWS,
        BOARD_COLS,
        BOARD_SQUARE_SIZE_MM,
        WORKSPACE_PLANE_OFFSET_M,
    )
except ImportError:
    from constants import (
        BOARD_ROWS,
        BOARD_COLS,
        BOARD_SQUARE_SIZE_MM,
        WORKSPACE_PLANE_OFFSET_M,
    )

# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------

_CALIB_PATH = Path(__file__).parents[1] / "data/arm_cam_calib/calibration.json"


def load_calibration(
    path: str | Path = _CALIB_PATH,
) -> tuple[np.ndarray, np.ndarray, float, tuple[int, int]]:
    """Return (K 3×3, dist 1×5, square_size_m, board_shape (rows, cols))."""
    with open(path) as f:
        cal = json.load(f)
    K = np.array(cal["camera_matrix"], dtype=np.float64)
    dist = np.array(cal["dist_coeff"], dtype=np.float64)
    sq_m = cal.get("square_size_mm", BOARD_SQUARE_SIZE_MM) / 1000.0
    rows = int(cal.get("board_rows", BOARD_ROWS))
    cols = int(cal.get("board_cols", BOARD_COLS))
    return K, dist, sq_m, (rows, cols)


# ---------------------------------------------------------------------------
# Interactive corner picker
# ---------------------------------------------------------------------------


def pick_4_corners(image_bgr: np.ndarray) -> list[tuple[float, float]]:
    """
    Show the image and let the user click 4 corners of one checkerboard square.
    Returns [(u0,v0), (u1,v1), (u2,v2), (u3,v3)] in click order.
    Click order: top-left → top-right → bottom-right → bottom-left.
    """
    clicks: list[tuple[float, float]] = []
    labels = [
        "TL (top-left)",
        "TR (top-right)",
        "BR (bottom-right)",
        "BL (bottom-left)",
    ]

    display = image_bgr.copy()
    cv2.namedWindow("Pick 4 square corners", cv2.WINDOW_NORMAL)

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN and len(clicks) < 4:
            clicks.append((float(x), float(y)))
            cv2.circle(display, (x, y), 6, (0, 255, 0), -1)
            idx = len(clicks) - 1
            cv2.putText(
                display,
                str(idx + 1),
                (x + 8, y - 4),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 0),
                2,
            )
            if len(clicks) == 4:
                pts = np.array(clicks, dtype=np.int32)
                cv2.polylines(display, [pts], True, (0, 255, 0), 2)
            cv2.imshow("Pick 4 square corners", display)

    cv2.setMouseCallback("Pick 4 square corners", on_mouse)
    print("\n  Click 4 corners of ONE checkerboard square in order:")
    for i, lbl in enumerate(labels):
        print(f"    {i + 1}. {lbl}")
    print("  Press ENTER or SPACE when done, ESC to cancel.\n")

    while True:
        cv2.imshow("Pick 4 square corners", display)
        key = cv2.waitKey(20) & 0xFF
        if key in (13, 32) and len(clicks) == 4:
            break
        if key == 27:
            cv2.destroyAllWindows()
            raise RuntimeError("Corner selection cancelled by user.")

    cv2.destroyAllWindows()
    return clicks


# ---------------------------------------------------------------------------
# Automatic corner detection
# ---------------------------------------------------------------------------


def _try_detect(gray: np.ndarray, r: int, c: int):
    """Try to detect an (r, c) inner-corner checkerboard. Returns (found, corners)."""
    found, corners = cv2.findChessboardCornersSB(gray, (c, r))
    if not found:
        found, corners = cv2.findChessboardCorners(
            gray,
            (c, r),
            flags=cv2.CALIB_CB_ADAPTIVE_THRESH + cv2.CALIB_CB_NORMALIZE_IMAGE,
        )
        if found and corners is not None:
            crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
            corners = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), crit)
    return found, corners


class DetectedBoard(NamedTuple):
    """Result of checkerboard auto-detection."""

    square_corners_px: list[tuple[float, float]]  # 4 corners of one cell [TL,TR,BR,BL]
    all_corners_px: np.ndarray  # (rows, cols, 2) full grid
    detected_rows: int
    detected_cols: int


def detect_board_corners(
    image_bgr: np.ndarray,
    board_shape: tuple[int, int] = (BOARD_ROWS, BOARD_COLS),
    square_idx: tuple[int, int] | None = None,
    visualize: bool = False,
) -> DetectedBoard:
    """
    Auto-detect a (possibly partially occluded) checkerboard and return the
    4 pixel corners of one square plus the full grid of all detected corners.

    Tries the full ``board_shape`` first.  If the board is partly occluded,
    automatically shrinks the pattern size one row/column at a time until a
    visible sub-pattern is found — down to the minimum of 2×2 inner corners
    (= one complete square).

    Uses ``cv2.findChessboardCornersSB`` (robust) with a fallback to the
    classic ``cv2.findChessboardCorners`` + sub-pixel refinement.

    Parameters
    ----------
    image_bgr   : BGR image (from cv2.imread)
    board_shape : (rows, cols) of INNER corners of the FULL board,
                  e.g. (6, 9) for a 7×10 board  [default: (6, 9)]
    square_idx  : (row, col) 0-based cell index within the **detected**
                  inner-corner grid.  None → centre cell of whatever
                  sub-pattern was detected.
    visualize   : if True, open a window showing all detected corners (colour
                  gradient) with the selected square highlighted in cyan.
                  Press any key to close.

    Returns
    -------
    DetectedBoard with:
      - square_corners_px: 4 (u, v) float tuples [TL, TR, BR, BL]
      - all_corners_px: (rows, cols, 2) array of all detected inner corners
      - detected_rows, detected_cols: dimensions of the detected pattern

    Raises
    ------
    RuntimeError  – no sub-pattern detected down to 2×2
    ValueError    – square_idx out of range
    """
    full_rows, full_cols = board_shape
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)

    # Build candidate sizes ordered largest-first (most corners = best accuracy).
    # We reduce rows and cols independently so a visible strip along either
    # axis is found quickly.
    candidates: list[tuple[int, int]] = []
    for r in range(full_rows, 4, -1):
        for c in range(full_cols, 4, -1):
            candidates.append((r, c))
    candidates.sort(key=lambda x: x[0] * x[1], reverse=True)

    found = False
    corners = None
    det_rows = det_cols = 0
    for r, c in candidates:
        ok, pts = _try_detect(gray, r, c)
        if ok and pts is not None:
            found, corners, det_rows, det_cols = True, pts, r, c
            if (r, c) != (full_rows, full_cols):
                print(
                    f"[detect_board_corners] Partial board detected: "
                    f"{r}×{c} inner corners (full board: {full_rows}×{full_cols})"
                )
            break

    if not found or corners is None:
        raise RuntimeError(
            "No checkerboard pattern found (tried all sizes down to 2×2). "
            "Ensure at least one complete square of the board is clearly visible."
        )

    # Reshape to (det_rows, det_cols, 2) grid of (x, y) pixel positions
    corners_2d = corners.reshape(det_rows, det_cols, 2)

    # Normalise orientation so row-0 is the top row and col-0 is the left column
    if corners_2d[0, 0, 1] > corners_2d[-1, 0, 1]:  # row 0 is below row -1 → flip
        corners_2d = corners_2d[::-1, :, :]
    if corners_2d[0, 0, 0] > corners_2d[0, -1, 0]:  # col 0 is right of col -1 → flip
        corners_2d = corners_2d[:, ::-1, :]

    rows, cols = det_rows, det_cols

    # Pick the cell
    if square_idx is None:
        sr, sc = (rows - 1) // 2, (cols - 1) // 2
    else:
        sr, sc = int(square_idx[0]), int(square_idx[1])
        if not (0 <= sr <= rows - 2 and 0 <= sc <= cols - 2):
            raise ValueError(
                f"square_idx ({sr}, {sc}) out of range for detected board "
                f"({rows}×{cols}). Valid range: row [0, {rows - 2}], "
                f"col [0, {cols - 2}]."
            )

    # Extract 4 corners of cell (sr, sc) in TL→TR→BR→BL order
    tl = (float(corners_2d[sr, sc, 0]), float(corners_2d[sr, sc, 1]))
    tr = (float(corners_2d[sr, sc + 1, 0]), float(corners_2d[sr, sc + 1, 1]))
    br = (float(corners_2d[sr + 1, sc + 1, 0]), float(corners_2d[sr + 1, sc + 1, 1]))
    bl = (float(corners_2d[sr + 1, sc, 0]), float(corners_2d[sr + 1, sc, 1]))

    if visualize:
        vis = image_bgr.copy()
        # Draw all detected inner corners with OpenCV's colour-gradient overlay
        corners_raw = corners_2d.reshape(-1, 1, 2).astype(np.float32)
        cv2.drawChessboardCorners(vis, (cols, rows), corners_raw, True)
        # Highlight the selected square in cyan
        quad = np.array([tl, tr, br, bl], dtype=np.int32)
        cv2.polylines(vis, [quad], isClosed=True, color=(255, 255, 0), thickness=2)
        for pt, label in zip([tl, tr, br, bl], ["TL", "TR", "BR", "BL"]):
            cv2.circle(vis, (int(pt[0]), int(pt[1])), 7, (255, 255, 0), -1)
            cv2.putText(
                vis,
                label,
                (int(pt[0]) + 8, int(pt[1]) - 4),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 0),
                2,
            )
        cv2.putText(
            vis,
            f"Detected: {rows}x{cols} inner corners  |  cell ({sr},{sc})",
            (10, 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (0, 255, 0),
            2,
        )
        cv2.namedWindow("Checkerboard detection", cv2.WINDOW_NORMAL)
        cv2.imshow("Checkerboard detection", vis)
        cv2.waitKey(0)
        cv2.destroyAllWindows()

    return DetectedBoard(
        square_corners_px=[tl, tr, br, bl],
        all_corners_px=corners_2d.copy(),
        detected_rows=rows,
        detected_cols=cols,
    )


# ---------------------------------------------------------------------------
# Pose estimation from 4 square corners
# ---------------------------------------------------------------------------


class BoardPose(NamedTuple):
    R_board_in_cam: np.ndarray  # 3×3 rotation: board frame → camera frame
    t_board_in_cam: np.ndarray  # 3-vector: board origin in camera frame (m)
    reprojection_err_px: float
    square_corners_px: list  # the 4 image points used


def solve_pose_from_square(
    corners_px: list[tuple[float, float]],
    square_size_m: float,
    K: np.ndarray,
    dist: np.ndarray,
) -> BoardPose:
    """
    Estimate camera-to-board pose from 4 corners of one checkerboard square.

    corners_px order: [TL, TR, BR, BL] (going clockwise around one square).

    The board frame origin is at TL (top-left corner), with:
      X → TL to TR (right)
      Y → TL to BL (down)
      Z → out of board (right-hand rule: X×Y)

    Uses cv2.SOLVEPNP_IPPE which is designed for 4 coplanar points and returns
    two candidate poses; we select the one where the board is in front of the
    camera (positive depth).
    """
    s = square_size_m

    # 3D object points in board frame (Z=0 plane)
    obj_pts = np.array(
        [
            [0.0, 0.0, 0.0],  # TL
            [s, 0.0, 0.0],  # TR
            [s, s, 0.0],  # BR
            [0.0, s, 0.0],  # BL
        ],
        dtype=np.float64,
    )

    img_pts = np.array(corners_px, dtype=np.float64).reshape(-1, 1, 2)

    # IPPE returns 2 solutions for planar point sets
    num_sols, rvecs, tvecs, errors = cv2.solvePnPGeneric(
        obj_pts,
        img_pts,
        K,
        dist,
        flags=cv2.SOLVEPNP_IPPE,
    )

    # Pick solution with positive Z (board in front of camera)
    best_idx = 0
    for i in range(num_sols):
        R_i, _ = cv2.Rodrigues(rvecs[i])
        t_i = tvecs[i].ravel()
        # Board origin Z in camera frame
        if t_i[2] > 0:
            best_idx = i
            break

    R, _ = cv2.Rodrigues(rvecs[best_idx])
    t = tvecs[best_idx].ravel()

    # Compute reprojection error
    proj, _ = cv2.projectPoints(obj_pts, rvecs[best_idx], tvecs[best_idx], K, dist)
    proj = proj.reshape(-1, 2)
    gt = np.array(corners_px)
    err = float(np.mean(np.linalg.norm(proj - gt, axis=1)))

    return BoardPose(
        R_board_in_cam=R,
        t_board_in_cam=t,
        reprojection_err_px=err,
        square_corners_px=corners_px,
    )


def solve_pose_from_grid(
    all_corners_px: np.ndarray,
    detected_rows: int,
    detected_cols: int,
    square_size_m: float,
    K: np.ndarray,
    dist: np.ndarray,
) -> BoardPose:
    """
    Estimate camera-to-board pose using **all** detected inner corners of a
    checkerboard grid — far more robust than the 4-point single-square solver.

    Parameters
    ----------
    all_corners_px : (rows, cols, 2) array of sub-pixel corner coordinates.
                     Row 0 is top, col 0 is left, matching the orientation
                     normalisation done by ``detect_board_corners()``.
    detected_rows, detected_cols : grid dimensions.
    square_size_m  : physical side length of one checkerboard cell (metres).
    K, dist        : camera intrinsics and distortion coefficients.

    The board frame is defined the same as ``solve_pose_from_square``:
      origin = top-left inner corner (row 0, col 0)
      X → right (increasing col), Y → down (increasing row), Z → out of board.
    """
    rows, cols = detected_rows, detected_cols
    n_pts = rows * cols

    # Build 3D object points: each inner corner at grid position (r, c)
    # maps to 3D point (c * square_size, r * square_size, 0).
    obj_pts = np.zeros((n_pts, 3), dtype=np.float64)
    for r in range(rows):
        for c in range(cols):
            idx = r * cols + c
            obj_pts[idx, 0] = c * square_size_m  # X = col direction
            obj_pts[idx, 1] = r * square_size_m  # Y = row direction
            # Z = 0 (planar)

    # Flatten the image points to (N, 1, 2)
    img_pts = all_corners_px.reshape(-1, 1, 2).astype(np.float64)

    # Use iterative PnP for > 4 points (IPPE is only for 4 coplanar points)
    success, rvec, tvec = cv2.solvePnP(
        obj_pts,
        img_pts,
        K,
        dist,
        flags=cv2.SOLVEPNP_ITERATIVE,
    )
    if not success:
        raise RuntimeError(
            f"solvePnP failed on {n_pts} points ({rows}x{cols} grid). "
            "Check that the detected corners are valid."
        )

    # Refine with Levenberg-Marquardt
    rvec, tvec = cv2.solvePnPRefineLM(obj_pts, img_pts, K, dist, rvec, tvec)

    R, _ = cv2.Rodrigues(rvec)
    t = tvec.ravel()

    # Ensure board is in front of camera
    if t[2] < 0:
        # Flip — shouldn't normally happen with correct corner ordering
        t = -t
        R = -R

    # Compute reprojection error over ALL points
    proj, _ = cv2.projectPoints(obj_pts, rvec, tvec, K, dist)
    proj = proj.reshape(-1, 2)
    gt = img_pts.reshape(-1, 2)
    per_point_err = np.linalg.norm(proj - gt, axis=1)
    mean_err = float(np.mean(per_point_err))

    # Log stats for diagnostics
    print(
        f"[solve_pose_from_grid] {n_pts} corners ({rows}x{cols}), "
        f"reproj err: mean={mean_err:.3f} px, max={float(np.max(per_point_err)):.3f} px"
    )

    # For backward compatibility, store the 4 centre-cell corners
    sr, sc = (rows - 1) // 2, (cols - 1) // 2
    tl = (float(all_corners_px[sr, sc, 0]), float(all_corners_px[sr, sc, 1]))
    tr = (float(all_corners_px[sr, sc + 1, 0]), float(all_corners_px[sr, sc + 1, 1]))
    br = (
        float(all_corners_px[sr + 1, sc + 1, 0]),
        float(all_corners_px[sr + 1, sc + 1, 1]),
    )
    bl = (float(all_corners_px[sr + 1, sc, 0]), float(all_corners_px[sr + 1, sc, 1]))

    return BoardPose(
        R_board_in_cam=R,
        t_board_in_cam=t,
        reprojection_err_px=mean_err,
        square_corners_px=[tl, tr, br, bl],
    )


# ---------------------------------------------------------------------------
# Ray-plane intersection
# ---------------------------------------------------------------------------


def pixel_to_3d(
    pixel: tuple[float, float],
    K: np.ndarray,
    dist: np.ndarray,
    pose: BoardPose,
    plane_offset_m: float,
) -> dict:
    """
    Intersect the camera ray through `pixel` with a plane parallel to the board
    at height `plane_offset_m` above it (board frame Z = plane_offset_m).

    Returns dict:
      pos_cam_m   : np.ndarray (3,) in camera frame (metres)
      pos_board_m : np.ndarray (3,) in board frame (metres)
      depth_m     : float, camera Z depth
    """
    u, v = float(pixel[0]), float(pixel[1])

    # Undistort → normalised image coordinates (removes lens distortion)
    pt_norm = cv2.undistortPoints(
        np.array([[[u, v]]], dtype=np.float64), K, dist
    )  # result has no P matrix → output is in normalised coords
    xn, yn = float(pt_norm[0, 0, 0]), float(pt_norm[0, 0, 1])

    # Ray direction in camera frame (not unit — we parameterise by depth)
    ray_cam = np.array([xn, yn, 1.0])

    R = pose.R_board_in_cam
    t = pose.t_board_in_cam

    # Board +Z axis expressed in camera frame (= 3rd column of R)
    z_board_cam = R[:, 2]

    # A point on the target plane: board origin shifted by plane_offset_m along board +Z
    p_plane_cam = t + R @ np.array([0.0, 0.0, plane_offset_m])

    # Solve: t_ray * (ray_cam · z_board_cam) = p_plane_cam · z_board_cam
    denom = ray_cam @ z_board_cam
    if abs(denom) < 1e-8:
        raise ValueError(
            "Ray is nearly parallel to the board plane — camera may be viewing "
            "the board edge-on. Tilt camera or reduce plane_offset."
        )

    t_ray = (p_plane_cam @ z_board_cam) / denom
    if t_ray < 0:
        raise ValueError(
            f"Intersection behind camera (t={t_ray:.3f}). "
            "Flip plane_offset sign or check corner order (should be CW: TL→TR→BR→BL)."
        )

    pos_cam = t_ray * ray_cam
    pos_board = R.T @ (pos_cam - t)

    return {
        "pos_cam_m": pos_cam,
        "pos_board_m": pos_board,
        "depth_m": float(t_ray),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def localize_keypoint(
    image_path: str | Path,
    keypoint_px: tuple[float, float],
    square_corners_px: list[tuple[float, float]] | None = None,
    plane_offset_m: float = WORKSPACE_PLANE_OFFSET_M,
    calib_path: str | Path = _CALIB_PATH,
    interactive: bool = False,
    auto_detect: bool = False,
    board_shape: tuple[int, int] | None = None,
    square_idx: tuple[int, int] | None = None,
    visualize: bool = False,
    save_annotated: str | Path | None = None,
) -> dict:
    """
    Full localisation pipeline.

    Parameters
    ----------
    image_path         : path to the image
    keypoint_px        : (u, v) pixel of the point of interest
    square_corners_px  : 4 corners of one checkerboard square [TL, TR, BR, BL].
                         Not needed when ``auto_detect=True`` or ``interactive=True``.
    plane_offset_m     : height of the PCB/target plane above the board (metres)
    interactive        : open a window to click the 4 corners manually
    auto_detect        : use OpenCV to detect the full checkerboard automatically
    board_shape        : (rows, cols) of inner corners for auto_detect
                         [default: taken from calibration.json, or (6, 9)]
    square_idx         : (row, col) cell to use when auto_detect=True
                         [default: centre cell]
    visualize          : show a window with all detected corners + selected square
    save_annotated     : if given, write annotated image here

    Returns dict with:
      pos_cam_m        : [x,y,z] metres in camera frame
      pos_board_m      : [x,y,z] metres in board frame
      depth_m          : depth (camera Z)
      pose             : BoardPose named tuple
    """
    K, dist, sq_m, calib_board_shape = load_calibration(calib_path)
    image_bgr = cv2.imread(str(image_path))
    if image_bgr is None:
        raise FileNotFoundError(f"Cannot load image: {image_path}")

    detected_board: DetectedBoard | None = None

    if auto_detect:
        shape = board_shape if board_shape is not None else calib_board_shape
        detected_board = detect_board_corners(image_bgr, shape, square_idx, visualize)
        square_corners_px = detected_board.square_corners_px
    elif interactive:
        square_corners_px = pick_4_corners(image_bgr)
    elif square_corners_px is None:
        raise ValueError(
            "Provide square_corners_px, set interactive=True, or set auto_detect=True"
        )

    # Use ALL detected corners when the grid has more than 4 points (>= 3x3).
    # This dramatically improves pose accuracy by over-constraining solvePnP.
    # Fall back to the 4-point IPPE solver for manual/interactive modes or
    # when only a tiny sub-grid (e.g. 2x2) was found.
    if (
        detected_board is not None
        and detected_board.detected_rows >= 3
        and detected_board.detected_cols >= 3
    ):
        n_pts = detected_board.detected_rows * detected_board.detected_cols
        print(
            f"[localize_keypoint] Using {n_pts} grid corners "
            f"({detected_board.detected_rows}x{detected_board.detected_cols}) "
            f"for pose estimation (vs 4-point fallback)"
        )
        pose = solve_pose_from_grid(
            detected_board.all_corners_px,
            detected_board.detected_rows,
            detected_board.detected_cols,
            sq_m,
            K,
            dist,
        )
    else:
        pose = solve_pose_from_square(square_corners_px, sq_m, K, dist)

    result = pixel_to_3d(keypoint_px, K, dist, pose, plane_offset_m)
    result["pose"] = pose

    if save_annotated:
        img = image_bgr.copy()
        # If we have a full detected grid, draw ALL corners for visual verification
        if detected_board is not None:
            all_pts = detected_board.all_corners_px.reshape(-1, 1, 2).astype(np.float32)
            cv2.drawChessboardCorners(
                img,
                (detected_board.detected_cols, detected_board.detected_rows),
                all_pts,
                True,
            )
        # Draw the selected square corners
        pts = np.array(square_corners_px, dtype=np.int32)
        cv2.polylines(img, [pts], True, (0, 200, 0), 2)
        labels = ["TL", "TR", "BR", "BL"]
        for i, (px, py) in enumerate(square_corners_px):
            cv2.circle(img, (int(px), int(py)), 5, (0, 255, 0), -1)
            cv2.putText(
                img,
                labels[i],
                (int(px) + 6, int(py) - 4),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 255, 0),
                1,
            )
        # Draw keypoint
        u, v = int(round(keypoint_px[0])), int(round(keypoint_px[1]))
        cv2.circle(img, (u, v), 10, (0, 255, 255), -1)
        cv2.circle(img, (u, v), 12, (0, 0, 0), 2)
        pos_b = result["pos_board_m"]
        pos_c = result["pos_cam_m"]
        cv2.putText(
            img,
            f"board: ({pos_b[0] * 1000:.1f}, {pos_b[1] * 1000:.1f}, {pos_b[2] * 1000:.1f}) mm",
            (u + 14, v - 8),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 255, 255),
            2,
        )
        cv2.putText(
            img,
            f"cam:   ({pos_c[0] * 1000:.1f}, {pos_c[1] * 1000:.1f}, {pos_c[2] * 1000:.1f}) mm",
            (u + 14, v + 16),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 200, 255),
            2,
        )
        cv2.imwrite(str(save_annotated), img)

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Checkerboard 4-point PnP → 3D keypoint localisation"
    )
    ap.add_argument("--image", required=True, help="Image path")
    ap.add_argument(
        "--pixel",
        nargs=2,
        type=float,
        default=[673, 160],
        metavar=("U", "V"),
        help="Pixel (u v) of the keypoint of interest  [default: 673 160]",
    )
    ap.add_argument(
        "--corners",
        nargs=8,
        type=float,
        metavar=("TL_U", "TL_V", "TR_U", "TR_V", "BR_U", "BR_V", "BL_U", "BL_V"),
        help="8 floats: pixel coords of TL TR BR BL corners of one square "
        "(clockwise).  Omit to use --auto or --interactive.",
    )
    ap.add_argument(
        "--auto",
        action="store_true",
        help="Auto-detect the checkerboard corners with OpenCV (no manual input)",
    )
    ap.add_argument(
        "--board-shape",
        nargs=2,
        type=int,
        default=None,
        metavar=("ROWS", "COLS"),
        help="Inner-corner grid size for --auto  [default: from calibration.json]",
    )
    ap.add_argument(
        "--square-idx",
        nargs=2,
        type=int,
        default=None,
        metavar=("ROW", "COL"),
        help="Which cell to use when --auto is set  [default: centre cell]",
    )
    ap.add_argument(
        "--vis",
        action="store_true",
        help="Show detected corners in a window before computing pose "
        "(only used with --auto)",
    )
    ap.add_argument(
        "--interactive",
        action="store_true",
        help="Open window to click the 4 corners manually",
    )
    ap.add_argument(
        "--plane-offset",
        type=float,
        default=WORKSPACE_PLANE_OFFSET_M,
        metavar="M",
        help=f"Target plane height above checkerboard (metres)  [default: {WORKSPACE_PLANE_OFFSET_M}]",
    )
    ap.add_argument(
        "--calib", default=str(_CALIB_PATH), help="Path to calibration.json"
    )
    ap.add_argument("--save", default=None, help="Save annotated image to this path")
    args = ap.parse_args()

    if args.corners:
        c = args.corners
        corners = [(c[0], c[1]), (c[2], c[3]), (c[4], c[5]), (c[6], c[7])]
    else:
        corners = None

    if corners is None and not args.interactive and not args.auto:
        ap.error(
            "Provide --corners TL_U TL_V TR_U TR_V BR_U BR_V BL_U BL_V  "
            "or  --auto  or  --interactive"
        )

    try:
        result = localize_keypoint(
            image_path=args.image,
            keypoint_px=tuple(args.pixel),
            square_corners_px=corners,
            plane_offset_m=args.plane_offset,
            calib_path=args.calib,
            interactive=args.interactive,
            auto_detect=args.auto,
            board_shape=tuple(args.board_shape) if args.board_shape else None,
            square_idx=tuple(args.square_idx) if args.square_idx else None,
            visualize=args.vis,
            save_annotated=args.save,
        )
    except (RuntimeError, ValueError) as e:
        print(f"\n[ERROR] {e}")
        raise SystemExit(1) from e

    pose = result["pose"]
    p_b = result["pos_board_m"]
    p_c = result["pos_cam_m"]

    print("\n" + "=" * 58)
    print("  Checkerboard 4-point PnP  →  3D Keypoint")
    print("=" * 58)
    print(f"  Reprojection error  : {pose.reprojection_err_px:.2f} px")
    print(f"  Pixel (u, v)        : ({args.pixel[0]:.0f}, {args.pixel[1]:.0f})")
    print(f"  Plane above board   : {args.plane_offset * 1000:.1f} mm")
    print()
    print("  Position in BOARD frame (origin = TL corner of selected square):")
    print(f"    X = {p_b[0] * 1000:+8.2f} mm   (→ along board)")
    print(f"    Y = {p_b[1] * 1000:+8.2f} mm   (↓ along board)")
    print(
        f"    Z = {p_b[2] * 1000:+8.2f} mm   (should ≈ {args.plane_offset * 1000:.1f} mm, above board)"
    )
    print()
    print("  Position in CAMERA frame:")
    print(f"    X = {p_c[0] * 1000:+8.2f} mm")
    print(f"    Y = {p_c[1] * 1000:+8.2f} mm")
    print(f"    Z = {p_c[2] * 1000:+8.2f} mm   (depth)")
    print()
    print("  ─── To get ROBOT-BASE frame ───────────────────────────")
    print("  Apply your camera-to-robot extrinsic T_robot_cam:")
    print("    p_robot = T_robot_cam[:3,:3] @ p_cam + T_robot_cam[:3,3]")
    print("=" * 58)

    if args.save:
        print(f"\n  Annotated image saved: {args.save}")
