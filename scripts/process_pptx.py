#!/usr/bin/env python3
"""
NoLabel PowerPoint (PPTX) Processor
Handles presentation slide decks (.pptx).
1. Inspects Slide 1 to detect bottom-right corner shapes, text frames, or embedded image watermarks.
2. Removes native shapes/badges and in-paints/heals rasterized watermarks in slide media.
3. Preserves all animations, typography, themes, and slide layouts.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from nolabel_detector import detect_corner_label
from nolabel_healer import heal_label_area
from process_image import get_xattrs, restore_xattrs


def process_pptx(
    input_path: Path,
    output_path: Optional[Path] = None,
    inpaint_radius: int = 3,
    method: str = "telea",
    verbose: bool = True
) -> bool:
    """
    Cleans bottom-right labels from all slides in a PowerPoint (.pptx) file.
    """
    input_path = Path(input_path).resolve()
    if output_path is None:
        output_path = input_path
    else:
        output_path = Path(output_path).resolve()

    if not input_path.exists():
        if verbose:
            print(f"[!] Error: PPTX not found {input_path}")
        return False

    try:
        prs = Presentation(str(input_path))
    except Exception as e:
        if verbose:
            print(f"[!] Error reading PPTX: {e}")
        return False

    sw = prs.slide_width
    sh = prs.slide_height
    total_slides = len(prs.slides)

    if total_slides == 0:
        return False

    if verbose:
        print(f"[*] Analyzing PPTX '{input_path.name}' ({total_slides} slides)...")

    # Step 1: Check Slide 1 for native bottom-right shapes / text boxes
    slide1 = prs.slides[0]
    native_br_found = False
    cleaned_shapes_count = 0

    for s_idx, slide in enumerate(prs.slides):
        shapes_to_remove = []
        for shape in list(slide.shapes):
            try:
                # Shape position in slide
                x = shape.left
                y = shape.top
                w = shape.width
                h = shape.height

                # Check if center of shape falls in bottom-right quadrant
                cx = (x + w / 2.0) / sw
                cy = (y + h / 2.0) / sh
                if cx >= 0.65 and cy >= 0.70:
                    txt = shape.text if shape.has_text_frame else ""
                    if s_idx == 0:
                        native_br_found = True
                        if verbose:
                            print(f"  [+] Found native shape in bottom-right on Slide 1: '{txt}'")
                    shapes_to_remove.append(shape)
            except Exception:
                continue

        for sp in shapes_to_remove:
            try:
                elem = sp._element
                elem.getparent().remove(elem)
                cleaned_shapes_count += 1
            except Exception:
                pass

    # Step 2: Check embedded media images (e.g. background images or slide pictures)
    cleaned_images_count = 0
    checked_part_names = set()

    for part in prs.part.package.iter_parts():
        part_name = str(part.partname)
        if "/media/" in part_name and part_name not in checked_part_names:
            checked_part_names.add(part_name)
            # Try to read image blob
            try:
                blob = part.blob
                nparr = np.frombuffer(blob, np.uint8)
                img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                if img is None:
                    continue

                # Run detector on media image
                det = detect_corner_label(img)
                if det.detected and det.box is not None:
                    if verbose:
                        print(f"  [+] Found watermark in slide media ({part_name}): {det.shape_type} at {det.box}")
                    healed = heal_label_area(
                        img=img,
                        box=det.box,
                        shape_type=det.shape_type,
                        corner_radius=det.corner_radius,
                        inpaint_radius=inpaint_radius,
                        method=method
                    )
                    # Determine extension
                    ext = Path(part_name).suffix.lower()
                    if ext in [".jpg", ".jpeg"]:
                        _, encoded = cv2.imencode(".jpg", healed, [cv2.IMWRITE_JPEG_QUALITY, 96])
                    else:
                        _, encoded = cv2.imencode(".png", healed, [cv2.IMWRITE_PNG_COMPRESSION, 3])

                    part._blob = encoded.tobytes()
                    cleaned_images_count += 1
            except Exception:
                continue

    xattrs = get_xattrs(input_path)

    # Save output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(output_path))

    if xattrs:
        restore_xattrs(output_path, xattrs)

    if verbose:
        print(
            f"  [✓] Successfully processed {output_path.name}: "
            f"removed {cleaned_shapes_count} native shapes, healed {cleaned_images_count} media images."
        )

    return True


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: process_pptx.py <input_pptx> [output_pptx]")
        sys.exit(1)

    inp = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    process_pptx(inp, out)
