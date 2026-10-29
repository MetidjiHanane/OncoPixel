"""Input validation and plausibility warnings for imported slices.

A reliable "is this a T1 brain MRI?" detector would need its own trained model. These checks
catch clearly unsupported input (unreadable, tiny, blank, colour photographs) and add soft
warnings; they cannot prove that an image is a brain scan.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

MIN_SIDE = 64
MAX_ASPECT = 2.0
BLOCKING = "error"
WARNING = "warning"
INFO = "info"

# Sequence descriptions that are clearly not T1-weighted (DICOM SeriesDescription).
_NON_T1 = ("t2", "flair", "dwi", "adc", "swi", "tof", "angio", "mra", "stir", "pd ")


def warn(code: str, severity: str, **params: Any) -> Dict[str, Any]:
    return {"code": code, "severity": severity, "params": params}


def validate_pixels(gray: np.ndarray, color_chroma: Optional[float], max_pixels: int) -> List[Dict[str, Any]]:
    """Return warnings; any with severity ``error`` means the image must be rejected."""
    out: List[Dict[str, Any]] = []
    h, w = gray.shape[:2]
    if min(h, w) < MIN_SIDE:
        out.append(warn("image_too_small", BLOCKING, width=w, height=h, minimum=MIN_SIDE))
    if h * w > max_pixels:
        out.append(warn("image_too_large", BLOCKING, width=w, height=h, max_pixels=max_pixels))
    if out:
        return out
    if float(gray.std()) < 3.0:
        out.append(warn("image_blank_or_flat", BLOCKING))
        return out
    if color_chroma is not None and color_chroma > 12.0:
        out.append(warn("image_is_colour", WARNING, chroma=round(color_chroma, 1)))
    ratio = max(h, w) / max(1, min(h, w))
    if ratio > MAX_ASPECT:
        out.append(warn("unusual_aspect_ratio", WARNING, ratio=round(ratio, 2)))
    # Brain MRI slices have a dark background: most border pixels are near black.
    border = np.concatenate([gray[0, :], gray[-1, :], gray[:, 0], gray[:, -1]])
    if float(np.median(border)) > 90:
        out.append(warn("bright_border_not_typical_mri", WARNING))
    if int(gray.max()) - int(gray.min()) < 60:
        out.append(warn("low_dynamic_range", WARNING))
    out.append(warn("not_verified_brain_t1", INFO))
    return out


def sequence_warning(description: Optional[str]) -> Optional[Dict[str, Any]]:
    """Warn when a DICOM series description names a non-T1 sequence."""
    if not description:
        return None
    low = description.lower()
    if "t1" in low:
        return None
    if any(tag in low for tag in _NON_T1):
        return warn("sequence_not_t1", WARNING, description=description)
    return None


def segmentation_sanity(mask: np.ndarray) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    frac = float(mask.mean()) if mask.size else 0.0
    if frac > 0.5:
        out.append(warn("mask_covers_half_the_image", WARNING, fraction=round(frac, 3)))
    return out


def has_blocking(warnings: List[Dict[str, Any]]) -> bool:
    return any(w["severity"] == BLOCKING for w in warnings)
