#!/usr/bin/env python3
"""
NoLabel Near-Background Inpainter and Canvas Healer
Part of NoLabel Suite.
Implements the 2-step removal and restoration:
1. Sample perimeter background (solid or 2D gradient) and remove the label by filling
   its bounding area (rectangle or rounded rectangle) with near-background color.
2. Inpaint and heal the area and boundary seams using OpenCV Fast Marching (Telea)
   or Navier-Stokes with boundary feathering for seamless restoration.
"""

from __future__ import annotations

import math
from typing import Tuple, Union

import cv2
import numpy as np


class BackgroundAnalysis:
    def __init__(
        self,
        dominant_bgr: Tuple[int, int, int],
        is_gradient: bool = False,
        plane_params_bgr: Tuple[np.ndarray, np.ndarray, np.ndarray] = None,
        noise_variance: float = 0.0,
    ):
        self.dominant_bgr = dominant_bgr
        self.is_gradient = is_gradient
        self.plane_params_bgr = plane_params_bgr
        self.noise_variance = noise_variance


def analyze_perimeter_background(
    img: np.ndarray,
    box: Tuple[int, int, int, int],
    margin: int = 16,
) -> BackgroundAnalysis:
    """
    Samples perimeter pixels outside the bounding box to compute the near-background
    dominant color and 2D bilinear gradient plane parameters.
    """
    ih, iw = img.shape[:2]
    bx, by, bw, bh = box

    x1 = max(0, bx)
    y1 = max(0, by)
    x2 = min(iw, bx + bw)
    y2 = min(ih, by + bh)

    outer_x1 = max(0, x1 - margin)
    outer_y1 = max(0, y1 - margin)
    outer_x2 = min(iw, x2 + margin)
    outer_y2 = min(ih, y2 + margin)

    coords_x = []
    coords_y = []
    b_vals = []
    g_vals = []
    r_vals = []

    def sample_strip(sx1, sy1, sx2, sy2):
        if sx2 <= sx1 or sy2 <= sy1:
            return
        strip = img[sy1:sy2, sx1:sx2]
        for sy in range(sy1, sy2):
            for sx in range(sx1, sx2):
                b, g, r = img[sy, sx]
                coords_x.append(float(sx))
                coords_y.append(float(sy))
                b_vals.append(float(b))
                g_vals.append(float(g))
                r_vals.append(float(r))

    # Top strip
    sample_strip(outer_x1, outer_y1, outer_x2, y1)
    # Bottom strip
    sample_strip(outer_x1, y2, outer_x2, outer_y2)
    # Left strip
    sample_strip(outer_x1, y1, x1, y2)
    # Right strip
    sample_strip(x2, y1, outer_x2, y2)

    if not b_vals:
        return BackgroundAnalysis(dominant_bgr=(240, 240, 240), is_gradient=False)

    med_b = int(np.median(b_vals))
    med_g = int(np.median(g_vals))
    med_r = int(np.median(r_vals))
    dominant_bgr = (med_b, med_g, med_r)

    # Check gradient variance
    var_b = float(np.var(b_vals))
    var_g = float(np.var(g_vals))
    var_r = float(np.var(r_vals))
    is_gradient = max(var_b, var_g, var_r) > 8.0

    plane_params = None
    if is_gradient and len(coords_x) >= 10:
        # Fit 2D planes: V(x, y) = a*x + b*y + c
        pts = np.column_stack([coords_x, coords_y, np.ones(len(coords_x))])
        try:
            p_b, _, _, _ = np.linalg.lstsq(pts, b_vals, rcond=None)
            p_g, _, _, _ = np.linalg.lstsq(pts, g_vals, rcond=None)
            p_r, _, _, _ = np.linalg.lstsq(pts, r_vals, rcond=None)
            plane_params = (p_b, p_g, p_r)
        except Exception:
            is_gradient = False

    return BackgroundAnalysis(
        dominant_bgr=dominant_bgr,
        is_gradient=is_gradient,
        plane_params_bgr=plane_params,
        noise_variance=float(np.mean([var_b, var_g, var_r])),
    )


def create_rounded_rect_mask(
    shape: Tuple[int, int],
    box: Tuple[int, int, int, int],
    radius: int = 0
) -> np.ndarray:
    """Creates a binary mask (uint8) with antialiased rounded rectangle or rectangle."""
    h, w = shape[:2]
    mask = np.zeros((h, w), dtype=np.uint8)
    bx, by, bw, bh = box

    x1 = max(0, bx)
    y1 = max(0, by)
    x2 = min(w, bx + bw)
    y2 = min(h, by + bh)

    if radius <= 0 or radius > min(bw, bh) // 2:
        radius = min(bw, bh) // 2

    # Draw rounded rectangle: central rectangle, side rectangles, and 4 corner circles
    cv2.rectangle(mask, (x1 + radius, y1), (x2 - radius, y2), 255, -1)
    cv2.rectangle(mask, (x1, y1 + radius), (x2, y2 - radius), 255, -1)
    cv2.circle(mask, (x1 + radius, y1 + radius), radius, 255, -1, cv2.LINE_AA)
    cv2.circle(mask, (x2 - radius, y1 + radius), radius, 255, -1, cv2.LINE_AA)
    cv2.circle(mask, (x1 + radius, y2 - radius), radius, 255, -1, cv2.LINE_AA)
    cv2.circle(mask, (x2 - radius, y2 - radius), radius, 255, -1, cv2.LINE_AA)

    return mask


def heal_label_area(
    img: np.ndarray,
    box: Tuple[int, int, int, int],
    shape_type: str = "rectangle",
    corner_radius: int = 0,
    inpaint_radius: int = 3,
    method: str = "telea",
    pad: int = 3
) -> np.ndarray:
    """
    Executes the 2-step removal and healing process:
    1. Sample perimeter background and replace the label area with near-background color/gradient.
    2. Inpaint and heal the seam boundary and area for flawless transition.
    """
    ih, iw = img.shape[:2]
    bx, by, bw, bh = box

    # Expand box slightly by pad to cover antialiased edges and borders
    x1 = max(0, bx - pad)
    y1 = max(0, by - pad)
    x2 = min(iw, bx + bw + pad)
    y2 = min(ih, by + bh + pad)
    actual_box = (x1, y1, x2 - x1, y2 - y1)

    # 1. Analyze surrounding background
    bg = analyze_perimeter_background(img, actual_box, margin=16)

    # Step A: Remove label with near background color / gradient
    healed_step1 = img.copy()

    # Generate synthetic patch matching background
    patch_w = x2 - x1
    patch_h = y2 - y1
    if patch_w <= 0 or patch_h <= 0:
        return img

    patch = np.zeros((patch_h, patch_w, 3), dtype=np.uint8)
    if bg.is_gradient and bg.plane_params_bgr is not None:
        p_b, p_g, p_r = bg.plane_params_bgr
        grid_y, grid_x = np.mgrid[y1:y2, x1:x2]
        pred_b = np.clip(p_b[0] * grid_x + p_b[1] * grid_y + p_b[2], 0, 255)
        pred_g = np.clip(p_g[0] * grid_x + p_g[1] * grid_y + p_g[2], 0, 255)
        pred_r = np.clip(p_r[0] * grid_x + p_r[1] * grid_y + p_r[2], 0, 255)
        patch[:, :, 0] = pred_b.astype(np.uint8)
        patch[:, :, 1] = pred_g.astype(np.uint8)
        patch[:, :, 2] = pred_r.astype(np.uint8)
    else:
        patch[:] = bg.dominant_bgr

    # Create shape mask
    if shape_type == "rounded_rectangle" and corner_radius > 0:
        shape_mask = create_rounded_rect_mask((ih, iw), actual_box, radius=corner_radius + pad)
        roi_mask = shape_mask[y1:y2, x1:x2]
        np.copyto(healed_step1[y1:y2, x1:x2], patch, where=(roi_mask[:, :, None] == 255))
        inpaint_target_mask = shape_mask
    else:
        healed_step1[y1:y2, x1:x2] = patch
        inpaint_target_mask = np.zeros((ih, iw), dtype=np.uint8)
        cv2.rectangle(inpaint_target_mask, (x1, y1), (x2, y2), 255, -1)

    # Step B: Start to heal the area (inpaint boundary and seam)
    # Dilate mask slightly so inpainting blends the boundary pixels seamlessly
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    dilated_mask = cv2.dilate(inpaint_target_mask, kernel, iterations=1)

    inpaint_flag = cv2.INPAINT_TELEA if method == "telea" else cv2.INPAINT_NS
    final_img = cv2.inpaint(healed_step1, dilated_mask, inpaint_radius, inpaint_flag)

    return final_img
