#!/usr/bin/env python3
"""
NoLabel Apple Keynote (.key) Processor
Automates Apple Keynote on macOS to clean corner labels and watermarks.
1. Inspects Slide 1 to detect native shapes/badges or rasterized watermarks in bottom-right corner.
2. Deletes native badge shapes and in-paints/heals rasterized slide backgrounds.
3. Re-injects healed visuals and saves the presentation in-place or to output.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import cv2

from nolabel_detector import detect_corner_label
from nolabel_healer import heal_label_area
from process_image import get_xattrs, restore_xattrs


def run_osascript(script: str) -> str:
    res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"AppleScript error: {res.stderr.strip()}")
    return res.stdout.strip()


def process_keynote(
    input_path: Path,
    output_path: Optional[Path] = None,
    inpaint_radius: int = 3,
    method: str = "telea",
    verbose: bool = True
) -> bool:
    """
    Cleans bottom-right labels from all slides in an Apple Keynote (.key) document.
    """
    input_path = Path(input_path).resolve()
    if output_path is None:
        output_path = input_path
    else:
        output_path = Path(output_path).resolve()

    if not input_path.exists():
        if verbose:
            print(f"[!] Error: Keynote file not found {input_path}")
        return False

    # Check Keynote availability
    if not (os.path.exists("/Applications/Keynote.app") or os.path.exists("/System/Applications/Keynote.app")):
        if verbose:
            print("[!] Error: Apple Keynote.app is not installed.")
        return False

    # If output is different from input, copy original to output location first
    if input_path != output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if input_path.is_dir():
            if output_path.exists():
                shutil.rmtree(output_path)
            shutil.copytree(input_path, output_path)
        else:
            shutil.copy2(input_path, output_path)

    target_file = output_path
    xattrs = get_xattrs(input_path)

    with tempfile.TemporaryDirectory(prefix="nolabel_key_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        export_dir = tmp_path / "slides_export"
        export_dir.mkdir(parents=True, exist_ok=True)

        # 1. Open document in Keynote, query slide dimensions, count, and export slide images
        as_open_and_export = f"""
        tell application "Keynote"
            set doc to open POSIX file "{target_file.resolve()}"
            tell doc
                set sw to width
                set sh to height
                set totalSlides to count of slides
                export to POSIX file "{export_dir.resolve()}" as slide images with properties {{image format:PNG}}
            end tell
            return (sw as text) & "|" & (sh as text) & "|" & (totalSlides as text)
        end tell
        """

        try:
            out = run_osascript(as_open_and_export)
            parts = out.split("|")
            canvas_w = float(parts[0])
            canvas_h = float(parts[1])
            total_slides = int(parts[2])
        except Exception as e:
            if verbose:
                print(f"[!] Error inspecting Keynote deck: {e}")
            return False

        if verbose:
            print(f"[*] Analyzing Keynote deck '{input_path.name}' ({total_slides} slides, {int(canvas_w)}x{int(canvas_h)})...")

        exported_images = sorted(list(export_dir.glob("*.png")))
        if not exported_images:
            # Close Keynote document
            run_osascript('tell application "Keynote" to close front document saving no')
            return False

        # Step 2: Detect label on the first slide image
        first_img = cv2.imread(str(exported_images[0]))
        baseline_det = detect_corner_label(first_img) if first_img is not None else None

        has_raster_watermark = baseline_det is not None and baseline_det.detected and baseline_det.box is not None

        # Step 3: Clean Keynote presentation via AppleScript
        # First, remove any native bottom-right shapes or text items
        as_clean_native = f"""
        tell application "Keynote"
            tell front document
                set cleanedNative to 0
                repeat with sIdx from 1 to {total_slides}
                    tell slide sIdx
                        -- Remove shapes in bottom-right zone
                        set sc to count of shapes
                        repeat with i from sc to 1 by -1
                            set shp to shape i
                            set p to position of shp
                            set px to item 1 of p
                            set py to item 2 of p
                            if px >= ({canvas_w} * 0.65) and py >= ({canvas_h} * 0.70) then
                                delete shp
                                set cleanedNative to cleanedNative + 1
                            end if
                        end repeat
                        
                        -- Remove text items in bottom-right zone
                        set tc to count of text items
                        repeat with i from tc to 1 by -1
                            set ti to text item i
                            set p to position of ti
                            set px to item 1 of p
                            set py to item 2 of p
                            if px >= ({canvas_w} * 0.65) and py >= ({canvas_h} * 0.70) then
                                delete ti
                                set cleanedNative to cleanedNative + 1
                            end if
                        end repeat
                    end tell
                end repeat
                return cleanedNative
            end tell
        end tell
        """

        try:
            num_native_removed = int(run_osascript(as_clean_native))
        except Exception:
            num_native_removed = 0

        # Step 4: If raster watermark exists, heal exported slide images and re-inject
        num_healed_slides = 0
        if has_raster_watermark:
            if verbose:
                print(
                    f"  [+] Found rasterized label on Slide 1: {baseline_det.shape_type} at {baseline_det.box} "
                    f"(text: '{baseline_det.text}'). Inpainting slides..."
                )

            nx, ny, nw, nh = baseline_det.norm_box
            for s_idx, img_file in enumerate(exported_images, start=1):
                s_img = cv2.imread(str(img_file))
                if s_img is None:
                    continue

                ih, iw = s_img.shape[:2]
                box = (int(nx * iw), int(ny * ih), int(nw * iw), int(nh * ih))

                healed_img = heal_label_area(
                    img=s_img,
                    box=box,
                    shape_type=baseline_det.shape_type,
                    corner_radius=baseline_det.corner_radius,
                    inpaint_radius=inpaint_radius,
                    method=method
                )

                healed_file = tmp_path / f"slide_{s_idx:02d}_healed.png"
                cv2.imwrite(str(healed_file), healed_img, [cv2.IMWRITE_PNG_COMPRESSION, 3])

                # Re-inject healed background into slide
                as_reinject = f"""
                tell application "Keynote"
                    tell front document
                        tell slide {s_idx}
                            if (count of images) > 0 then
                                delete image 1
                            end if
                            set newBg to make new image with properties {{file:POSIX file "{healed_file.resolve()}"}}
                            set width of newBg to {canvas_w}
                            set height of newBg to {canvas_h}
                            set position of newBg to {{0, 0}}
                        end tell
                    end tell
                end tell
                """
                try:
                    run_osascript(as_reinject)
                    num_healed_slides += 1
                except Exception as e:
                    if verbose:
                        print(f"  [!] Re-inject error on slide {s_idx}: {e}")

        # Step 5: Save and close Keynote document
        as_save_close = """
        tell application "Keynote"
            tell front document
                save
                close saving yes
            end tell
        end tell
        """
        try:
            run_osascript(as_save_close)
        except Exception:
            pass

    if xattrs:
        restore_xattrs(output_path, xattrs)

    if verbose:
        print(
            f"  [✓] Successfully processed Keynote presentation {output_path.name}: "
            f"removed {num_native_removed} native shapes, healed {num_healed_slides} slides."
        )

    return True


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: process_keynote.py <input_keynote> [output_keynote]")
        sys.exit(1)

    inp = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    process_keynote(inp, out)
