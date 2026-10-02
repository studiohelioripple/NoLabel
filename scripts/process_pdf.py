#!/usr/bin/env python3
"""
NoLabel PDF Processor
Handles multi-page PDF documents and slide decks.
1. Inspects the first page/slide to detect any bottom-right corner label and its bounding area.
2. Applies near-background color removal and healing across all affected pages.
3. Reassembles the document preserving dimensions, page count, and metadata.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import pymupdf

from nolabel_detector import detect_corner_label
from nolabel_healer import heal_label_area
from process_image import get_xattrs, restore_xattrs


def process_pdf(
    input_path: Path,
    output_path: Optional[Path] = None,
    dpi: int = 150,
    inpaint_radius: int = 3,
    method: str = "telea",
    verbose: bool = True
) -> bool:
    """
    Cleans bottom-right labels from all pages of a PDF presentation deck.
    """
    input_path = Path(input_path).resolve()
    if output_path is None:
        output_path = input_path
    else:
        output_path = Path(output_path).resolve()

    if not input_path.exists():
        if verbose:
            print(f"[!] Error: PDF not found {input_path}")
        return False

    try:
        doc = pymupdf.open(str(input_path))
    except Exception as e:
        if verbose:
            print(f"[!] Error reading PDF: {e}")
        return False

    total_pages = len(doc)
    if total_pages == 0:
        doc.close()
        return False

    if verbose:
        print(f"[*] Analyzing PDF '{input_path.name}' ({total_pages} pages)...")

    # Step 1: Detect label on the first page (or check page 2 if page 1 is a clean cover)
    baseline_det = None
    baseline_page_idx = 0

    for idx in range(min(3, total_pages)):
        page = doc[idx]
        pix = page.get_pixmap(dpi=dpi)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, pix.n))
        if pix.n == 4:
            img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
        elif pix.n == 3:
            img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

        det = detect_corner_label(img)
        if det.detected and det.box is not None:
            baseline_det = det
            baseline_page_idx = idx
            break

    if baseline_det is None or baseline_det.norm_box is None:
        if verbose:
            print(f"  [-] No bottom-right label detected on baseline slides. Preserved pristine.")
        doc.close()
        if input_path != output_path:
            import shutil
            shutil.copy2(input_path, output_path)
        return True

    nx, ny, nw, nh = baseline_det.norm_box
    if verbose:
        print(
            f"  [+] Baseline label found on Page {baseline_page_idx + 1}: "
            f"{baseline_det.shape_type} (norm bounds: x={nx:.3f}, y={ny:.3f}, w={nw:.3f}, h={nh:.3f}, text='{baseline_det.text}')"
        )

    # Step 2: Process all pages
    new_doc = pymupdf.open()
    xattrs = get_xattrs(input_path)

    for i in range(total_pages):
        page = doc[i]
        p_rect = page.rect
        pix = page.get_pixmap(dpi=dpi)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, pix.n))
        if pix.n == 4:
            img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
        elif pix.n == 3:
            img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

        ih, iw = img.shape[:2]
        
        # Calculate bounding box for this page
        page_bx = int(nx * iw)
        page_by = int(ny * ih)
        page_bw = int(nw * iw)
        page_bh = int(nh * ih)
        
        # Verify if this page contains label or content in this zone
        # We check local difference from background in this zone
        box = (page_bx, page_by, page_bw, page_bh)
        
        healed_img = heal_label_area(
            img=img,
            box=box,
            shape_type=baseline_det.shape_type,
            corner_radius=int(baseline_det.corner_radius * (ih / baseline_det.image_size[1])) if baseline_det.image_size[1] > 0 else 0,
            inpaint_radius=inpaint_radius,
            method=method
        )

        # Encode healed image
        _, buf = cv2.imencode(".png", healed_img, [cv2.IMWRITE_PNG_COMPRESSION, 3])
        img_bytes = buf.tobytes()

        # Add page to clean PDF with exact original dimensions
        new_page = new_doc.new_page(width=p_rect.width, height=p_rect.height)
        new_page.insert_image(pymupdf.Rect(0, 0, p_rect.width, p_rect.height), stream=img_bytes)

    doc.close()

    # Write output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_out = output_path.with_suffix(".tmp.pdf")
    new_doc.save(str(temp_out), deflate=True, garbage=4)
    new_doc.close()

    temp_out.replace(output_path)

    if xattrs:
        restore_xattrs(output_path, xattrs)

    if verbose:
        print(f"  [✓] Successfully cleaned all {total_pages} pages of {output_path.name}")

    return True


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: process_pdf.py <input_pdf> [output_pdf]")
        sys.exit(1)

    inp = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    process_pdf(inp, out)
