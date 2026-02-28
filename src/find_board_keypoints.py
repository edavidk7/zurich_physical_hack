#!/usr/bin/env python3
"""
vlm keypoint extractor for robotic test point localization.
uses gemini robotics-er 1.5 to ground schematic references onto live camera feeds.

usage:
    python vlm_keypoint.py schematic.png camera.png -p "the ATmega328P chip"
    python vlm_keypoint.py ref1.png ref2.png camera.png -p "test point TP1 near the voltage regulator"
"""

import argparse
import json
import mimetypes
import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image, ImageOps
from google import genai
from google.genai import types


def parse_json_response(raw_text: str) -> list[dict]:
    """strip markdown fences and parse json from model output."""
    cleaned = re.sub(r"^```\w*\n?|```$", "", raw_text.strip()).strip()
    data = json.loads(cleaned)
    if not isinstance(data, list):
        data = [data]
    return data

def load_and_prep_image(img_path: Path, target_width: int | None) -> Image.Image:
    """bakes exif rotation and normalizes resolution for the ER model."""
    img = Image.open(img_path)
    img = ImageOps.exif_transpose(img)
    if target_width is not None:
        aspect_ratio = img.size[1] / img.size[0]
        img = img.resize((target_width, int(target_width * aspect_ratio)), Image.Resampling.LANCZOS)
    return img


def main():
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
        "-p", "--prompt",
        default="the four corners of the Arduino board",
        help="the component or feature to localize",
    )
    parser.add_argument(
        "-tb", "--thinking-budget",
        type=int,
        default=10000,
        help="thinking budget for the model. 0 for simple pointing, higher for complex reasoning (default: 0)",
    )
    
    parser.add_argument(
        "-tl",
        "--thinking-level",
        type=str,
        choices=["minimal","low","medium","high", None],
        default=None,
        help="thinking level of the model (for newer gemini 3)",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.0,
        help="sampling temperature",
    )
    parser.add_argument(
        "--model",
        default="gemini-3.1-pro-preview",
        help="model id",
    )
    parser.add_argument(
        "-tw",
        "--target_width",
        default=None
    )
    args = parser.parse_args()

    # validate all image paths upfront
    for img_path in args.images:
        if not Path(img_path).exists():
            print(f"!!! file not found: {img_path}")
            return

    client = genai.Client()

    # build multimodal content: label each image so the model can differentiate
    contents = []
    total_imgs = len(args.images)

    for idx, img_path in enumerate(args.images, start=1):
        img = load_and_prep_image(img_path, args.target_width)
        if idx < total_imgs - 1:
            contents.append(f"Image {idx} (reference schematic/documentation):")
        else:
            contents.append(f"Image {idx} (live camera feed — locate objects HERE):")
        contents.append(
            img
        )

    prompt = f"""
Locate the following in Image {total_imgs} (the live camera feed): {args.prompt}.
The preceding images are reference schematics for context only.

Rules:
- You MUST return EXACTLY the points described — no more, no fewer.
- Do NOT add extra points, explanations, or commentary.
- output top left, top right, bottom left, bottom right as labels
- Output ONLY a JSON array. No markdown, no prose, nothing else.
- Format: [{{"point": [y, x], "label": "<short label>"}}]
- Points are [y, x] normalized to 0-1000.
- You MUST return ALL points, even if some are partially visible or at the image edge. Do not omit any.

Think super hard about this. 
"""
    contents.append(prompt)

    print(f"querying {args.model} (thinking_budget={args.thinking_budget})...")
    
    thinking_args = {"include_thoughts": True}
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

    # load the target image (always the last one) for visualization
    target_img = Image.open(args.images[-1])
    target_img = ImageOps.exif_transpose(target_img)
    width, height = target_img.size

    fig, ax = plt.subplots(figsize=(10, 8))
    ax.imshow(target_img)

    # plot all detected points
    colors = ["#00ff00", "#ff00ff", "#00ffff", "#ffff00", "#ff8800"]
    for i, detection in enumerate(data):
        point = detection["point"]
        label = detection.get("label", f"target_{i}")

        # gemini returns [y, x] normalized to 0-1000
        norm_y, norm_x = point[0], point[1]
        px_x = int((norm_x / 1000.0) * width)
        px_y = int((norm_y / 1000.0) * height)

        color = colors[i % len(colors)]

        ax.plot(px_x, px_y, marker="+", color=color, markersize=24, markeredgewidth=3)
        circle = plt.Circle(
            (px_x, px_y), radius=width * 0.02, color=color, fill=False, linewidth=2
        )
        ax.add_patch(circle)
        ax.annotate(
            label,
            (px_x, px_y),
            textcoords="offset points",
            xytext=(12, -12),
            color=color,
            fontsize=10,
            fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.2", facecolor="black", alpha=0.7),
        )

        print(f"  [{i}] '{label}' -> pixel ({px_x}, {px_y})  [norm: y={norm_y}, x={norm_x}]")

    ax.set_title(f"Prompt: {args.prompt} | {len(data)} point(s) detected")
    ax.axis("off")
    plt.tight_layout()
    out_path = Path(args.images[-1]).with_suffix(".out.png")
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"saved to {out_path}")


if __name__ == "__main__":
    main()
