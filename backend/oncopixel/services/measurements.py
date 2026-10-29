"""Quantitative description of a 2D tumor mask.

All geometry is computed in pixels on the original image grid. Values in millimetres are
added only when pixel spacing is known (read from DICOM or entered by the user); nothing is
assumed. Volume is intentionally not reported: it needs verified slice spacing and mask
consistency across a series.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np


def _hull_points(mask: np.ndarray) -> np.ndarray:
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    pts = np.concatenate([c[:, 0, :] for c in contours]).astype(np.float64)
    hull = cv2.convexHull(pts.astype(np.float32))[:, 0, :].astype(np.float64)
    # use pixel extents (edges of boundary pixels), not centres
    return hull


def feret_diameters(mask: np.ndarray, spacing: Tuple[float, float] = (1.0, 1.0)) -> Dict[str, float]:
    """Maximum and minimum Feret (caliper) diameters of the largest region, in spacing units.

    ``spacing`` is (row spacing, column spacing). Boundary pixel centres are used, so a one-pixel
    object has diameter 0; add one pixel width as a conservative extent when needed.
    """
    hull = _hull_points(mask)
    sr, sc = spacing
    pts = np.stack([hull[:, 0] * sc, hull[:, 1] * sr], axis=1)
    if len(pts) < 2:
        return {"max": 0.0, "min": 0.0, "max_angle_deg": 0.0}
    diff = pts[:, None, :] - pts[None, :, :]
    d = np.sqrt((diff ** 2).sum(-1))
    i, j = np.unravel_index(int(np.argmax(d)), d.shape)
    max_d = float(d[i, j])
    max_angle = math.degrees(math.atan2(pts[j, 1] - pts[i, 1], pts[j, 0] - pts[i, 0])) % 180.0
    angles = np.deg2rad(np.arange(0, 180, 0.5))
    proj = pts @ np.stack([np.cos(angles), np.sin(angles)])  # (n_pts, n_angles)
    widths = proj.max(0) - proj.min(0)
    return {"max": max_d, "min": float(widths.min()), "max_angle_deg": float(max_angle),
            "endpoints_px": [[float(hull[i, 0]), float(hull[i, 1])], [float(hull[j, 0]), float(hull[j, 1])]]}


def compute_measurements(
    gray: np.ndarray,
    mask: np.ndarray,
    spacing: Optional[Tuple[float, float]] = None,
    plane: str = "unknown",
) -> Dict[str, Any]:
    """Measurements of ``mask`` (uint8 {0,1}) on ``gray`` (uint8). ``spacing`` = (row, col) in mm."""
    m = (mask > 0).astype(np.uint8)
    h, w = m.shape
    out: Dict[str, Any] = {
        "image_width_px": int(w), "image_height_px": int(h),
        "units": "mm" if spacing else "px",
        "pixel_spacing_mm": list(spacing) if spacing else None,
    }
    area_px = int(m.sum())
    out["tumor_detected"] = area_px > 0
    out["area_px"] = area_px
    out["area_fraction_of_image"] = area_px / float(h * w)
    if area_px == 0:
        return out

    n, labels, stats, cents = cv2.connectedComponentsWithStats(m, connectivity=8)
    areas = stats[1:, cv2.CC_STAT_AREA]
    out["n_components"] = int(n - 1)
    out["largest_component_area_px"] = int(areas.max())

    ys, xs = np.nonzero(m)
    x0, y0, x1, y1 = int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
    out["bbox_xyxy_px"] = [x0, y0, x1, y1]
    out["bbox_width_px"], out["bbox_height_px"] = x1 - x0, y1 - y0

    mom = cv2.moments(m, binaryImage=True)
    cx, cy = mom["m10"] / mom["m00"], mom["m01"] / mom["m00"]
    out["centroid_xy_px"] = [float(cx), float(cy)]

    contours, _ = cv2.findContours(m, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    perimeter = float(sum(cv2.arcLength(c, True) for c in contours))
    out["perimeter_px"] = perimeter
    out["circularity"] = float(min(1.0, 4.0 * math.pi * area_px / (perimeter ** 2))) if perimeter > 0 else None
    out["equivalent_diameter_px"] = float(math.sqrt(4.0 * area_px / math.pi))

    fer = feret_diameters(m)
    out["max_diameter_px"], out["min_diameter_px"] = fer["max"], fer["min"]
    out["max_diameter_angle_deg"] = fer["max_angle_deg"]
    out["max_diameter_endpoints_px"] = fer.get("endpoints_px")
    out["aspect_ratio"] = float(fer["max"] / fer["min"]) if fer["min"] > 0 else None

    # Distance from the vertical image midline. This is an image-geometry approximation: it is
    # meaningful only for upright axial or coronal slices with the head centred in the frame.
    midline_px = abs(cx - (w - 1) / 2.0)
    out["midline_distance_px"] = float(midline_px)
    out["midline_note"] = "midline_is_image_centre" if plane in ("axial", "coronal", "unknown") else "midline_not_applicable"
    if plane == "sagittal":
        out["midline_distance_px"] = None

    # intensity statistics inside the mask and contrast against a surrounding ring
    vals = gray[m > 0].astype(np.float64)
    out["intensity"] = {
        "mean": float(vals.mean()), "std": float(vals.std()), "median": float(np.median(vals)),
        "min": int(vals.min()), "max": int(vals.max()),
    }
    k = max(3, int(round(0.03 * max(h, w))))
    kern = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * k + 1, 2 * k + 1))
    ring = (cv2.dilate(m, kern) > 0) & (m == 0)
    if ring.sum() > 20:
        ring_mean = float(gray[ring].mean())
        out["intensity"]["surrounding_ring_mean"] = ring_mean
        out["intensity"]["contrast_ratio"] = float(vals.mean() / ring_mean) if ring_mean > 0 else None

    if spacing:
        sr, sc = spacing
        px_area = sr * sc
        mean_sp = math.sqrt(px_area)
        fer_mm = feret_diameters(m, spacing)
        out["area_mm2"] = area_px * px_area
        out["bbox_width_mm"], out["bbox_height_mm"] = (x1 - x0) * sc, (y1 - y0) * sr
        out["centroid_xy_mm"] = [float(cx * sc), float(cy * sr)]
        out["perimeter_mm"] = perimeter * mean_sp  # arc length on a near-isotropic grid
        out["equivalent_diameter_mm"] = float(math.sqrt(4.0 * area_px * px_area / math.pi))
        out["max_diameter_mm"], out["min_diameter_mm"] = fer_mm["max"], fer_mm["min"]
        if out["midline_distance_px"] is not None:
            out["midline_distance_mm"] = out["midline_distance_px"] * sc
        if abs(sr - sc) / max(sr, sc) > 0.05:
            out["spacing_note"] = "anisotropic_spacing_perimeter_approximate"
    return out


def compare_measurements(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    """Differences ``b - a`` for the headline quantities, in the unit both studies share."""
    both_mm = a.get("units") == "mm" and b.get("units") == "mm"
    keys = ["area", "max_diameter", "min_diameter", "perimeter"]
    suffix = "_mm2" if both_mm else "_px"
    rows: List[Dict[str, Any]] = []
    for key in keys:
        ka = f"{key}_mm" + ("2" if key == "area" else "") if both_mm else f"{key}_px"
        va, vb = a.get(ka), b.get(ka)
        if va is None or vb is None:
            continue
        rows.append({
            "metric": key, "unit": ("mm2" if key == "area" else "mm") if both_mm else "px",
            "a": va, "b": vb, "delta": vb - va, "percent": (100.0 * (vb - va) / va) if va else None,
        })
    return {"unit_system": "mm" if both_mm else "px", "rows": rows,
            "comparable_in_mm": both_mm, "suffix": suffix}
