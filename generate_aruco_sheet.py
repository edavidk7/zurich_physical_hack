"""
Generate a printable A4 sheet of uniquely numbered ArUco markers.

Each marker has a 1.8 cm side length with a small gap between them.
Output: aruco_sheet.png (300 DPI, A4 dimensions)
"""

import cv2
import numpy as np

# --- Configuration ---
DPI = 300
MARKER_SIZE_CM = 1.8
GAP_CM = 0.45  # gap between markers
MARGIN_CM = 1.5  # page margin

# A4 dimensions in cm
PAGE_WIDTH_CM = 21.0
PAGE_HEIGHT_CM = 29.7

# ArUco dictionary – 4x4 with 250 unique IDs (small, fast to detect)
ARUCO_DICT = cv2.aruco.DICT_4X4_250


# --- Helpers ---
def cm_to_px(cm: float) -> int:
    return int(round(cm / 2.54 * DPI))


def main():
    marker_px = cm_to_px(MARKER_SIZE_CM)
    gap_px = cm_to_px(GAP_CM)
    margin_px = cm_to_px(MARGIN_CM)

    page_w = cm_to_px(PAGE_WIDTH_CM)
    page_h = cm_to_px(PAGE_HEIGHT_CM)

    # Usable area
    usable_w = page_w - 2 * margin_px
    usable_h = page_h - 2 * margin_px

    cols = (usable_w + gap_px) // (marker_px + gap_px)
    rows = (usable_h + gap_px) // (marker_px + gap_px)

    total_markers = rows * cols
    print(
        f"Page : {PAGE_WIDTH_CM} x {PAGE_HEIGHT_CM} cm  ({page_w} x {page_h} px @ {DPI} DPI)"
    )
    print(
        f"Marker: {MARKER_SIZE_CM} cm  ({marker_px} px),  gap: {GAP_CM} cm  ({gap_px} px)"
    )
    print(f"Grid  : {cols} cols x {rows} rows = {total_markers} markers")

    # White page
    page = 255 * np.ones((page_h, page_w), dtype=np.uint8)

    aruco_dict = cv2.aruco.getPredefinedDictionary(ARUCO_DICT)

    # Center the grid on the page
    grid_w = cols * marker_px + (cols - 1) * gap_px
    grid_h = rows * marker_px + (rows - 1) * gap_px
    x_offset = (page_w - grid_w) // 2
    y_offset = (page_h - grid_h) // 2

    marker_id = 0
    for row in range(rows):
        for col in range(cols):
            # Generate marker image
            marker_img = cv2.aruco.generateImageMarker(aruco_dict, marker_id, marker_px)

            x = x_offset + col * (marker_px + gap_px)
            y = y_offset + row * (marker_px + gap_px)

            page[y : y + marker_px, x : x + marker_px] = marker_img
            marker_id += 1

    out_path = "aruco_sheet.png"
    cv2.imwrite(out_path, page)
    print(f"\nSaved to {out_path}")
    print(f"Print at {DPI} DPI for accurate {MARKER_SIZE_CM} cm markers.")


if __name__ == "__main__":
    main()
