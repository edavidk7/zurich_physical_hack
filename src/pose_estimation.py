"""
Camera pose estimation and keypoint-to-movement conversion.

Uses a checkerboard in the scene as the world frame (Z=0 plane).
Provides utilities to:
  1. Estimate the camera pose w.r.t. the checkerboard via solvePnP.
  2. Project a 2D image keypoint onto the board plane to get its 3D position.
  3. Compute the camera movement delta needed to center the camera on the keypoint.

Coordinate conventions
----------------------
Board frame:   origin at first inner corner, X along columns, Y along rows, Z pointing toward camera.
Camera frame:  X = rightward in image, Y = downward in image, Z = forward (toward board).
Robot frame:   X = forward, Y = left, Z = up  (see scripts/move_arm_cartesian.py).

Typical camera-to-robot mapping for a straight-down mount:
    delta_robot_x_m  =  dy_cam_mm / 1000   (cam-down  → robot-forward)
    delta_robot_y_m  = -dx_cam_mm / 1000   (cam-right → robot-backward / left is positive)
    delta_robot_z_m  =  0                  (maintain height)
Adjust signs/axes for your actual camera mounting orientation.
"""

import json
from pathlib import Path
from typing import Union

import cv2
import numpy as np


# ── Calibration loading ───────────────────────────────────────────────────────

def load_calibration(calib_path: str) -> dict:
    """
    Load camera intrinsics from a calibration JSON file.

    Args:
        calib_path: Path to calibration.json produced by estimate_instrinsics.py.

    Returns:
        dict with keys:
          'camera_matrix'  : np.ndarray (3, 3)
          'dist_coeff'     : np.ndarray (1, 5)
          'board_size'     : (rows, cols) inner corners
          'square_size_mm' : float
          'image_size_px'  : (width, height)
    """
    with open(calib_path) as f:
        data = json.load(f)
    return {
        "camera_matrix": np.array(data["camera_matrix"], dtype=np.float64),
        "dist_coeff": np.array(data["dist_coeff"], dtype=np.float64),
        "board_size": tuple(data["board_size"]),
        "square_size_mm": float(data["square_size_mm"]),
        "image_size_px": tuple(data["image_size_px"]),
    }


# ── Square detection ──────────────────────────────────────────────────────────

def _order_square_corners(pts: np.ndarray) -> np.ndarray | None:
    """Order 4 points as TL, TR, BR, BL."""
    centroid = pts.mean(axis=0)
    top_mask = pts[:, 1] < centroid[1]
    top = pts[top_mask]
    bot = pts[~top_mask]
    if len(top) != 2 or len(bot) != 2:
        return None
    top = top[np.argsort(top[:, 0])]
    bot = bot[np.argsort(bot[:, 0])]
    return np.array([top[0], top[1], bot[1], bot[0]])


def _detect_squares(
    gray: np.ndarray,
    min_area_frac: float = 0.001,
    max_area_frac: float = 0.5,
) -> list[np.ndarray]:
    """
    Detect all checkerboard squares in a grayscale image.

    Returns a list of (4, 2) arrays, each with corners ordered TL, TR, BR, BL
    and sub-pixel refined.
    """
    h, w = gray.shape[:2]
    img_area = h * w
    min_area = img_area * min_area_frac
    max_area = img_area * max_area_frac

    th = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 51, 10
    )

    raw_squares = []

    for binary in [th, cv2.bitwise_not(th)]:
        contours, _ = cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < min_area or area > max_area:
                continue
            peri = cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, 0.04 * peri, True)
            if len(approx) != 4:
                continue
            if not cv2.isContourConvex(approx):
                continue

            pts = approx.reshape(4, 2).astype(np.float64)
            side_lengths = [np.linalg.norm(pts[(i + 1) % 4] - pts[i]) for i in range(4)]
            mean_side = np.mean(side_lengths)
            if mean_side < 10:
                continue
            aspect_dev = max(side_lengths) / min(side_lengths) - 1.0
            if aspect_dev > 0.3:
                continue

            # Verify interior is uniformly dark or light
            mask = np.zeros(gray.shape[:2], dtype=np.uint8)
            cv2.fillConvexPoly(mask, approx.reshape(4, 2).astype(np.int32), 255)
            roi_stddev = cv2.meanStdDev(gray, mask=mask)[1][0, 0]
            if roi_stddev > 50:
                continue

            ordered = _order_square_corners(pts)
            if ordered is None:
                continue
            raw_squares.append(ordered)

    if not raw_squares:
        return []

    # Deduplicate: two detections whose centers are within half a side length
    # of each other are the same square — keep the one with better aspect ratio.
    centers = np.array([sq.mean(axis=0) for sq in raw_squares])
    median_side = np.median([
        np.mean([np.linalg.norm(sq[(i + 1) % 4] - sq[i]) for i in range(4)])
        for sq in raw_squares
    ])
    dedup_dist = median_side * 0.5

    keep = []
    used = set()
    for i in range(len(raw_squares)):
        if i in used:
            continue
        group = [i]
        for j in range(i + 1, len(raw_squares)):
            if j in used:
                continue
            if np.linalg.norm(centers[i] - centers[j]) < dedup_dist:
                group.append(j)
                used.add(j)
        # Keep the square with the best (lowest) aspect deviation
        best = min(group, key=lambda idx: (
            max(np.linalg.norm(raw_squares[idx][(k + 1) % 4] - raw_squares[idx][k])
                for k in range(4))
            / max(1e-9, min(np.linalg.norm(raw_squares[idx][(k + 1) % 4] - raw_squares[idx][k])
                            for k in range(4)))
        ))
        keep.append(raw_squares[best])
        used.add(i)

    # Sub-pixel refine all kept squares
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
    refined = []
    for sq in keep:
        corners = sq.reshape(-1, 1, 2).astype(np.float32)
        corners = cv2.cornerSubPix(gray, corners, (5, 5), (-1, -1), criteria)
        refined.append(corners.reshape(4, 2))

    return refined


def _assign_grid_positions(
    squares: list[np.ndarray],
) -> list[tuple[int, int, np.ndarray]]:
    """
    Assign integer grid (row, col) positions to detected squares.

    Uses the first square as anchor (0, 0) and finds grid offsets for all
    others based on center-to-center distances relative to the median
    square side length (≈ one grid step in pixels).

    Returns list of (row, col, corners_4x2) tuples.
    """
    centers = np.array([sq.mean(axis=0) for sq in squares])
    # Estimate grid step as median side length across all squares
    all_sides = []
    for sq in squares:
        for i in range(4):
            all_sides.append(np.linalg.norm(sq[(i + 1) % 4] - sq[i]))
    grid_step = np.median(all_sides)

    # Use anchor square to determine grid axes from its edges
    anchor = squares[0]
    # TL->TR direction ≈ column axis, TL->BL direction ≈ row axis
    col_vec = (anchor[1] - anchor[0])  # TL -> TR
    row_vec = (anchor[3] - anchor[0])  # TL -> BL
    col_vec = col_vec / np.linalg.norm(col_vec)
    row_vec = row_vec / np.linalg.norm(row_vec)

    result = [(0, 0, squares[0])]
    anchor_center = centers[0]

    for i in range(1, len(squares)):
        delta = centers[i] - anchor_center
        col_offset = np.dot(delta, col_vec) / grid_step
        row_offset = np.dot(delta, row_vec) / grid_step
        col_idx = round(col_offset)
        row_idx = round(row_offset)
        # Reject if too far from integer grid (likely a false detection)
        if abs(col_offset - col_idx) > 0.35 or abs(row_offset - row_idx) > 0.35:
            continue
        result.append((row_idx, col_idx, squares[i]))

    return result


# ── Camera pose from checkerboard ─────────────────────────────────────────────

def estimate_camera_pose(
    image: Union[np.ndarray, str, Path],
    calib_path: str,
    square_size_mm: float = 22.5,
) -> tuple:
    """
    Detect a single checkerboard square in *image* and compute the camera
    pose via solvePnP.  Works even when only one square is visible.

    The returned rvec/tvec describe the transformation from the detected
    square's frame to camera frame:  p_cam = R @ p_board + tvec

    Args:
        image:          BGR numpy array, or path to an image file.
        calib_path:     Path to calibration.json.
        square_size_mm: Square edge length in mm.

    Returns:
        (success, rvec, tvec, camera_matrix, dist_coeff)
        success        : bool – False if no square was detected.
        rvec           : (3, 1) rotation vector (Rodrigues).
        tvec           : (3, 1) translation vector in mm.
        camera_matrix  : (3, 3)
        dist_coeff     : (1, 5)
    """
    calib = load_calibration(calib_path)
    camera_matrix = calib["camera_matrix"]
    dist_coeff = calib["dist_coeff"]

    if isinstance(image, (str, Path)):
        bgr = cv2.imread(str(image))
        if bgr is None:
            raise FileNotFoundError(f"Cannot read image: {image}")
    else:
        bgr = image

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    squares = _detect_squares(gray)
    if not squares:
        return False, None, None, camera_matrix, dist_coeff

    grid = _assign_grid_positions(squares)

    if len(grid) == 1:
        # Single square: use IPPE_SQUARE (needs centered object points)
        row, col, sq = grid[0]
        half = square_size_mm / 2.0
        objp = np.array([
            [-half,  half, 0],
            [ half,  half, 0],
            [ half, -half, 0],
            [-half, -half, 0],
        ], dtype=np.float32)
        img_pts = sq.reshape(-1, 1, 2).astype(np.float32)

        n_solutions, rvecs, tvecs, _ = cv2.solvePnPGeneric(
            objp, img_pts, camera_matrix, dist_coeff,
            flags=cv2.SOLVEPNP_IPPE_SQUARE,
        )
        if n_solutions == 0:
            return False, None, None, camera_matrix, dist_coeff
        best_idx = 0
        for i in range(n_solutions):
            if tvecs[i][2, 0] > 0:
                best_idx = i
                break
        return True, rvecs[best_idx], tvecs[best_idx], camera_matrix, dist_coeff

    # Multiple squares: collect all corners with grid-based 3D coordinates
    all_obj = []
    all_img = []
    for row, col, sq in grid:
        # Corner 3D positions based on grid (row, col)
        # TL, TR, BR, BL of the square at grid position (row, col)
        x0 = col * square_size_mm
        y0 = row * square_size_mm
        all_obj.extend([
            [x0, y0, 0],
            [x0 + square_size_mm, y0, 0],
            [x0 + square_size_mm, y0 + square_size_mm, 0],
            [x0, y0 + square_size_mm, 0],
        ])
        all_img.extend(sq.tolist())

    objp = np.array(all_obj, dtype=np.float32)
    imgp = np.array(all_img, dtype=np.float32).reshape(-1, 1, 2)

    success, rvec, tvec = cv2.solvePnP(objp, imgp, camera_matrix, dist_coeff)
    return bool(success), rvec, tvec, camera_matrix, dist_coeff


# ── Keypoint to board-plane 3D position ───────────────────────────────────────

def keypoint_to_board_coords(
    norm_y: float,
    norm_x: float,
    rvec: np.ndarray,
    tvec: np.ndarray,
    camera_matrix: np.ndarray,
    dist_coeff: np.ndarray,
    image_width: int = 1280,
    image_height: int = 720,
) -> np.ndarray:
    """
    Project a normalized image keypoint onto the checkerboard plane (Z_board = 0).

    Keypoints are assumed to lie on the same plane as the checkerboard (the work
    surface).  The function back-projects the image ray and intersects it with
    Z_board = 0.

    Args:
        norm_y, norm_x : Keypoint in normalized [0, 1000] coords (height-first).
        rvec           : Rotation vector from estimate_camera_pose.
        tvec           : Translation vector from estimate_camera_pose (mm).
        camera_matrix  : (3, 3) intrinsic matrix.
        dist_coeff     : (1, 5) distortion coefficients.
        image_width    : Pixel width of the image.
        image_height   : Pixel height of the image.

    Returns:
        np.ndarray shape (3,) — [x_mm, y_mm, 0] in board frame (mm).
    """
    px = (norm_x / 1000.0) * image_width
    py = (norm_y / 1000.0) * image_height

    # Undistort the pixel point → normalized camera coordinates (removes K and distortion)
    pt = np.array([[[px, py]]], dtype=np.float64)
    pt_norm = cv2.undistortPoints(pt, camera_matrix, dist_coeff)  # shape (1,1,2)
    xn, yn = pt_norm[0, 0]  # normalized, undistorted

    # Ray direction in camera frame
    d = np.array([xn, yn, 1.0])

    # Board-to-camera rotation matrix
    R, _ = cv2.Rodrigues(rvec)
    R_inv = R.T  # R is orthogonal → R^{-1} = R^T
    t = tvec.flatten()

    # Intersect ray with Z_board = 0:
    #   p_cam = s * d   (ray from camera centre)
    #   p_board = R_inv @ (p_cam - t)
    #   p_board[2] = 0  →  R_inv[2,:] @ (s*d - t) = 0
    #                       s = (R_inv[2,:] @ t) / (R_inv[2,:] @ d)
    r3 = R_inv[2, :]
    denom = r3 @ d
    if abs(denom) < 1e-8:
        raise ValueError("Ray is parallel to the board plane; cannot intersect.")
    s = (r3 @ t) / denom

    p_cam = s * d
    p_board = R_inv @ (p_cam - t)
    p_board[2] = 0.0  # enforce exact Z=0

    return p_board


# ── Movement delta ────────────────────────────────────────────────────────────

def compute_movement_to_keypoint(
    norm_y: float,
    norm_x: float,
    rvec: np.ndarray,
    tvec: np.ndarray,
    camera_matrix: np.ndarray,
    dist_coeff: np.ndarray,
    image_width: int = 1280,
    image_height: int = 720,
) -> np.ndarray:
    """
    Compute the camera movement delta (in camera frame, mm) to center the
    optical axis on the given keypoint.

    The keypoint is assumed to lie on the checkerboard plane (Z_board = 0).
    The camera needs to translate laterally (X_cam, Y_cam) by the amount that
    the keypoint is off-centre in 3D.  Depth (Z_cam) is unchanged.

    Camera frame convention:
        X_cam  = rightward in image
        Y_cam  = downward in image
        Z_cam  = forward (toward board)

    Typical robot mapping for a straight-down mount:
        delta_robot [x, y, z] (metres) = [dy_cam/1000, -dx_cam/1000, 0]

    Args:
        norm_y, norm_x : Keypoint in [0, 1000] normalized coords.
        rvec           : Rotation vector from estimate_camera_pose.
        tvec           : Translation vector from estimate_camera_pose (mm).
        camera_matrix  : (3, 3) intrinsic matrix.
        dist_coeff     : (1, 5) distortion coefficients.
        image_width    : Pixel width of the image.
        image_height   : Pixel height of the image.

    Returns:
        np.ndarray shape (3,) — [dx_cam, dy_cam, 0] in mm.
        Divide by 1000 to convert to metres for use with cartesian_move().
    """
    p_board = keypoint_to_board_coords(
        norm_y, norm_x, rvec, tvec, camera_matrix, dist_coeff,
        image_width, image_height,
    )

    R, _ = cv2.Rodrigues(rvec)
    t = tvec.flatten()
    p_cam = R @ p_board + t  # keypoint in camera frame (mm)

    # Camera is at origin; keypoint is at p_cam.
    # Lateral offset is (p_cam[0], p_cam[1]).
    delta = np.array([p_cam[0], p_cam[1], 0.0])
    return delta


# ── CLI demo ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Estimate camera pose and compute movement delta for a keypoint."
    )
    parser.add_argument("--image", required=True, help="Path to image with checkerboard.")
    parser.add_argument(
        "--calib",
        default="data/arm_cam_calib/calibration.json",
        help="Path to calibration JSON.",
    )
    parser.add_argument(
        "--keypoint",
        default=None,
        help="Normalized keypoint as 'norm_y,norm_x' in [0,1000]. E.g. 500,300",
    )
    parser.add_argument("--viz", action="store_true", help="Show detected corners.")
    args = parser.parse_args()

    bgr = cv2.imread(args.image)
    if bgr is None:
        raise SystemExit(f"Cannot read image: {args.image}")

    success, rvec, tvec, K, D = estimate_camera_pose(bgr, args.calib)

    if not success:
        print("Checkerboard NOT detected in image.")
    else:
        print("Checkerboard detected.")
        print(f"  rvec: {rvec.flatten().round(4)}")
        print(f"  tvec: {tvec.flatten().round(2)} mm")

        if args.keypoint:
            ny, nx = map(float, args.keypoint.split(","))
            h, w = bgr.shape[:2]
            delta = compute_movement_to_keypoint(ny, nx, rvec, tvec, K, D, w, h)
            p_board = keypoint_to_board_coords(ny, nx, rvec, tvec, K, D, w, h)
            print(f"\nKeypoint [{ny}, {nx}] (norm):")
            print(f"  Board position : [{p_board[0]:.1f}, {p_board[1]:.1f}] mm")
            print(f"  Camera delta   : dx={delta[0]:.1f} mm, dy={delta[1]:.1f} mm")
            print(f"  Robot delta (straight-down mount):")
            print(f"    x={delta[1]/1000:.4f} m, y={-delta[0]/1000:.4f} m, z=0 m")

        if args.viz:
            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            squares = _detect_squares(gray)
            grid = _assign_grid_positions(squares)
            print(f"  Detected {len(squares)} squares, {len(grid)} on grid")
            for row, col, sq in grid:
                pts = sq.astype(np.int32)
                cv2.polylines(bgr, [pts], True, (0, 255, 0), 2)
                center = pts.mean(axis=0).astype(int)
                cv2.putText(bgr, f"{row},{col}", tuple(center),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 0, 0), 1)
            out_path = str(Path(args.image).with_suffix(".out.png"))
            cv2.imwrite(out_path, bgr)
            print(f"Visualization saved to {out_path}")
