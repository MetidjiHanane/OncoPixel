"""Comparison of two studies of the same patient: measurement change and mask overlay.

The two images are not registered. The overlay is meaningful only when both come from the same
acquisition geometry; the response says so explicitly and reports when image sizes differ.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, Optional

import numpy as np

from ..context import AppContext
from . import analysis, repo
from .measurements import compare_measurements
from .media import contour_of, png_bytes, resize_nearest


def _primary(ctx: AppContext, study_id: int) -> int:
    row = ctx.db.one("SELECT primary_slice_id FROM studies WHERE id=?", (study_id,))
    if not row:
        raise repo.NotFound("study")
    if not row["primary_slice_id"]:
        raise repo.Invalid("study_has_no_slice")
    return int(row["primary_slice_id"])


def compare_studies(ctx: AppContext, study_a: int, study_b: int) -> Dict[str, Any]:
    """``a`` is the baseline, ``b`` the follow-up."""
    if study_a == study_b:
        raise repo.Invalid("same_study")
    sa, sb = repo.study_detail(ctx, study_a), repo.study_detail(ctx, study_b)
    pa, pb = sa.get("patient"), sb.get("patient")
    if not pa or not pb or pa["id"] != pb["id"]:
        raise repo.Invalid("different_patients")
    ia, ib = _primary(ctx, study_a), _primary(ctx, study_b)
    ma, mb = analysis.measurements_dict(ctx, ia), analysis.measurements_dict(ctx, ib)
    if ma is None or mb is None:
        raise repo.Invalid("study_not_segmented")
    out: Dict[str, Any] = {"a": {"study": _brief(sa), "slice_id": ia}, "b": {"study": _brief(sb), "slice_id": ib}}
    out["comparison"] = compare_measurements(ma, mb)
    out["measurements"] = {"a": ma, "b": mb}
    days: Optional[int] = None
    try:
        days = (date.fromisoformat(sb["study_date"]) - date.fromisoformat(sa["study_date"])).days
    except (TypeError, ValueError):
        pass
    out["days_between"] = days
    notes = []
    ga, gb = analysis.load_gray(ctx, ia), analysis.load_gray(ctx, ib)
    maska, maskb = analysis.load_mask(ctx, ia), analysis.load_mask(ctx, ib)
    same_grid = ga.shape == gb.shape
    if not same_grid:
        notes.append("different_image_sizes")
    notes.append("images_not_registered")
    if sa["plane"] != sb["plane"]:
        notes.append("different_planes")
    ra, rb = repo.get_slice_row(ctx, ia), repo.get_slice_row(ctx, ib)
    if (ra["spacing_row"], ra["spacing_col"]) != (rb["spacing_row"], rb["spacing_col"]):
        notes.append("different_pixel_spacing")
    ov = None
    if same_grid:
        inter = int((maska & maskb).sum())
        union = int((maska | maskb).sum())
        ov = {"dice": (2.0 * inter / int(maska.sum() + maskb.sum())) if int(maska.sum() + maskb.sum()) else None,
              "iou": inter / union if union else None, "overlap_px": inter,
              "only_a_px": int((maska & (1 - maskb)).sum()), "only_b_px": int(((1 - maska) & maskb).sum())}
    out["mask_overlap"] = ov
    out["notes"] = notes
    rows = {r["metric"]: r for r in out["comparison"]["rows"]}
    if days and "area" in rows:
        out["area_change_per_day"] = rows["area"]["delta"] / days
    return out


def _brief(s: Dict[str, Any]) -> Dict[str, Any]:
    return {k: s.get(k) for k in ("id", "code", "study_date", "plane", "sequence", "status", "prediction")}


def overlay_png(ctx: AppContext, study_a: int, study_b: int) -> bytes:
    """Follow-up image with the baseline contour (cyan), follow-up contour (magenta) and overlap (yellow fill)."""
    ia, ib = _primary(ctx, study_a), _primary(ctx, study_b)
    gb = analysis.load_gray(ctx, ib)
    ma = analysis.load_mask(ctx, ia)
    mb = analysis.load_mask(ctx, ib)
    if ma is None or mb is None:
        raise repo.Invalid("study_not_segmented")
    ma = resize_nearest(ma, gb.shape)
    rgb = np.repeat(gb[..., None], 3, axis=2).astype(np.float32)
    both = (ma > 0) & (mb > 0)
    only_a = (ma > 0) & ~(mb > 0)
    only_b = (mb > 0) & ~(ma > 0)
    for m, col, a in ((both, (255, 214, 10), 0.35), (only_a, (0, 200, 255), 0.35), (only_b, (255, 60, 200), 0.35)):
        rgb[m] = rgb[m] * (1 - a) + np.array(col, np.float32) * a
    out = np.clip(rgb, 0, 255).astype(np.uint8)
    out[contour_of(ma) > 0] = (0, 220, 255)
    out[contour_of(mb) > 0] = (255, 60, 200)
    return png_bytes(out)
