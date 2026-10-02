#!/usr/bin/env python3
"""
NoLabel Precision Corner Label & Watermark Detector
---------------------------------------------------
Implements text-first anchored detection in the bottom-right corner:
1. Identifies corner label text (e.g. "Gemini Notebook", "NotebookLM", "Google", watermarks).
2. Detects adjacent icons (e.g. Gemini 4-pointed sparkle, logo glyphs) immediately beside text.
3. Analyzes tight container geometry (rounded rectangle pill badge vs flat rectangle).
4. Strictly confines bounding area to avoid touching any neighboring slide cards or text.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import cv2
import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
VISION_BIN = PROJECT_DIR / "bin" / "nolabel_vision"
VISION_SWIFT = SCRIPT_DIR / "nolabel_vision.swift"

WATERMARK_KEYWORDS = [
    "gemini", "notebook", "notebooklm", "google", "watermark",
    "confidential", "draft", "gamma", "canva", "made with", "preview"
]


class LabelDetectionResult:
    def __init__(
        self,
        detected: bool,
        box: Optional[Tuple[int, int, int, int]] = None,
        norm_box: Optional[Tuple[float, float, float, float]] = None,
        shape_type: str = "rectangle",
        corner_radius: int = 0,
        text: str = "",
        has_icon: bool = False,
        confidence: float = 0.0,
        image_size: Tuple[int, int] = (0, 0),
        raw_info: Optional[Dict[str, Any]] = None,
    ):
        self.detected = detected
        self.box = box  # (x, y, w, h)
        self.norm_box = norm_box  # (nx, ny, nw, nh)
        self.shape_type = shape_type  # 'rectangle' or 'rounded_rectangle'
        self.corner_radius = corner_radius
        self.text = text
        self.has_icon = has_icon
        self.confidence = confidence
        self.image_size = image_size
        self.raw_info = raw_info or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "detected": self.detected,
            "box": list(self.box) if self.box else None,
            "norm_box": [round(v, 4) for v in self.norm_box] if self.norm_box else None,
            "shape_type": self.shape_type,
            "corner_radius": self.corner_radius,
            "text": self.text,
            "has_icon": self.has_icon,
            "confidence": round(self.confidence, 3),
            "image_size": list(self.image_size),
        }

    def __repr__(self) -> str:
        if not self.detected:
            return "<LabelDetectionResult: No Label Detected>"
        return (
            f"<LabelDetectionResult: {self.shape_type.upper()} at {self.box} "
            f"(text='{self.text}', icon={self.has_icon}, radius={self.corner_radius}px)>"
        )


def run_apple_vision(image_path: Union[str, Path]) -> Optional[Dict[str, Any]]:
    """Runs Apple Vision Swift tool to obtain OCR and rectangle observations."""
    cmd = []
    if VISION_BIN.exists() and os.access(VISION_BIN, os.X_OK):
        cmd = [str(VISION_BIN), "--json", str(image_path)]
    elif VISION_SWIFT.exists():
        cmd = ["swift", str(VISION_SWIFT), "--json", str(image_path)]
    else:
        return None

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return json.loads(res.stdout)
    except Exception:
        return None


def detect_icon_adjacent_to_text(
    img: np.ndarray,
    text_box: Tuple[int, int, int, int]
) -> Tuple[Tuple[int, int, int, int], bool]:
    """
    Scans immediate left and right margins beside text to detect adjacent icons
    (e.g., Gemini 4-pointed sparkle, Notebook star, logo glyph).
    """
    tx, ty, tw, th = text_box
    H, W = img.shape[:2]

    # 1. Check LEFT strip: up to 2.8 * th wide (where sparkle usually sits)
    strip_w = max(24, int(2.8 * th))
    left_x1 = max(0, tx - strip_w)
    left_x2 = tx
    left_y1 = max(0, ty - 6)
    left_y2 = min(H, ty + th + 6)

    left_strip = img[left_y1:left_y2, left_x1:left_x2]
    found_icon = False
    icon_box = None

    if left_strip.size > 0:
        gray = cv2.cvtColor(left_strip, cv2.COLOR_BGR2GRAY)
        bg = np.median(left_strip[0, :])
        diff = np.abs(gray.astype(float) - bg)
        thresh = (diff > 16).astype(np.uint8) * 255
        pts = cv2.findNonZero(thresh)
        if pts is not None and len(pts) >= 12:
            ix, iy, iw, ih = cv2.boundingRect(pts)
            full_ix = left_x1 + ix
            full_iy = left_y1 + iy
            icon_box = (full_ix, full_iy, iw, ih)
            found_icon = True

    # 2. Check RIGHT strip if not found on left
    if not found_icon:
        right_x1 = min(W, tx + tw)
        right_x2 = min(W, tx + tw + int(2.0 * th))
        right_strip = img[left_y1:left_y2, right_x1:right_x2]
        if right_strip.size > 0:
            gray = cv2.cvtColor(right_strip, cv2.COLOR_BGR2GRAY)
            bg = np.median(right_strip[0, :])
            diff = np.abs(gray.astype(float) - bg)
            thresh = (diff > 16).astype(np.uint8) * 255
            pts = cv2.findNonZero(thresh)
            if pts is not None and len(pts) >= 12:
                ix, iy, iw, ih = cv2.boundingRect(pts)
                full_ix = right_x1 + ix
                full_iy = left_y1 + iy
                icon_box = (full_ix, full_iy, iw, ih)
                found_icon = True

    if found_icon and icon_box is not None:
        new_x = min(tx, icon_box[0])
        new_y = min(ty, icon_box[1])
        new_x2 = max(tx + tw, icon_box[0] + icon_box[2])
        new_y2 = max(ty + th, icon_box[1] + icon_box[3])
        return (new_x, new_y, new_x2 - new_x, new_y2 - new_y), True

    return text_box, False


def detect_tight_container(
    img: np.ndarray,
    core_box: Tuple[int, int, int, int]
) -> Tuple[Optional[Tuple[int, int, int, int]], str, int]:
    """
    Checks if the core (text + icon) is enclosed inside a tight container
    (pill / rounded rectangle or flat rectangle badge).
    """
    H, W = img.shape[:2]
    cx_core, cy_core, cw_core, ch_core = core_box

    # Search window around the core box: scale relative to core box height
    pad_search_w = max(40, int(2.2 * ch_core))
    pad_search_h = max(24, int(1.4 * ch_core))
    sx1 = max(0, cx_core - pad_search_w)
    sy1 = max(0, cy_core - pad_search_h)
    sx2 = min(W, cx_core + cw_core + pad_search_w)
    sy2 = min(H, cy_core + ch_core + pad_search_h)

    roi = img[sy1:sy2, sx1:sx2]
    if roi.size == 0:
        return None, "rectangle", 0

    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    border = np.concatenate([gray[0, :], gray[-1, :], gray[:, 0], gray[:, -1]])
    bg_val = np.median(border)
    diff = np.abs(gray.astype(float) - bg_val)
    thresh = (diff > 18).astype(np.uint8) * 255

    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    rx = cx_core - sx1
    ry = cy_core - sy1
    rw = cw_core
    rh = ch_core

    margin_x = max(8, int(0.30 * ch_core))
    margin_y = max(6, int(0.25 * ch_core))
    max_extra_w = max(50, int(2.5 * ch_core))
    max_extra_h = max(35, int(1.8 * ch_core))

    for c in contours:
        cx, cy, cw, ch = cv2.boundingRect(c)
        # Must tightly enclose the core box
        if (cx <= rx + margin_x) and (cx + cw >= rx + rw - margin_x) and \
           (cy <= ry + margin_y) and (cy + ch >= ry + rh - margin_y):
            # Strict maximum size constraint: cannot be a huge slide section
            if cw <= rw + max_extra_w and ch <= rh + max_extra_h:
                area = cv2.contourArea(c)
                extent = area / (cw * ch)
                container_box = (sx1 + cx, sy1 + cy, cw, ch)
                if 0.76 <= extent <= 0.94:
                    shape_type = "rounded_rectangle"
                    corner_radius = int(ch * 0.45)
                else:
                    shape_type = "rectangle"
                    corner_radius = 0
                return container_box, shape_type, corner_radius

    return None, "rectangle", 0


def detect_corner_label(
    image: Union[str, Path, np.ndarray],
    min_x_norm: float = 0.60,
    min_y_norm: float = 0.65
) -> LabelDetectionResult:
    """
    Precision Corner Label Detector:
    1. Text-First: Locates text in the bottom-right quadrant.
    2. Icon-Adjacent: Detects small icon (e.g. Gemini sparkle) beside the text.
    3. Container: Identifies rounded rectangle pill badge or naked label.
    """
    temp_saved_path = None
    if isinstance(image, (str, Path)):
        img_path = Path(image)
        img_cv = cv2.imread(str(img_path))
        if img_cv is None:
            return LabelDetectionResult(detected=False)
    else:
        img_cv = image
        import tempfile
        tfile = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        cv2.imwrite(tfile.name, img_cv)
        img_path = Path(tfile.name)
        temp_saved_path = img_path

    try:
        ih, iw = img_cv.shape[:2]

        # 1. Run Apple Vision
        vision_res = run_apple_vision(img_path)
        if not vision_res:
            return LabelDetectionResult(detected=False, image_size=(iw, ih))

        # 2. Text-First: Find candidate watermark texts in bottom-right corner
        br_candidates = []
        for td in vision_res.get("texts", []):
            b = td["box"]
            norm_x = b["normX"]
            norm_y = b["normY"]
            norm_w = b["normWidth"]
            norm_h = b["normHeight"]
            txt = td["text"].strip()
            txt_lower = txt.lower()

            # Must be in bottom-right zone and not large body paragraphs
            if norm_x >= min_x_norm and norm_y >= min_y_norm and norm_h <= 0.08 and norm_w <= 0.35:
                score = 1.0
                if any(k in txt_lower for k in WATERMARK_KEYWORDS):
                    score += 15.0
                # Corner proximity bonus
                score += (norm_x - min_x_norm) * 6.0 + (norm_y - min_y_norm) * 6.0
                br_candidates.append((score, b, txt))

        # If text is found in bottom-right corner:
        if br_candidates:
            br_candidates.sort(key=lambda x: x[0], reverse=True)
            _, best_b, detected_text = br_candidates[0]

            tb = (best_b["x"], best_b["y"], best_b["width"], best_b["height"])

            # Detect icon adjacent to text (e.g. Gemini 4-pointed sparkle)
            core_box, has_icon = detect_icon_adjacent_to_text(img_cv, tb)

            # If keyword is Gemini/Notebook and icon was faint, guarantee sparkle clearance
            txt_l = detected_text.lower()
            if not has_icon and any(k in txt_l for k in ["gemini", "notebook"]):
                pad_spk = int(1.3 * tb[3])
                cx = max(0, core_box[0] - pad_spk)
                cw = core_box[2] + pad_spk
                core_box = (cx, core_box[1], cw, core_box[3])
                has_icon = True

            # Detect tight container (pill / rounded rectangle)
            container_box, shape_type, corner_radius = detect_tight_container(img_cv, core_box)

            if container_box is not None:
                final_box = container_box
            else:
                # Naked text + icon sitting directly on canvas
                pad_tight = 4
                nx1 = max(0, core_box[0] - pad_tight)
                ny1 = max(0, core_box[1] - pad_tight)
                nx2 = min(iw, core_box[0] + core_box[2] + pad_tight)
                ny2 = min(ih, core_box[1] + core_box[3] + pad_tight)
                final_box = (nx1, ny1, nx2 - nx1, ny2 - ny1)
                shape_type = "rounded_rectangle" if has_icon else "rectangle"
                corner_radius = 4 if has_icon else 0

            norm_box = (
                final_box[0] / iw,
                final_box[1] / ih,
                final_box[2] / iw,
                final_box[3] / ih
            )

            return LabelDetectionResult(
                detected=True,
                box=final_box,
                norm_box=norm_box,
                shape_type=shape_type,
                corner_radius=corner_radius,
                text=detected_text,
                has_icon=has_icon,
                confidence=0.98,
                image_size=(iw, ih),
                raw_info=vision_res
            )

        # 3. Fallback: Only if NO text was detected, check for extreme corner compact graphic badge
        # (Strictly confined to extreme corner: x >= 0.86, y >= 0.86, small area <= 0.035 * canvas)
        extreme_rx1 = int(iw * 0.85)
        extreme_ry1 = int(ih * 0.85)
        extreme_roi = img_cv[extreme_ry1:ih, extreme_rx1:iw]
        if extreme_roi.size > 0:
            gray = cv2.cvtColor(extreme_roi, cv2.COLOR_BGR2GRAY)
            bg = np.median(gray[0, :])
            diff = np.abs(gray.astype(float) - bg)
            thresh = (diff > 20).astype(np.uint8) * 255
            contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for c in contours:
                area = cv2.contourArea(c)
                if 250 <= area <= (iw * ih * 0.035):
                    bx, by, bw, bh = cv2.boundingRect(c)
                    extent = area / (bw * bh)
                    if extent >= 0.80 and bw <= iw * 0.15 and bh <= ih * 0.08:
                        full_box = (extreme_rx1 + bx, extreme_ry1 + by, bw, bh)
                        norm_box = (full_box[0] / iw, full_box[1] / ih, full_box[2] / iw, full_box[3] / ih)
                        shape_type = "rounded_rectangle" if extent <= 0.94 else "rectangle"
                        return LabelDetectionResult(
                            detected=True,
                            box=full_box,
                            norm_box=norm_box,
                            shape_type=shape_type,
                            corner_radius=int(bh * 0.45) if shape_type == "rounded_rectangle" else 0,
                            text="Graphic Badge",
                            has_icon=True,
                            confidence=0.85,
                            image_size=(iw, ih),
                            raw_info=vision_res
                        )

        return LabelDetectionResult(detected=False, image_size=(iw, ih))

    finally:
        if temp_saved_path and temp_saved_path.exists():
            try:
                temp_saved_path.unlink()
            except Exception:
                pass


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: nolabel_detector.py <image_path>")
        sys.exit(1)

    res = detect_corner_label(sys.argv[1])
    print(json.dumps(res.to_dict(), indent=2))
