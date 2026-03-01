import cv2
import os
import numpy as np
from typing import Any
import pprint
import json
import matplotlib
matplotlib.use("QtAgg")
import matplotlib.pyplot as plt


def calibrate_camera(image_dir, board_size, square_size, pixel_pitch, output_filename, visualize, intrinsic_guess: bool=False, guessed_intrinsics:dict | None = None) -> dict[str, Any]:
    """
    Calibrates a camera using checkerboard images from a directory.

    Args:
        image_dir (str): Path to the directory containing checkerboard images (.png).
        board_size (tuple): Number of inner corners (rows, cols) in the checkerboard.
        square_size (float): Size of each square in the checkerboard (in mm).
        pixel_pitch (float): Pixel pitch of the camera sensor (in microns).
        output_filename (str, optional): Name of the JSON file to save calibration data. Defaults to "calibration.json".

    Returns:
        dict: Calibration data (camera matrix, distortion coefficients, etc.).
    """
    image_paths = [os.path.join(image_dir, f) for f in os.listdir(image_dir) if f.endswith(".jpg")]
    image_paths.sort(reverse=True)

    # Termination criteria for cornerSubPix
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)

    # Prepare object points (0,0,0), (1,0,0), (2,0,0) ....,(cols-1,rows-1,0)
    objp = np.zeros((board_size[0] * board_size[1], 3), np.float32)
    objp[:, :2] = np.mgrid[0:board_size[0], 0:board_size[1]].T.reshape(-1, 2)
    objp = objp * square_size

    # Arrays to store object points and image points from all the images.
    objpoints = []  # 3d point in real world space
    imgpoints = []  # 2d points in image plane.

    for image_path in image_paths:
        bgr = cv2.imread(image_path)
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        # Find the chess board corners
        ret, corners = cv2.findChessboardCorners(gray, board_size, None)
        # If found, add object points, image points (after refining them)
        if ret == True:
            objpoints.append(objp)
            # Refine corner locations
            corners2 = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
            imgpoints.append(corners2)
            if visualize:
                # Draw and display the corners (for debugging)
                img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
                cv2.drawChessboardCorners(img, board_size, corners2, ret)
                cv2.imshow('img', img)
                cv2.waitKey(1000)
        else:
            print(f"Checkerboard not found in {image_path}")

    cv2.destroyAllWindows()

    if len(objpoints) == 0:
        raise Exception("No checkerboards found in the provided images.  Calibration cannot proceed.")

    # Calibrate the camera
    if intrinsic_guess and guessed_intrinsics is not None:
        # Create an initial camera matrix with the guessed intrinsics
        print("Using guessed intrinsics as initial estimate for calibration:")
        initial_camera_matrix = np.array([[guessed_intrinsics["fx"], 0, guessed_intrinsics["cx"]],
                                          [0, guessed_intrinsics["fy"], guessed_intrinsics["cy"]],
                                          [0, 0, 1]], dtype=np.float64)
        ret, mtx, dist, rvecs, tvecs = cv2.calibrateCamera(objpoints, imgpoints, gray.shape[::-1], initial_camera_matrix, None, flags=cv2.CALIB_USE_INTRINSIC_GUESS)
    else:
        ret, mtx, dist, rvecs, tvecs = cv2.calibrateCamera(objpoints, imgpoints, gray.shape[::-1], None, None)

    # Metric focal length
    f_mm = mtx[0, 0].item() * pixel_pitch / 1000

    if visualize:
        fig = plt.figure(figsize=(18, 10))
        ax = fig.add_subplot(111, projection='3d')
        for i, (r, t, o) in enumerate(zip(rvecs, tvecs, objpoints)):
            R, _ = cv2.Rodrigues(r)
            points3d = np.dot(R, o.T) + t
            ax.scatter(points3d[0], points3d[1], points3d[2], marker='o', label=image_paths[i].split("/")[-1], color=((i + 1) / len(objpoints), 0, 0))
        ax.set_title('3D Checkerboard Points')
        ax.scatter(0, 0, 0, marker='x', color='black', label='Origin - pinhole/lens pupil', s=20)
        ax.set_xlabel('X')
        ax.set_ylabel('Y')
        ax.set_zlabel('Z')
        ax.legend(loc='right', bbox_to_anchor=(1.35, 0.5))
        fig.tight_layout()
        plt.show()

    # Save the calibration data to a JSON file
    calibration_data = {
        "camera_matrix": mtx.tolist(),
        "dist_coeff": dist.tolist(),
        "image_size_px": gray.shape[::-1],
        "board_size": board_size,
        "square_size_mm": square_size,
        "pixel_pitch_micron": pixel_pitch,
        "f_mm": f_mm,
        "rms_error": ret
    }
    output_path = os.path.join(image_dir, output_filename)
    with open(output_path, 'w') as outfile:
        json.dump(calibration_data, outfile, indent=4)

    print(f"Calibration data saved to {output_path}")

    return calibration_data


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", type=str, required=True)
    parser.add_argument("--board_size", type=int, nargs=2, required=True)
    parser.add_argument("--square_size", type=float, required=True)
    parser.add_argument("--pixel_pitch", type=float, required=True)
    parser.add_argument("--vis", action="store_true", default=False)
    parser.add_argument("--output", type=str, default="calibration.json")
    parser.add_argument("--intrinsic_guess", action="store_true", default=False, help="Whether to use guessed intrinsics as the initial estimate for calibration")
    parser.add_argument("--fx_guess", type=float, default=0.0, help="Guessed focal length in pixels (fx) for intrinsic_guess"
                        )
    parser.add_argument("--fy_guess", type=float, default=0.0, help="Guessed focal length in pixels (fy) for intrinsic_guess"
                        )
    parser.add_argument("--cx_guess", type=float, default=0.0, help="Guessed principal point x-coordinate in pixels (cx) for intrinsic_guess"
                        )
    parser.add_argument("--cy_guess", type=float, default=0.0, help="Guessed principal point y-coordinate in pixels (cy) for intrinsic_guess"
                        )
    args = parser.parse_args()
    if args.intrinsic_guess:
        if args.fx_guess <= 0 or args.fy_guess <= 0:
            raise ValueError("Guessed focal lengths (fx_guess and fy_guess) must be positive when using intrinsic_guess.")
        if args.cx_guess < 0 or args.cy_guess < 0:
            raise ValueError("Guessed principal point coordinates (cx_guess and cy_guess) must be non-negative when using intrinsic_guess.")
        guessed_intrinsics = {
            "fx": args.fx_guess,
            "fy": args.fy_guess,
            "cx": args.cx_guess,
            "cy": args.cy_guess
        }
    try:
        calib_data = calibrate_camera(args.src, args.board_size, args.square_size, args.pixel_pitch, visualize=args.vis, output_filename=args.output, guessed_intrinsics=guessed_intrinsics if args.intrinsic_guess else None, intrinsic_guess=args.intrinsic_guess)
        pprint.pprint(calib_data)
    except Exception as e:
        print(f"Error: {e}")
