#!/usr/bin/env python3
"""
Visualize normalized coordinates on an image.

Coordinates are [y, x] normalized to 0-1000 (matching Gemini robotics output format).

usage:
    # JSON array of {point, label} dicts (same format as model output)
    python visualize_points.py image.png --json '[{"point": [500, 300], "label": "TP1"}]'

    # Bare coordinate pairs: y,x (repeatable)
    python visualize_points.py image.png --point 500,300 --point 200,700

    # Mix: unlabeled points get auto-numbered
    python visualize_points.py image.png --point 100,900 --point 800,200 -l "pin1" "pin2"
"""

import argparse
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("QtAgg")
import matplotlib.pyplot as plt
from PIL import Image


COLORS = ["#00ff00", "#ff00ff", "#00ffff", "#ffff00", "#ff8800", "#ff4444", "#44aaff"]


def plot_points(image_path: str, detections: list[dict], title: str = "") -> None:
    img = Image.open(image_path)
    width, height = img.size

    fig, ax = plt.subplots(figsize=(10, 8))
    ax.imshow(img)

    for i, det in enumerate(detections):
        norm_y, norm_x = det["point"]
        label = det.get("label", f"point_{i}")
        color = COLORS[i % len(COLORS)]

        px_x = int((norm_x / 1000.0) * width)
        px_y = int((norm_y / 1000.0) * height)

        ax.plot(px_x, px_y, marker="+", color=color, markersize=24, markeredgewidth=3)
        circle = plt.Circle((px_x, px_y), radius=width * 0.02, color=color, fill=False, linewidth=2)
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

    n = len(detections)
    ax.set_title(title or f"{n} point(s) on {Path(image_path).name}")
    ax.axis("off")
    plt.tight_layout()
    plt.show()


def main():
    parser = argparse.ArgumentParser(
        description="Visualize normalized [y,x] coordinates (0-1000) on an image.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("image", help="path to the image")
    parser.add_argument(
        "--json", "-j",
        metavar="JSON",
        help='JSON array: \'[{"point": [y, x], "label": "name"}, ...]\''
    )
    parser.add_argument(
        "--point", "-p",
        metavar="Y,X",
        action="append",
        default=[],
        help="a single coordinate pair as y,x (repeatable)",
    )
    parser.add_argument(
        "--labels", "-l",
        metavar="LABEL",
        nargs="*",
        default=[],
        help="labels for --point args (in order); unlabeled points get auto-numbered",
    )
    parser.add_argument(
        "--title", "-t",
        default="",
        help="plot title",
    )
    args = parser.parse_args()

    if not Path(args.image).exists():
        print(f"!!! file not found: {args.image}")
        sys.exit(1)

    detections: list[dict] = []

    if args.json:
        try:
            data = json.loads(args.json)
            if not isinstance(data, list):
                data = [data]
            detections.extend(data)
        except json.JSONDecodeError as e:
            print(f"!!! invalid JSON: {e}")
            sys.exit(1)

    for i, pair in enumerate(args.point):
        try:
            y, x = [float(v) for v in pair.split(",")]
        except ValueError:
            print(f"!!! invalid coordinate '{pair}': expected y,x")
            sys.exit(1)
        label = args.labels[i] if i < len(args.labels) else f"point_{len(detections)}"
        detections.append({"point": [y, x], "label": label})

    if not detections:
        print("!!! no points provided. use --json or --point.")
        parser.print_help()
        sys.exit(1)

    plot_points(args.image, detections, title=args.title)


if __name__ == "__main__":
    main()
