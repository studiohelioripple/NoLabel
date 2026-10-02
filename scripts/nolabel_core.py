#!/usr/bin/env python3
"""
NoLabel Core Dispatcher
Unified engine routing Keynote (.key), PowerPoint (.pptx), Images, and PDF documents
to their respective corner-label detectors, near-background color inpainters, and canvas healers.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional, Tuple

from process_image import process_image
from process_pdf import process_pdf
from process_pptx import process_pptx
from process_keynote import process_keynote

SUPPORTED_EXTENSIONS = {
    # Presentations
    ".key": "keynote",
    ".pptx": "pptx",
    # Documents
    ".pdf": "pdf",
    # Images
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".webp": "image",
    ".tiff": "image",
    ".tif": "image",
    ".bmp": "image",
}


def is_supported_file(file_path: Path) -> bool:
    """Checks if the given file has a supported extension."""
    return file_path.suffix.lower() in SUPPORTED_EXTENSIONS


def get_file_type(file_path: Path) -> Optional[str]:
    """Returns the category ('keynote', 'pptx', 'pdf', 'image') or None."""
    return SUPPORTED_EXTENSIONS.get(file_path.suffix.lower())


def process_file(
    input_path: Path,
    output_path: Optional[Path] = None,
    archive_dir: Optional[Path] = None,
    inpaint_radius: int = 3,
    method: str = "telea",
    verbose: bool = True
) -> bool:
    """
    Routes a file to the appropriate handler, optionally archiving the original.
    """
    input_path = Path(input_path).resolve()
    if not input_path.exists():
        if verbose:
            print(f"[!] Error: File not found {input_path}")
        return False

    ftype = get_file_type(input_path)
    if not ftype:
        if verbose:
            print(f"[-] Unsupported file format: {input_path.name}")
        return False

    if verbose:
        print(f"\n==========================================")
        print(f"[*] Processing [{ftype.upper()}]: {input_path.name}")
        print(f"==========================================")

    # If archive directory is specified, make a safe backup of the original first
    if archive_dir:
        archive_dir = Path(archive_dir).resolve()
        archive_dir.mkdir(parents=True, exist_ok=True)
        backup_target = archive_dir / input_path.name
        try:
            if input_path.is_dir():
                if backup_target.exists():
                    shutil.rmtree(backup_target)
                shutil.copytree(input_path, backup_target)
            else:
                shutil.copy2(input_path, backup_target)
            if verbose:
                print(f"  [+] Original archived to: {backup_target}")
        except Exception as e:
            if verbose:
                print(f"  [!] Warning: Could not archive original: {e}")

    success = False
    if ftype == "image":
        success = process_image(input_path, output_path, inpaint_radius, method, verbose)
    elif ftype == "pdf":
        success = process_pdf(input_path, output_path, dpi=150, inpaint_radius=inpaint_radius, method=method, verbose=verbose)
    elif ftype == "pptx":
        success = process_pptx(input_path, output_path, inpaint_radius, method, verbose)
    elif ftype == "keynote":
        success = process_keynote(input_path, output_path, inpaint_radius, method, verbose)

    return success
