#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "google-genai",
#   "pillow",
# ]
# ///
"""Find bounding box of letter N in an image using Gemini 3 Flash."""

import json
import sys
from pathlib import Path

import google.genai as genai
import google.genai.types as types
from PIL import Image, ImageDraw


def find_letter_n(image_path: str) -> dict:
    client = genai.Client()

    image_data = Path(image_path).read_bytes()

    prompt = """Find all occurrences of the letter 'N' (uppercase) in this image.
For each occurrence, return a bounding box.
Respond with JSON only, no explanation. Format:
{
  "occurrences": [
    {"y_min": <top>, "x_min": <left>, "y_max": <bottom>, "x_max": <right>, "confidence": <0-1>}
  ]
}
Coordinates are normalized in the range [0, 1000] where 1000 = full image width or height.
If no letter N is found, return {"occurrences": []}."""

    response = client.models.generate_content(
        model="gemini-3-flash-preview",
        contents=[
            types.Part.from_bytes(data=image_data, mime_type="image/jpeg"),
            prompt,
        ],
    )

    text = response.text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def draw_bounding_boxes(image_path: str, result: dict, output_path: str) -> None:
    img = Image.open(image_path).convert("RGB")
    w, h = img.size
    draw = ImageDraw.Draw(img)

    for occ in result.get("occurrences", []):
        # Gemini returns normalized [0-1000] coords in y_min/x_min/y_max/x_max order
        x1 = int(occ["x_min"] / 1000 * w)
        y1 = int(occ["y_min"] / 1000 * h)
        x2 = int(occ["x_max"] / 1000 * w)
        y2 = int(occ["y_max"] / 1000 * h)
        confidence = occ.get("confidence", 1.0)

        draw.rectangle([x1, y1, x2, y2], outline="red", width=3)
        label = f"N ({confidence:.2f})"
        draw.text((x1, max(0, y1 - 18)), label, fill="red")

    img.save(output_path)
    print(f"Annotated image saved to: {output_path}")


if __name__ == "__main__":
    image_path = sys.argv[1] if len(sys.argv) > 1 else "../test_image.jpg"
    output_path = sys.argv[2] if len(sys.argv) > 2 else "annotated_output.jpg"

    result = find_letter_n(image_path)
    print(json.dumps(result, indent=2))

    draw_bounding_boxes(image_path, result, output_path)
