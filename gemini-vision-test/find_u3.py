#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "google-genai",
#   "pillow",
# ]
# ///
"""Find and highlight GND ports in an Arduino board image using Gemini 3 Flash,
with Arduino datasheets as context."""

import json
import sys
from pathlib import Path

import google.genai as genai
import google.genai.types as types
from PIL import Image, ImageDraw


def upload_pdf(client: genai.Client, pdf_path: str):
    print(f"Uploading {pdf_path}...")
    uploaded = client.files.upload(file=pdf_path)
    print(f"  -> {uploaded.name}")
    return uploaded


def find_gnd_ports(image_path: str, pdf_paths: list[str]) -> dict:
    client = genai.Client()

    image_data = Path(image_path).read_bytes()

    # Upload PDFs via Files API so they're available as context
    pdf_parts = []
    for pdf_path in pdf_paths:
        uploaded = upload_pdf(client, pdf_path)
        pdf_parts.append(types.Part.from_uri(file_uri=uploaded.uri, mime_type="application/pdf"))

    prompt = """You have been given Arduino documentation PDFs and a photo of an Arduino board.
Using the documentation as reference, locate all GND (ground) ports/pins on the board in the image.

Respond with JSON only, no explanation. Format:
{
  "occurrences": [
    {"y_min": <top>, "x_min": <left>, "y_max": <bottom>, "x_max": <right>, "label": "GND"}
  ]
}
Coordinates are normalized in the range [0, 1000] where 1000 = full image width or height.
If no GND ports are visible, return {"occurrences": []}."""

    contents = [
        *pdf_parts,
        types.Part.from_bytes(data=image_data, mime_type="image/jpeg"),
        prompt,
    ]

    response = client.models.generate_content(
        model="gemini-3-flash-preview",
        contents=contents,
    )

    text = response.text.strip()
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
        x1 = int(occ["x_min"] / 1000 * w)
        y1 = int(occ["y_min"] / 1000 * h)
        x2 = int(occ["x_max"] / 1000 * w)
        y2 = int(occ["y_max"] / 1000 * h)
        label = occ.get("label", "GND")

        draw.rectangle([x1, y1, x2, y2], outline="red", width=3)
        draw.text((x1, max(0, y1 - 18)), label, fill="red")

    img.save(output_path)
    print(f"Annotated image saved to: {output_path}")


if __name__ == "__main__":
    image_path = sys.argv[1] if len(sys.argv) > 1 else "../test_image.jpg"
    output_path = sys.argv[2] if len(sys.argv) > 2 else "annotated_gnd.jpg"

    pdf_paths = [
        "../data/arduino/arduino.pdf",
        "../data/arduino/arduino2.pdf",
    ]

    result = find_gnd_ports(image_path, pdf_paths)
    print(json.dumps(result, indent=2))

    draw_bounding_boxes(image_path, result, output_path)
