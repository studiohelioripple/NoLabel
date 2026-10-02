#!/usr/bin/env python3
"""
NoLabel Image Processor
Processes single image files (.png, .jpg, .jpeg, .webp, .tiff, .bmp).
Detects bottom-right label, removes with near-background color, and heals the area.
Preserves macOS Finder tags, extended attributes, and metadata.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np

from nolabel_detector import detect_corner_label
from nolabel_healer import heal_label_area


def get_xattrs(file_path: Path) -> dict[str, str]:
    """Retrieves all extended attributes (Finder tags, color profiles, etc.)."""
    attrs = {}
    try:
        names = subprocess.check_output(
            ["xattr", str(file_path)], stderr=subprocess.DEVNULL
        ).decode("utf-8").splitlines()
        for name in names:
            name = name.strip()
            if name:
                try:
                    val = subprocess.check_output(
                        ["xattr", "-px", name, str(file_path)], stderr=subprocess.DEVNULL
                    ).decode("utf-8").replace("\n", "").replace(" ", "")
                    attrs[name] = val
                except Exception:
                    pass
    except Exception:
        pass
    return attrs


def restore_xattrs(file_path: Path, attrs: dict[str, str]) -> None:
    """Restores extended attributes to the processed output file."""
    for name, hex_val in attrs.items():
        try:
            subprocess.run(
                ["xattr", "-wx", name, hex_val, str(file_path)], stderr=subprocess.DEVNULL
            )
        except Exception:
            pass


def process_image(
    input_path: Path,
    output_path: Optional[Path] = None,
    inpaint_radius: int = 3,
    method: str = "telea",
    verbose: bool = True
) -> bool:
    """
    Cleans bottom-right corner label from an image and heals the canvas.
    """
    input_path = Path(input_path).resolve()
    if output_path is None:
        output_path = input_path
    else:
        output_path = Path(output_path).resolve()

    if not input_path.exists():
        if verbose:
            print(f"[!] Error: File not found {input_path}")
        return False

    img = cv2.imread(str(input_path))
    if img is None:
        if verbose:
            print(f"[!] Error: Could not read image {input_path}")
        return False

    # 1. First detect the label in bottom-right corner
    det = detect_corner_label(img)
    if not det.detected or det.box is None:
        if verbose:
            print(f"  [-] No bottom-right label found on {input_path.name}. Preserved pristine.")
        # Copy original if output is different
        if input_path != output_path:
            import shutil
            shutil.copy2(input_path, output_path)
        return True

    if verbose:
        print(f"  [+] Detected label on {input_path.name}: {det.shape_type} at {det.box} (text: '{det.text}')")

    # 2. Remove with near-background color then heal the area
    healed = heal_label_area(
        img=img,
        box=det.box,
        shape_type=det.shape_type,
        corner_radius=det.corner_radius,
        inpaint_radius=inpaint_radius,
        method=method
    )

    # Save xattrs from original
    xattrs = get_xattrs(input_path)

    # Write output image
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ext = output_path.suffix.lower()
    if ext in [".jpg", ".jpeg"]:
        cv2.imwrite(str(output_path), healed, [cv2.IMWRITE_JPEG_QUALITY, 98])
    elif ext == ".png":
        cv2.imwrite(str(output_path), healed, [cv2.IMWRITE_PNG_COMPRESSION, 3])
    else:
        cv2.imwrite(str(output_path), healed)

    # Restore macOS Finder tags and metadata
    if xattrs:
        restore_xattrs(output_path, xattrs)

    if verbose:
        print(f"  [✓] Successfully removed label & healed: {output_path.name}")

    return True


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: process_image.py <input_image> [output_image]")
        sys.exit(1)

    inp = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    process_image(inp, out)
