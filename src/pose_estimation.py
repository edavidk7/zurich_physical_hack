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


# ── Camera pose from checkerboard ─────────────────────────────────────────────

def estimate_camera_pose(
    image: Union[np.ndarray, str, Path],
    calib_path: str,
    board_size: tuple = (6, 9),
    square_size_mm: float = 22.5,
) -> tuple:
    """
    Detect a checkerboard in *image* and compute the camera pose via solvePnP.

    The returned rvec/tvec describe the transformation from board frame to
    camera frame:  p_cam = R @ p_board + tvec

    Args:
        image:          BGR numpy array, or path to an image file.
        calib_path:     Path to calibration.json.
        board_size:     (rows, cols) of inner corners.  Defaults match calib file.
        square_size_mm: Square edge length in mm.  Defaults match calib file.

    Returns:
        (success, rvec, tvec, camera_matrix, dist_coeff)
        success        : bool – False if checkerboard was not detected.
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

    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
    ret, corners = cv2.findChessboardCorners(gray, board_size, None)

    if not ret:
        return False, None, None, camera_matrix, dist_coeff

    corners_refined = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)

    # Build 3D object points on the Z=0 plane (board frame)
    rows, cols = board_size
    objp = np.zeros((rows * cols, 3), dtype=np.float32)
    objp[:, :2] = np.mgrid[0:rows, 0:cols].T.reshape(-1, 2)
    objp *= square_size_mm  # convert to mm

    success, rvec, tvec = cv2.solvePnP(
        objp, corners_refined, camera_matrix, dist_coeff
    )

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
            calib = load_calibration(args.calib)
            board_size = calib["board_size"]
            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            _, corners = cv2.findChessboardCorners(gray, board_size, None)
            cv2.drawChessboardCorners(bgr, board_size, corners, True)
            cv2.imshow("Checkerboard corners", bgr)
            cv2.waitKey(0)
            cv2.destroyAllWindows()
