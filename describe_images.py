#!/usr/bin/env python3
"""
Generate LLM-powered alt-text descriptions for every extracted image in the
parsed document collection, then rewrite the *_parsed.md files so that
``![Image](path)`` becomes ``![<description>](path)``.

This lets the text-only DocumentSearcher understand what each image depicts
and select the right reference images for keypoint localisation.

Usage:
    python describe_images.py                  # describe all docs
    python describe_images.py arduino_uno      # describe one doc
    python describe_images.py --dry-run        # preview without writing
"""

import argparse
import os
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from PIL import Image
from google import genai
from google.genai import types


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PARSED_DIR = Path(__file__).parent / "data" / "parsed"
MODEL = "gemini-2.5-flash"

DESCRIBE_PROMPT = """\
You are an expert technical documentation analyst.

Describe this image in 1-3 concise sentences for use as alt-text in a
technical document.  Focus on:
  - What TYPE of image it is (circuit schematic, PCB layout / board topology
    diagram, pin-mapping diagram, power tree / block diagram, photograph,
    mechanical drawing, timing diagram, table, etc.)
  - Which major components, ICs, connectors, or labels are visible
    (e.g. "U1 NCP1117 5V LDO regulator", "ATmega328P", "USB-B connector X2")
  - Any signal names, voltage rails, or net labels that are legible

Do NOT describe decorative elements or page furniture.
Return ONLY the description text, no quotes or markdown.
"""

# Tiny placeholder images from Docling (< 3 KB) are usually blank or icons.
# Skip them to save API calls.
MIN_IMAGE_SIZE_BYTES = 3000


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------


def describe_image(client: genai.Client, img_path: Path) -> str:
    """Send an image to Gemini and return a short alt-text description."""
    img = Image.open(img_path)

    response = client.models.generate_content(
        model=MODEL,
        contents=[DESCRIBE_PROMPT, img],
        config=types.GenerateContentConfig(
            temperature=0.2,
            max_output_tokens=300,
        ),
    )

    text = (response.text or "").strip()
    # Normalise to a single line (some models add newlines)
    text = " ".join(text.split())
    return text


def patch_markdown(md_path: Path, descriptions: dict[str, str]) -> str:
    """Replace ![Image](...) with ![<description>](...) in markdown text.

    ``descriptions`` maps the image reference path (as it appears in the
    markdown, e.g. ``arduino_uno_images/image_8.png``) to its description.
    """
    md_text = md_path.read_text(encoding="utf-8")

    def _replacer(m: re.Match) -> str:
        img_ref = m.group(1)
        desc = descriptions.get(img_ref)
        if desc:
            # Escape ] inside the alt-text so markdown stays valid
            safe_desc = desc.replace("]", "\\]")
            return f"![{safe_desc}]({img_ref})"
        return m.group(0)  # leave unchanged

    # Match ![anything](path) — the Docling output always uses ![Image](...)
    patched = re.sub(r"!\[[^\]]*\]\(([^)]+)\)", _replacer, md_text)
    return patched


def process_document(
    doc_name: str,
    client: genai.Client,
    *,
    dry_run: bool = False,
) -> dict[str, str]:
    """Describe all images for one parsed document and rewrite its markdown.

    Returns the descriptions dict {image_ref: description}.
    """
    images_dir = PARSED_DIR / f"{doc_name}_images"
    md_path = PARSED_DIR / f"{doc_name}_parsed.md"

    if not images_dir.exists():
        print(f"  [skip] no images directory for {doc_name}")
        return {}
    if not md_path.exists():
        print(f"  [skip] no markdown file for {doc_name}")
        return {}

    image_files = sorted(images_dir.glob("*.png"), key=lambda p: _sort_key(p.name))
    if not image_files:
        print(f"  [skip] no PNG images in {images_dir.name}/")
        return {}

    descriptions: dict[str, str] = {}

    for img_path in image_files:
        img_ref = f"{images_dir.name}/{img_path.name}"

        if img_path.stat().st_size < MIN_IMAGE_SIZE_BYTES:
            print(
                f"    {img_path.name:20s}  [skip — too small ({img_path.stat().st_size} B)]"
            )
            continue

        print(f"    {img_path.name:20s}  ", end="", flush=True)
        try:
            desc = describe_image(client, img_path)
            descriptions[img_ref] = desc
            # Truncate display for readability
            display = desc[:100] + ("…" if len(desc) > 100 else "")
            print(f"→ {display}")
        except Exception as e:
            print(f"[error] {e}")

        # Gentle rate-limit to stay within free-tier QPM
        time.sleep(0.5)

    if not descriptions:
        print(f"  [skip] no describable images for {doc_name}")
        return descriptions

    patched = patch_markdown(md_path, descriptions)

    if dry_run:
        print(
            f"\n  [dry-run] would rewrite {md_path.name} "
            f"({len(descriptions)} description(s))"
        )
    else:
        md_path.write_text(patched, encoding="utf-8")
        print(
            f"\n  ✓ rewrote {md_path.name} with {len(descriptions)} image description(s)"
        )

    return descriptions


def _sort_key(name: str) -> tuple[str, int]:
    """Sort image_1.png, image_2.png, … image_10.png numerically."""
    m = re.match(r"^(.*?)(\d+)\.png$", name)
    if m:
        return (m.group(1), int(m.group(2)))
    return (name, 0)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Generate VLM alt-text descriptions for parsed document images",
    )
    parser.add_argument(
        "docs",
        nargs="*",
        help="Document name(s) to process (e.g. 'arduino_uno'). "
        "Omit to process all documents.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview descriptions without rewriting markdown files.",
    )
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY not set. Add it to .env or environment.")
        sys.exit(1)

    client = genai.Client(api_key=api_key)

    # Discover documents
    if args.docs:
        doc_names = args.docs
    else:
        doc_names = sorted(
            set(d.stem.replace("_parsed", "") for d in PARSED_DIR.glob("*_parsed.md"))
        )

    if not doc_names:
        print(f"No parsed documents found in {PARSED_DIR}")
        sys.exit(1)

    print(f"Describing images for {len(doc_names)} document(s):\n")
    all_descriptions: dict[str, dict[str, str]] = {}

    for doc_name in doc_names:
        print(f"  [{doc_name}]")
        descs = process_document(doc_name, client, dry_run=args.dry_run)
        all_descriptions[doc_name] = descs
        print()

    total = sum(len(d) for d in all_descriptions.values())
    print(f"Done — {total} image(s) described across {len(doc_names)} document(s).")


if __name__ == "__main__":
    main()
