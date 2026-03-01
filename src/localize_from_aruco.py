"""
Camera pose from ArUco markers + 3D keypoint localisation.

Replaces checkerboard-based localisation with ArUco marker detection.
Detects one or more ArUco markers from a printed sheet, recovers the
camera-to-board transform via solvePnP, and ray-casts any pixel onto
the board plane (or an offset plane above it).

Pipeline
--------
1. Load image + camera calibration
2. Detect ArUco markers (DICT_4X4_250)
3. solvePnP from one marker (IPPE, 4 coplanar points) or
   multiple markers (iterative PnP with LM refinement)
4. Cast a ray through the keypoint pixel
5. Intersect ray with the target plane (board Z = plane_offset_m)
6. Report 3D position in board frame and camera frame

Coordinate frames
-----------------
* Camera frame : OpenCV convention (Z forward, X right, Y down)
* Board frame  : origin at the TOP-LEFT corner of marker ID 0,
                 X pointing RIGHT (column direction on the sheet),
                 Y pointing DOWN (row direction on the sheet),
                 Z pointing OUT of the board (towards the camera)

Usage (auto-detect, pick best marker automatically)
-----------------------------------------------------
    uv run python src/localize_from_aruco.py \\
        --image data/arduino/planning_image.jpeg \\
        --pixel 673 160 \\
        --plane-offset 0.003

Usage (specify which marker ID to use for the pose)
-----------------------------------------------------
    uv run python src/localize_from_aruco.py \\
        --image data/arduino/planning_image.jpeg \\
        --pixel 673 160 \\
        --marker-id 0 \\
        --plane-offset 0.003

Python API
----------
    from src.localize_from_aruco import localize_keypoint
    result = localize_keypoint(
        image="...",           # file path or BGR numpy array
        keypoint_px=(673, 160),
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
        ARUCO_MARKER_SIZE_MM,
        ARUCO_SHEET_COLS,
        ARUCO_SHEET_GAP_MM,
        ARUCO_SHEET_ROWS,
        WORKSPACE_PLANE_OFFSET_M,
    )
except ImportError:
    from constants import (
        ARUCO_MARKER_SIZE_MM,
        ARUCO_SHEET_COLS,
        ARUCO_SHEET_GAP_MM,
        ARUCO_SHEET_ROWS,
        WORKSPACE_PLANE_OFFSET_M,
    )

# ArUco dictionary — must match generate_aruco_sheet.py
ARUCO_DICT_TYPE = cv2.aruco.DICT_4X4_250

# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------

_CALIB_PATH = Path(__file__).parents[1] / "data/arm_cam_calib/calibration.json"


def load_calibration(
    path: str | Path = _CALIB_PATH,
) -> tuple[np.ndarray, np.ndarray, float, float]:
    """Return (K 3x3, dist 1x5, marker_size_m, gap_m)."""
    with open(path) as f:
        cal = json.load(f)
    K = np.array(cal["camera_matrix"], dtype=np.float64)
    dist = np.array(cal["dist_coeff"], dtype=np.float64)
    marker_m = cal.get("aruco_marker_size_mm", ARUCO_MARKER_SIZE_MM) / 1000.0
    gap_m = cal.get("aruco_sheet_gap_mm", ARUCO_SHEET_GAP_MM) / 1000.0
    return K, dist, marker_m, gap_m


# ---------------------------------------------------------------------------
# ArUco detection
# ---------------------------------------------------------------------------


class DetectedMarker(NamedTuple):
    """One detected ArUco marker."""

    marker_id: int
    corners_px: np.ndarray  # (4, 2) pixel coords [TL, TR, BR, BL]


def detect_markers(
    image_bgr: np.ndarray,
    marker_id: int | None = None,
    visualize: bool = False,
) -> list[DetectedMarker]:
    """
    Detect ArUco markers in the image.

    Parameters
    ----------
    image_bgr  : BGR image
    marker_id  : if given, filter to only this marker ID
    visualize  : show detection result in a window

    Returns
    -------
    List of DetectedMarker, sorted by marker_id.

    Raises
    ------
    RuntimeError if no markers found (or the requested ID is not visible).
    """
    aruco_dict = cv2.aruco.getPredefinedDictionary(ARUCO_DICT_TYPE)
    params = cv2.aruco.DetectorParameters()
    detector = cv2.aruco.ArucoDetector(aruco_dict, params)

    corners_list, ids, rejected = detector.detectMarkers(image_bgr)

    if ids is None or len(ids) == 0:
        raise RuntimeError(
            "No ArUco markers detected. Ensure the printed sheet is visible "
            "and well-lit."
        )

    results: list[DetectedMarker] = []
    for i, mid in enumerate(ids.ravel()):
        mid = int(mid)
        if marker_id is not None and mid != marker_id:
            continue
        # corners_list[i] has shape (1, 4, 2); squeeze to (4, 2)
        # OpenCV order: TL, TR, BR, BL (clockwise from top-left)
        c = corners_list[i].reshape(4, 2)
        results.append(DetectedMarker(marker_id=mid, corners_px=c))

    if not results:
        raise RuntimeError(
            f"Marker ID {marker_id} not found among detected IDs: "
            f"{sorted(ids.ravel().tolist())}"
        )

    results.sort(key=lambda m: m.marker_id)

    if visualize:
        vis = image_bgr.copy()
        cv2.aruco.drawDetectedMarkers(vis, corners_list, ids)
        for det in results:
            cx, cy = det.corners_px.mean(axis=0).astype(int)
            cv2.putText(
                vis,
                f"ID {det.marker_id}",
                (cx - 20, cy - 15),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 0),
                2,
            )
        cv2.namedWindow("ArUco detection", cv2.WINDOW_NORMAL)
        cv2.imshow("ArUco detection", vis)
        cv2.waitKey(0)
        cv2.destroyAllWindows()

    return results


# ---------------------------------------------------------------------------
# Pose estimation
# ---------------------------------------------------------------------------


class BoardPose(NamedTuple):
    """Camera-to-board pose from ArUco markers."""

    R_board_in_cam: np.ndarray  # 3x3 rotation
    t_board_in_cam: np.ndarray  # 3-vector (metres)
    reprojection_err_px: float
    marker_ids: list[int]  # which marker(s) were used


def _marker_grid_pos(marker_id: int) -> tuple[int, int]:
    """Return (row, col) of a marker on the printed sheet (row-major order)."""
    row = marker_id // ARUCO_SHEET_COLS
    col = marker_id % ARUCO_SHEET_COLS
    return row, col


def _marker_obj_corners(
    marker_id: int,
    marker_size_m: float,
    gap_m: float,
) -> np.ndarray:
    """
    Return the 4 object-space corners (TL, TR, BR, BL) of a marker
    on the printed sheet, in metres, Z=0.

    Board frame origin = TL corner of marker ID 0.
      X -> right (column direction)
      Y -> down  (row direction)
    """
    row, col = _marker_grid_pos(marker_id)
    stride = marker_size_m + gap_m
    x0 = col * stride
    y0 = row * stride
    s = marker_size_m
    return np.array(
        [
            [x0, y0, 0.0],  # TL
            [x0 + s, y0, 0.0],  # TR
            [x0 + s, y0 + s, 0.0],  # BR
            [x0, y0 + s, 0.0],  # BL
        ],
        dtype=np.float64,
    )


def _pick_centre_marker(
    markers: list[DetectedMarker],
    image_shape: tuple[int, ...],
) -> DetectedMarker:
    """Return the marker whose centre is closest to the image centre."""
    img_h, img_w = image_shape[:2]
    cx, cy = img_w / 2.0, img_h / 2.0
    best = markers[0]
    best_dist = float("inf")
    for m in markers:
        mc = m.corners_px.mean(axis=0)
        d = (mc[0] - cx) ** 2 + (mc[1] - cy) ** 2
        if d < best_dist:
            best_dist = d
            best = m
    return best


def solve_pose_single(
    marker: DetectedMarker,
    marker_size_m: float,
    gap_m: float,
    K: np.ndarray,
    dist: np.ndarray,
) -> BoardPose:
    """
    Estimate camera-to-board pose from 4 corners of one ArUco marker.

    Board frame origin = TL corner of marker ID 0.
    Uses IPPE (designed for 4 coplanar points).
    """
    obj_pts = _marker_obj_corners(marker.marker_id, marker_size_m, gap_m)
    img_pts = marker.corners_px.reshape(-1, 1, 2).astype(np.float64)

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
        t_i = tvecs[i].ravel()
        if t_i[2] > 0:
            best_idx = i
            break

    R, _ = cv2.Rodrigues(rvecs[best_idx])
    t = tvecs[best_idx].ravel()

    # Reprojection error
    proj, _ = cv2.projectPoints(obj_pts, rvecs[best_idx], tvecs[best_idx], K, dist)
    proj = proj.reshape(-1, 2)
    gt = marker.corners_px.astype(np.float64)
    err = float(np.mean(np.linalg.norm(proj - gt, axis=1)))

    return BoardPose(
        R_board_in_cam=R,
        t_board_in_cam=t,
        reprojection_err_px=err,
        marker_ids=[marker.marker_id],
    )


def solve_pose_multi(
    markers: list[DetectedMarker],
    marker_size_m: float,
    gap_m: float,
    K: np.ndarray,
    dist: np.ndarray,
    image_shape: tuple[int, ...] | None = None,
) -> BoardPose:
    """
    Estimate camera-to-board pose using corners from ALL detected markers.

    Each marker's 4 corners are mapped to their known 3D position on the
    printed sheet (row-major layout, stride = marker_size + gap).
    A single over-constrained solvePnP + LM refinement is used.

    Board frame origin = TL corner of marker ID 0.

    Falls back to single-marker IPPE (closest to image centre) when only
    one marker is detected.
    """
    if len(markers) == 1:
        return solve_pose_single(markers[0], marker_size_m, gap_m, K, dist)

    # Collect 3D-2D correspondences from ALL markers
    all_obj: list[np.ndarray] = []
    all_img: list[np.ndarray] = []
    used_ids: list[int] = []

    for m in markers:
        row, col = _marker_grid_pos(m.marker_id)
        if row >= ARUCO_SHEET_ROWS or col >= ARUCO_SHEET_COLS:
            # Marker ID outside the expected sheet — skip it
            continue
        obj = _marker_obj_corners(m.marker_id, marker_size_m, gap_m)
        all_obj.append(obj)
        all_img.append(m.corners_px.astype(np.float64))
        used_ids.append(m.marker_id)

    if not all_obj:
        # No valid sheet markers — fall back to closest-to-centre single marker
        best = _pick_centre_marker(markers, image_shape or (720, 1280))
        print(
            f"[solve_pose_multi] No markers matched the sheet layout, "
            f"falling back to single marker ID {best.marker_id}"
        )
        return solve_pose_single(best, marker_size_m, gap_m, K, dist)

    obj_pts = np.vstack(all_obj)  # (N*4, 3)
    img_pts = np.vstack(all_img).reshape(-1, 1, 2)  # (N*4, 1, 2)
    n_pts = obj_pts.shape[0]

    print(
        f"[solve_pose_multi] Using {len(used_ids)} markers "
        f"({n_pts} corners) for pose: IDs {used_ids}"
    )

    # Initial solve (iterative for > 4 points)
    success, rvec, tvec = cv2.solvePnP(
        obj_pts,
        img_pts,
        K,
        dist,
        flags=cv2.SOLVEPNP_ITERATIVE,
    )
    if not success:
        # Fallback: closest-to-centre single marker
        best = _pick_centre_marker(markers, image_shape or (720, 1280))
        print(
            f"[solve_pose_multi] solvePnP failed on {n_pts} points, "
            f"falling back to single marker ID {best.marker_id}"
        )
        return solve_pose_single(best, marker_size_m, gap_m, K, dist)

    # Refine with Levenberg-Marquardt
    rvec, tvec = cv2.solvePnPRefineLM(obj_pts, img_pts, K, dist, rvec, tvec)

    R, _ = cv2.Rodrigues(rvec)
    t = tvec.ravel()

    # Ensure board is in front of camera
    if t[2] < 0:
        t = -t
        R = -R

    # Reprojection error
    proj, _ = cv2.projectPoints(obj_pts, rvec, tvec, K, dist)
    proj = proj.reshape(-1, 2)
    gt = img_pts.reshape(-1, 2)
    per_point_err = np.linalg.norm(proj - gt, axis=1)
    mean_err = float(np.mean(per_point_err))

    print(
        f"[solve_pose_multi] {n_pts} corners from {len(used_ids)} markers, "
        f"reproj err: mean={mean_err:.3f} px, max={float(np.max(per_point_err)):.3f} px"
    )

    return BoardPose(
        R_board_in_cam=R,
        t_board_in_cam=t,
        reprojection_err_px=mean_err,
        marker_ids=used_ids,
    )


# ---------------------------------------------------------------------------
# Ray-plane intersection (identical to checkerboard version)
# ---------------------------------------------------------------------------


def pixel_to_3d(
    pixel: tuple[float, float],
    K: np.ndarray,
    dist: np.ndarray,
    pose: BoardPose,
    plane_offset_m: float,
) -> dict:
    """
    Intersect the camera ray through ``pixel`` with a plane parallel to the
    board at height ``plane_offset_m`` above it (board frame Z = plane_offset_m).

    Returns dict:
      pos_cam_m   : np.ndarray (3,) in camera frame (metres)
      pos_board_m : np.ndarray (3,) in board frame (metres)
      depth_m     : float, camera Z depth
    """
    u, v = float(pixel[0]), float(pixel[1])

    pt_norm = cv2.undistortPoints(np.array([[[u, v]]], dtype=np.float64), K, dist)
    xn, yn = float(pt_norm[0, 0, 0]), float(pt_norm[0, 0, 1])

    ray_cam = np.array([xn, yn, 1.0])

    R = pose.R_board_in_cam
    t = pose.t_board_in_cam

    z_board_cam = R[:, 2]
    p_plane_cam = t + R @ np.array([0.0, 0.0, plane_offset_m])

    denom = ray_cam @ z_board_cam
    if abs(denom) < 1e-8:
        raise ValueError(
            "Ray is nearly parallel to the board plane — camera may be viewing "
            "the board edge-on."
        )

    t_ray = (p_plane_cam @ z_board_cam) / denom
    if t_ray < 0:
        raise ValueError(
            f"Intersection behind camera (t={t_ray:.3f}). "
            "Check that the marker is in front of the camera."
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


def annotate_aruco_on_image(
    image_bgr: np.ndarray,
    pose_marker_ids: list[int],
    all_markers: list[DetectedMarker] | None = None,
) -> np.ndarray:
    """
    Draw ArUco marker highlights on a BGR image and return the annotated copy.

    Parameters
    ----------
    image_bgr       : BGR image to annotate
    pose_marker_ids : IDs of markers that were used for pose regression
                      (highlighted with thick cyan outlines + "POSE" label)
    all_markers     : all detected markers (drawn with thin green outlines).
                      If None, only pose markers are drawn.

    Returns
    -------
    Annotated BGR image (copy; original is not modified).
    """
    img = image_bgr.copy()

    # Draw all detected markers with thin green outlines
    if all_markers:
        for m in all_markers:
            pts = m.corners_px.astype(np.int32)
            cv2.polylines(img, [pts], True, (0, 200, 0), 1)
            cx, cy = pts.mean(axis=0).astype(int)
            cv2.putText(
                img,
                str(m.marker_id),
                (cx - 8, cy + 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.4,
                (0, 200, 0),
                1,
            )

    # Highlight pose-used markers with thick cyan outlines + label
    if all_markers:
        pose_set = set(pose_marker_ids)
        for m in all_markers:
            if m.marker_id in pose_set:
                pts = m.corners_px.astype(np.int32)
                cv2.polylines(img, [pts], True, (255, 255, 0), 3)  # cyan in BGR
                cx, cy = pts.mean(axis=0).astype(int)
                cv2.putText(
                    img,
                    f"POSE",
                    (cx - 18, cy - 12),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.45,
                    (255, 255, 0),
                    2,
                )

    return img


def localize_keypoint(
    image: "str | Path | np.ndarray",
    keypoint_px: tuple[float, float],
    plane_offset_m: float = WORKSPACE_PLANE_OFFSET_M,
    calib_path: str | Path = _CALIB_PATH,
    marker_id: int | None = None,
    visualize: bool = False,
    save_annotated: str | Path | None = None,
) -> dict:
    """
    Full localisation pipeline using ArUco markers.

    Parameters
    ----------
    image           : BGR numpy array, or path to an image file
    keypoint_px     : (u, v) pixel of the point of interest
    plane_offset_m  : height of the target plane above the board (metres)
    calib_path      : path to calibration.json
    marker_id       : if given, use only this marker for the pose.
                      Otherwise the lowest-ID detected marker is used.
    visualize       : show detected markers in a window
    save_annotated  : if given, write annotated image here

    Returns dict with:
      pos_cam_m   : [x,y,z] metres in camera frame
      pos_board_m : [x,y,z] metres in board frame
      depth_m     : depth (camera Z)
      pose        : BoardPose named tuple
    """
    K, dist, marker_m, gap_m = load_calibration(calib_path)
    if isinstance(image, np.ndarray):
        image_bgr = image
    else:
        image_bgr = cv2.imread(str(image))
        if image_bgr is None:
            raise FileNotFoundError(f"Cannot load image: {image}")

    markers = detect_markers(image_bgr, marker_id=marker_id, visualize=visualize)

    print(
        f"[localize_keypoint] Detected {len(markers)} marker(s): "
        f"{[m.marker_id for m in markers]}"
    )

    pose = solve_pose_multi(
        markers,
        marker_m,
        gap_m,
        K,
        dist,
        image_shape=image_bgr.shape,
    )

    result = pixel_to_3d(keypoint_px, K, dist, pose, plane_offset_m)
    result["pose"] = pose
    result["detected_markers"] = markers  # all detected markers for annotation

    if save_annotated:
        img = image_bgr.copy()

        # Draw all detected markers
        aruco_dict = cv2.aruco.getPredefinedDictionary(ARUCO_DICT_TYPE)
        params = cv2.aruco.DetectorParameters()
        detector = cv2.aruco.ArucoDetector(aruco_dict, params)
        corners_list, ids, _ = detector.detectMarkers(img)
        if ids is not None:
            cv2.aruco.drawDetectedMarkers(img, corners_list, ids)

        # Highlight the marker(s) used for the pose
        for m in markers:
            pts = m.corners_px.astype(np.int32)
            cv2.polylines(img, [pts], True, (255, 255, 0), 3)
            cx, cy = pts.mean(axis=0).astype(int)
            cv2.putText(
                img,
                f"POSE (ID {m.marker_id})",
                (cx - 40, cy - 20),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (255, 255, 0),
                2,
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
        description="ArUco marker PnP -> 3D keypoint localisation"
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
        "--marker-id",
        type=int,
        default=None,
        help="Use only this marker ID for pose estimation. "
        "Default: lowest-ID detected marker.",
    )
    ap.add_argument(
        "--vis",
        action="store_true",
        help="Show detected markers in a window",
    )
    ap.add_argument(
        "--plane-offset",
        type=float,
        default=WORKSPACE_PLANE_OFFSET_M,
        metavar="M",
        help=f"Target plane height above board (metres)  "
        f"[default: {WORKSPACE_PLANE_OFFSET_M}]",
    )
    ap.add_argument(
        "--calib",
        default=str(_CALIB_PATH),
        help="Path to calibration.json",
    )
    ap.add_argument(
        "--save",
        default=None,
        help="Save annotated image to this path",
    )
    args = ap.parse_args()

    try:
        result = localize_keypoint(
            image=args.image,
            keypoint_px=tuple(args.pixel),
            plane_offset_m=args.plane_offset,
            calib_path=args.calib,
            marker_id=args.marker_id,
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
    print("  ArUco Marker PnP  ->  3D Keypoint")
    print("=" * 58)
    print(f"  Marker(s) used      : {pose.marker_ids}")
    print(f"  Reprojection error  : {pose.reprojection_err_px:.2f} px")
    print(f"  Pixel (u, v)        : ({args.pixel[0]:.0f}, {args.pixel[1]:.0f})")
    print(f"  Plane above board   : {args.plane_offset * 1000:.1f} mm")
    print()
    print("  Position in BOARD frame (origin = TL corner of marker):")
    print(f"    X = {p_b[0] * 1000:+8.2f} mm   (-> along marker top edge)")
    print(f"    Y = {p_b[1] * 1000:+8.2f} mm   (v along marker left edge)")
    print(
        f"    Z = {p_b[2] * 1000:+8.2f} mm   "
        f"(should ~ {args.plane_offset * 1000:.1f} mm, above board)"
    )
    print()
    print("  Position in CAMERA frame:")
    print(f"    X = {p_c[0] * 1000:+8.2f} mm")
    print(f"    Y = {p_c[1] * 1000:+8.2f} mm")
    print(f"    Z = {p_c[2] * 1000:+8.2f} mm   (depth)")
    print()
    print("  --- To get ROBOT-BASE frame --------------------------")
    print("  Apply your camera-to-robot extrinsic T_robot_cam:")
    print("    p_robot = T_robot_cam[:3,:3] @ p_cam + T_robot_cam[:3,3]")
    print("=" * 58)

    if args.save:
        print(f"\n  Annotated image saved: {args.save}")
