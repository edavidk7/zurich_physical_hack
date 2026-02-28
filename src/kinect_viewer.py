"""
Kinect camera viewer — displays RGB and depth streams side-by-side using OpenCV.

Requires libfreenect + the freenect Python bindings:
    macOS:  brew install libfreenect && pip install freenect
    Linux:  sudo apt install freenect python3-freenect  (or pip install freenect)

Controls:
    q / ESC  — quit
    c        — cycle depth colourmap (TURBO → JET → INFERNO → HOT → BONE)
    s        — save current frame pair as kinect_frame_<n>.png
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import cv2
import numpy as np

try:
    import freenect
except ImportError:
    print(
        "ERROR: 'freenect' not found.\n"
        "Install libfreenect then run:  pip install freenect\n"
        "  macOS:  brew install libfreenect\n"
        "  Linux:  sudo apt install freenect\n"
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# Depth visualisation helpers
# ---------------------------------------------------------------------------

COLORMAPS = [
    ("TURBO",   cv2.COLORMAP_TURBO),
    ("JET",     cv2.COLORMAP_JET),
    ("INFERNO", cv2.COLORMAP_INFERNO),
    ("HOT",     cv2.COLORMAP_HOT),
    ("BONE",    cv2.COLORMAP_BONE),
]

KINECT_DEPTH_MAX = 2047   # 11-bit raw depth; 2047 = no reading


def depth_to_bgr(raw_depth: np.ndarray, colormap_id: int) -> np.ndarray:
    """Convert raw 11-bit Kinect depth to a colourised BGR image."""
    # Mask out invalid / no-reading pixels
    valid = raw_depth < KINECT_DEPTH_MAX

    # Normalise valid pixels to [0, 255]
    norm = np.zeros_like(raw_depth, dtype=np.uint8)
    if valid.any():
        dmin = int(raw_depth[valid].min())
        dmax = int(raw_depth[valid].max())
        if dmax > dmin:
            norm[valid] = ((raw_depth[valid] - dmin) * 255 / (dmax - dmin)).astype(np.uint8)

    coloured = cv2.applyColorMap(norm, colormap_id)
    # Paint invalid pixels black
    coloured[~valid] = 0
    return coloured


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def build_display(rgb_bgr: np.ndarray, depth_bgr: np.ndarray) -> np.ndarray:
    """Stack RGB and depth side-by-side with labels."""
    h, w = rgb_bgr.shape[:2]

    # Resize depth to match RGB dimensions if needed
    if depth_bgr.shape[:2] != (h, w):
        depth_bgr = cv2.resize(depth_bgr, (w, h))

    # Add channel labels
    cv2.putText(rgb_bgr,   "RGB",   (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(depth_bgr, "DEPTH", (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA)

    return np.hstack([rgb_bgr, depth_bgr])


def grab_frames() -> tuple[np.ndarray, np.ndarray] | None:
    """Grab one RGB and one depth frame. Returns None if the device is unavailable."""
    result = freenect.sync_get_video()
    if result is None:
        return None
    rgb_raw, _ = result

    result = freenect.sync_get_depth()
    if result is None:
        return None
    depth_raw, _ = result

    return rgb_raw, depth_raw


def run() -> None:
    cmap_idx = 0
    save_count = 0
    fps_t = time.perf_counter()
    fps_frames = 0
    fps_str = "-- fps"

    # Probe device before opening window
    print("Connecting to Kinect…")
    frames = grab_frames()
    if frames is None:
        print(
            "ERROR: Could not get frames from Kinect.\n"
            "  • Make sure the Kinect is plugged in.\n"
            "  • On macOS you may need:  sudo kextunload -b com.apple.driver.usb.cdc.acm\n"
            "  • Check 'freenect-glview' works from the terminal first.\n"
        )
        sys.exit(1)

    print("Kinect connected.  Press 'q' / ESC to quit, 'c' to cycle colourmap, 's' to save.")

    window = "Kinect Viewer  |  q=quit  c=colormap  s=save"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    # Force macOS to actually render the window before the first imshow
    cv2.waitKey(1)

    while True:
        # --- grab frames -------------------------------------------------
        frames = grab_frames()
        if frames is None:
            print("WARNING: lost frames, retrying…")
            time.sleep(0.05)
            continue

        rgb_raw, depth_raw = frames

        # Convert RGB → BGR for OpenCV
        rgb_bgr = cv2.cvtColor(rgb_raw, cv2.COLOR_RGB2BGR)

        depth_raw = depth_raw.astype(np.int32)
        cmap_name, cmap_id = COLORMAPS[cmap_idx]
        depth_bgr = depth_to_bgr(depth_raw, cmap_id)

        # --- FPS counter -------------------------------------------------
        fps_frames += 1
        now = time.perf_counter()
        if now - fps_t >= 1.0:
            fps_str = f"{fps_frames / (now - fps_t):.1f} fps"
            fps_frames = 0
            fps_t = now

        frame = build_display(rgb_bgr, depth_bgr)

        # Overlay FPS + colormap name
        cv2.putText(
            frame, f"{fps_str}  cmap:{cmap_name}",
            (10, frame.shape[0] - 10),
            cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 1, cv2.LINE_AA,
        )

        cv2.imshow(window, frame)

        # --- key handling ------------------------------------------------
        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27):          # q or ESC
            break
        elif key == ord("c"):              # cycle colourmap
            cmap_idx = (cmap_idx + 1) % len(COLORMAPS)
            print(f"Colormap → {COLORMAPS[cmap_idx][0]}")
        elif key == ord("s"):              # save frame
            out = Path(f"kinect_frame_{save_count:04d}.png")
            cv2.imwrite(str(out), frame)
            print(f"Saved {out}")
            save_count += 1

    cv2.destroyAllWindows()
    freenect.sync_stop()
    print("Kinect viewer closed.")


if __name__ == "__main__":
    run()
