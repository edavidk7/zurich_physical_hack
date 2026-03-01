#!/usr/bin/env python3
"""
vlm keypoint extractor for robotic test point localization.
uses gemini to ground schematic references onto live camera feeds.

usage:
    python vlm_keypoint.py schematic.png camera.png -p "the ATmega328P chip"
    python vlm_keypoint.py ref1.png ref2.png camera.png -p "test point TP1 near the voltage regulator"
"""

import argparse
import base64
import io
import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from PIL import Image, ImageDraw, ImageOps
from google import genai
from google.genai import types


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

KEYPOINT_COLORS = ["#00ff00", "#ff00ff", "#00ffff", "#ffff00", "#ff8800"]


def parse_json_response(raw_text: str) -> list[dict]:
    """strip markdown fences and parse json from model output."""
    cleaned = re.sub(r"^```\w*\n?|```$", "", raw_text.strip()).strip()
    data = json.loads(cleaned)
    if not isinstance(data, list):
        data = [data]
    return data


def load_and_prep_image(img_path: Path, target_width: int | None = None) -> Image.Image:
    """bakes exif rotation and normalizes resolution for the ER model."""
    img = Image.open(img_path)
    img = ImageOps.exif_transpose(img)
    if target_width is not None:
        aspect_ratio = img.size[1] / img.size[0]
        img = img.resize(
            (target_width, int(target_width * aspect_ratio)), Image.Resampling.LANCZOS
        )
    return img


# ---------------------------------------------------------------------------
# Core API — importable by server (no matplotlib)
# ---------------------------------------------------------------------------


def extract_keypoints(
    reference_images: list[Image.Image],
    camera_image: Image.Image,
    prompt: str,
    model: str = "gemini-2.5-flash",
    thinking_budget: int = 0,
) -> list[dict]:
    """
    Call the VLM to locate keypoints in the camera image using reference images.

    Returns a list of dicts: [{"point": [y, x], "label": str}]
    Coordinates are normalised to 0-1000.
    """
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

    contents = []
    cam_idx = len(reference_images) + 1

    for idx, img in enumerate(reference_images, start=1):
        contents.append(f"Image {idx} (reference schematic/documentation):")
        contents.append(img)

    contents.append(f"Image {cam_idx} (live camera feed — locate objects HERE):")
    contents.append(camera_image)
    contents.append(
        f"Locate the following in Image {cam_idx} (the live camera feed): {prompt}.\n"
        "The preceding images are reference schematics for context only.\n"
        'Return the answer as JSON: [{"point": [y, x], "label": "<name>"}].\n'
        "Points are in [y, x] format normalised to 0-1000.\n"
        f"Only return points visible in Image {cam_idx}. If not found, return []."
    )

    response = client.models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            temperature=1.0,
            thinking_config=types.ThinkingConfig(
                include_thoughts=True,
                thinking_budget=thinking_budget,
            ),
        ),
    )

    return parse_json_response(response.text.strip())


def annotate_image_pil(image: Image.Image, keypoints: list[dict]) -> Image.Image:
    """
    Draw keypoint markers on a PIL Image. Returns a new annotated RGB image.
    Also mutates each keypoint dict to add a "pixel": [px_x, px_y] field.
    """
    img = image.copy().convert("RGB")
    draw = ImageDraw.Draw(img)
    w, h = img.size
    r = max(12, int(w * 0.018))

    for i, det in enumerate(keypoints):
        point = det["point"]
        label = det.get("label", f"target_{i}")
        norm_y, norm_x = point[0], point[1]
        px_x = int((norm_x / 1000.0) * w)
        px_y = int((norm_y / 1000.0) * h)
        color = KEYPOINT_COLORS[i % len(KEYPOINT_COLORS)]

        # circle
        draw.ellipse([px_x - r, px_y - r, px_x + r, px_y + r], outline=color, width=3)
        # crosshair
        draw.line([(px_x - r - 6, px_y), (px_x + r + 6, px_y)], fill=color, width=2)
        draw.line([(px_x, px_y - r - 6), (px_x, px_y + r + 6)], fill=color, width=2)
        # label background + text
        tx, ty = px_x + r + 6, px_y - 10
        bbox = draw.textbbox((tx, ty), label)
        draw.rectangle(
            [bbox[0] - 3, bbox[1] - 2, bbox[2] + 3, bbox[3] + 2], fill="black"
        )
        draw.text((tx, ty), label, fill=color)

        det["pixel"] = [px_x, px_y]

    return img


def annotated_image_to_base64(image: Image.Image) -> str:
    """Encode a PIL Image as a base64 PNG string."""
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


# ---------------------------------------------------------------------------
# Closed-loop action API
# ---------------------------------------------------------------------------

ACTION_SCHEMA = """
Return a JSON object describing your next action. Choose exactly one of:

1. If you are NOT confident the target is visible / well-centred / sharp enough:
   {"action": "look", "point": [y, x], "reason": "<short explanation>"}
   • "point" is where in the CURRENT image you want the camera to move toward
     (normalised 0-1000, height-first).
   • Use this when: target not found, too blurry, at image edge, occluded, or
     any other condition that means a better viewing angle is needed.

2. If you ARE confident you see the target clearly and are ready to place:
   {"action": "place", "point": [y, x], "label": "<component name>",
    "confidence": <float 0.0-1.0>}
   • "confidence" must be >= 0.9 before a place is attempted.
   • Only choose this when the target is sharp, near the image centre, and
     unambiguously identified.

Do NOT return a list — return a single JSON object.
"""


_mock_extract_action_call_count: int = 0


def extract_action(
    reference_images: list[Image.Image],
    camera_image: Image.Image,
    prompt: str,
    model: str = "gemini-2.5-flash",
    thinking_budget: int = 1024,
) -> dict:
    """
    Ask the VLM what to do next in the closed control loop.

    Set env var MOCK_VLM=1 to skip the real Gemini call and return a scripted
    sequence: two "look" responses followed by a confident "place".
    """
    import os

    global _mock_extract_action_call_count
    if os.environ.get("MOCK_VLM") == "1":
        _mock_extract_action_call_count += 1
        n = _mock_extract_action_call_count
        if n < 3:
            return {
                "action": "look",
                "point": [500 + n * 30, 500 - n * 20],
                "reason": f"mock: iteration {n}, still looking",
            }
        else:
            return {
                "action": "place",
                "point": [500, 500],
                "label": f"mock: {prompt}",
                "confidence": 0.95,
            }

    client = genai.Client()

    cam_idx = len(reference_images) + 1
    contents = []

    for idx, img in enumerate(reference_images, start=1):
        contents.append(f"Image {idx} (reference schematic/documentation):")
        contents.append(img)

    contents.append(f"Image {cam_idx} (live camera feed — act on THIS image):")
    contents.append(camera_image)
    contents.append(
        f"Your goal: locate and prepare to place on the following target: {prompt}.\n"
        "The preceding images are reference schematics for context only.\n"
        + ACTION_SCHEMA
    )

    response = client.models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            temperature=1.0,
            thinking_config=types.ThinkingConfig(
                include_thoughts=True,
                thinking_budget=thinking_budget,
            ),
        ),
    )

    raw = response.text.strip()
    # Strip markdown fences if present
    cleaned = re.sub(r"^```\w*\n?|```$", "", raw).strip()
    result = json.loads(cleaned)

    if not isinstance(result, dict) or "action" not in result:
        raise ValueError(f"Unexpected response format: {raw}")
    if result["action"] not in ("look", "place"):
        raise ValueError(f"Unknown action '{result['action']}': {raw}")

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    parser = argparse.ArgumentParser(
        description="vlm keypoint extractor for robotic test point localization",
        epilog="example: python vlm_keypoint.py schematic.png camera.png -p 'the ATmega328P chip'",
    )
    parser.add_argument(
        "images",
        nargs="+",
        help="paths to images. the final image is the live camera feed; preceding images are reference material.",
    )
    parser.add_argument(
        "-p", "--prompt", required=True, help="the component or feature to localize"
    )
    parser.add_argument("-tb", "--thinking-budget", type=int, default=0)
    parser.add_argument(
        "-tl",
        "--thinking-level",
        type=str,
        choices=["minimal", "low", "medium", "high", None],
        default=None,
    )
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--model", default="gemini-3-flash-preview")
    parser.add_argument("-tw", "--target_width", default=None)
    args = parser.parse_args()

    for img_path in args.images:
        if not Path(img_path).exists():
            print(f"!!! file not found: {img_path}")
            return

    ref_imgs = [
        load_and_prep_image(Path(p), args.target_width) for p in args.images[:-1]
    ]
    camera_img = load_and_prep_image(Path(args.images[-1]), args.target_width)

    print(f"querying {args.model} (thinking_budget={args.thinking_budget})...")

    # override thinking config for CLI (supports thinking_level)
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
    cam_idx = len(ref_imgs) + 1
    contents = []
    for idx, img in enumerate(ref_imgs, start=1):
        contents.append(f"Image {idx} (reference schematic/documentation):")
        contents.append(img)
    contents.append(f"Image {cam_idx} (live camera feed — locate objects HERE):")
    contents.append(camera_img)
    contents.append(
        f"Locate the following in Image {cam_idx} (the live camera feed): {args.prompt}.\n"
        "The preceding images are reference schematics for context only.\n"
        'Return the answer as JSON: [{"point": [y, x], "label": "<identifying name>"}].\n'
        "Points are in [y, x] format normalized to 0-1000.\n"
        f"Only return points visible in Image {cam_idx}. If not found, return []."
    )

    thinking_args: dict = {"include_thoughts": True}
    if args.thinking_level is None:
        thinking_args["thinking_budget"] = args.thinking_budget
    else:
        thinking_args["thinking_level"] = args.thinking_level

    response = client.models.generate_content(
        model=args.model,
        contents=contents,
        config=types.GenerateContentConfig(
            temperature=args.temperature,
            thinking_config=types.ThinkingConfig(**thinking_args),
        ),
    )

    raw_text = response.text.strip()
    print(f"Raw model response: {raw_text}")

    try:
        data = parse_json_response(raw_text)
    except Exception as e:
        print(f"!!! failed to parse response: {raw_text}\nerr: {e}")
        return

    if not data:
        print("model returned empty results — target not found in camera feed.")
        return

    annotated = annotate_image_pil(camera_img, data)

    for i, det in enumerate(data):
        px = det.get("pixel", [0, 0])
        print(
            f"  [{i}] '{det.get('label')}' -> pixel {px}  [norm: y={det['point'][0]}, x={det['point'][1]}]"
        )

    # Show with matplotlib
    fig, ax = plt.subplots(figsize=(10, 8))
    ax.imshow(annotated)
    ax.set_title(f"Prompt: {args.prompt} | {len(data)} point(s) detected")
    ax.axis("off")
    plt.tight_layout()
    out_path = Path("keypoint_result.png")
    fig.savefig(out_path, dpi=150)
    print(f"  saved annotated image to {out_path}")
    try:
        plt.show()
    except Exception:
        pass


if __name__ == "__main__":
    main()
