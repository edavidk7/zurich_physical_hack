"""
Live depth estimation using Depth Anything V2 Small (HuggingFace transformers).

Model: depth-anything/Depth-Anything-V2-Small-hf
Docs:  https://huggingface.co/depth-anything/Depth-Anything-V2-Small-hf

Install deps:
    pip install transformers torch torchvision

Controls:
    q / ESC  — quit
    c        — cycle depth colourmap
    s        — save current frame pair as depth_frame_<n>.png
    +/-      — increase / decrease inference resolution (affects speed vs quality)
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np

# ---------------------------------------------------------------------------
# Lazy-import heavy deps with clear error messages
# ---------------------------------------------------------------------------
try:
    import torch
except ImportError:
    print("ERROR: torch not found. Run: pip install torch torchvision")
    sys.exit(1)

try:
    from transformers import AutoImageProcessor, AutoModelForDepthEstimation
except ImportError:
    print("ERROR: transformers not found. Run: pip install transformers")
    sys.exit(1)

from PIL import Image

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MODELS = {
    "relative": "depth-anything/Depth-Anything-V2-Small-hf",
    "indoor":   "depth-anything/Depth-Anything-V2-Metric-Indoor-Small-hf",
    "outdoor":  "depth-anything/Depth-Anything-V2-Metric-Outdoor-Small-hf",
}

COLORMAPS = [
    ("TURBO",   cv2.COLORMAP_TURBO),
    ("JET",     cv2.COLORMAP_JET),
    ("INFERNO", cv2.COLORMAP_INFERNO),
    ("MAGMA",   cv2.COLORMAP_MAGMA),
    ("BONE",    cv2.COLORMAP_BONE),
]

INFER_SIZES = [224, 308, 392, 518]   # multiples of 14 (ViT patch size)


# ---------------------------------------------------------------------------
# Device selection
# ---------------------------------------------------------------------------

def best_device() -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


# ---------------------------------------------------------------------------
# Depth colourisation
# ---------------------------------------------------------------------------

MAX_DEPTH_M = 10.0   # clip metric depth display at this many metres


def depth_to_bgr(
    depth_tensor: torch.Tensor,
    colormap_id: int,
    target_hw: tuple[int, int],
    metric: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Normalise a depth tensor and apply a colourmap, resized to target_hw (H, W).

    Returns (coloured_bgr, depth_metres_float32).
    depth_metres_float32 is meaningful only when metric=True.
    """
    d = depth_tensor.squeeze().float().cpu().numpy()   # raw depth map

    if metric:
        # Clip to a sensible range so the colourmap isn't dominated by far-away noise
        d_vis = np.clip(d, 0.0, MAX_DEPTH_M) / MAX_DEPTH_M
    else:
        d_min, d_max = d.min(), d.max()
        d_vis = (d - d_min) / (d_max - d_min) if d_max > d_min else d

    d_u8 = (d_vis * 255).astype(np.uint8)
    coloured = cv2.applyColorMap(d_u8, colormap_id)

    h, w = target_hw
    if coloured.shape[:2] != (h, w):
        coloured = cv2.resize(coloured, (w, h), interpolation=cv2.INTER_LINEAR)
        d = cv2.resize(d, (w, h), interpolation=cv2.INTER_LINEAR)

    return coloured, d.astype(np.float32)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_display(rgb_bgr: np.ndarray, depth_bgr: np.ndarray) -> np.ndarray:
    cv2.putText(rgb_bgr,   "RGB",   (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(depth_bgr, "DEPTH", (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA)
    return np.hstack([rgb_bgr, depth_bgr])


def run(camera_index: int = 0, infer_size_idx: int = 1, mode: str = "indoor") -> None:
    model_id = MODELS[mode]
    metric = mode != "relative"

    device = best_device()
    print(f"Device: {device}")
    print(f"Loading {model_id} …")

    processor = AutoImageProcessor.from_pretrained(model_id)
    model = AutoModelForDepthEstimation.from_pretrained(model_id).to(device).eval()

    print("Model loaded. Opening camera…")

    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        print(f"ERROR: Cannot open camera {camera_index}")
        sys.exit(1)

    # Warm-up: let auto-exposure settle
    for _ in range(10):
        cap.read()

    window = "Depth Anything V2 Small  |  q=quit  c=colourmap  s=save  +/-=resolution"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.waitKey(1)  # force macOS to render the window

    cmap_idx = 0
    save_count = 0
    fps_t = time.perf_counter()
    fps_frames = 0
    fps_str = "-- fps"

    print("Running. Press 'q' or ESC to quit.")

    while True:
        ret, bgr = cap.read()
        if not ret:
            print("WARNING: dropped frame, retrying…")
            time.sleep(0.02)
            continue

        h, w = bgr.shape[:2]
        rgb_pil = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))

        # Resize input to the chosen inference resolution
        infer_size = INFER_SIZES[infer_size_idx]
        rgb_small = rgb_pil.resize(
            (infer_size, infer_size),
            resample=Image.BILINEAR,
        )

        # --- inference ---------------------------------------------------
        inputs = processor(images=rgb_small, return_tensors="pt").to(device)
        with torch.no_grad():
            outputs = model(**inputs)
        # predicted_depth: (1, H', W')
        pred_depth = outputs.predicted_depth

        depth_bgr, depth_m = depth_to_bgr(pred_depth, COLORMAPS[cmap_idx][1], (h, w), metric=metric)

        # --- FPS ---------------------------------------------------------
        fps_frames += 1
        now = time.perf_counter()
        if now - fps_t >= 1.0:
            fps_str = f"{fps_frames / (now - fps_t):.1f} fps"
            fps_frames = 0
            fps_t = now

        frame = build_display(bgr.copy(), depth_bgr)

        cmap_name = COLORMAPS[cmap_idx][0]
        depth_tag = f"metric-{mode}" if metric else "relative"
        label = f"{fps_str}  cmap:{cmap_name}  infer:{infer_size}px  {depth_tag}  device:{device}"
        cv2.putText(
            frame, label,
            (10, frame.shape[0] - 10),
            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 1, cv2.LINE_AA,
        )

        # Show depth at image centre (metric only)
        if metric:
            cy, cx = h // 2, w // 2
            centre_m = float(depth_m[cy, cx])
            centre_label = f"{centre_m:.2f} m"
            # draw on the depth panel (right half of frame)
            cv2.putText(
                frame, centre_label,
                (w + cx - 30, cy - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2, cv2.LINE_AA,
            )
            cv2.circle(frame, (w + cx, cy), 4, (0, 255, 0), -1)

        cv2.imshow(window, frame)

        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27):
            break
        elif key == ord("c"):
            cmap_idx = (cmap_idx + 1) % len(COLORMAPS)
            print(f"Colourmap → {COLORMAPS[cmap_idx][0]}")
        elif key == ord("s"):
            out = Path(f"depth_frame_{save_count:04d}.png")
            cv2.imwrite(str(out), frame)
            print(f"Saved {out}")
            save_count += 1
        elif key == ord("+") or key == ord("="):
            infer_size_idx = min(infer_size_idx + 1, len(INFER_SIZES) - 1)
            print(f"Inference size → {INFER_SIZES[infer_size_idx]}px")
        elif key == ord("-"):
            infer_size_idx = max(infer_size_idx - 1, 0)
            print(f"Inference size → {INFER_SIZES[infer_size_idx]}px")

    cap.release()
    cv2.destroyAllWindows()
    print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Live depth estimation with Depth Anything V2 Small")
    parser.add_argument("--camera", type=int, default=0, help="Camera index (default: 0)")
    parser.add_argument(
        "--infer-size", type=int, default=308,
        choices=INFER_SIZES,
        help="Inference resolution in pixels (default: 308). Lower = faster.",
    )
    parser.add_argument(
        "--mode", default="indoor",
        choices=list(MODELS.keys()),
        help="Depth mode: 'indoor' or 'outdoor' for metric (metres), 'relative' for scale-free (default: indoor).",
    )
    args = parser.parse_args()

    infer_size_idx = INFER_SIZES.index(args.infer_size)
    run(camera_index=args.camera, infer_size_idx=infer_size_idx, mode=args.mode)
