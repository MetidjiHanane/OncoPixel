"""Running the two models on a stored slice and persisting everything that comes out.

Classification and segmentation are separate stages. If a checkpoint is missing or invalid the
corresponding stage is skipped and reported; nothing is ever substituted for a real prediction.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import cv2
import numpy as np

from ..context import AppContext
from ..db import now_iso
from ..ml.registry import ModelUnavailable
from . import repo
from .importer import slice_dir
from .measurements import compute_measurements
from .media import (blend_rgba, contour_of, heatmap_rgba, hex_to_rgb, mask_rgba, npy_bytes, png_bytes,
                    read_png_gray, read_npy)
from .validation import segmentation_sanity, warn, WARNING

STAGES = ("classification", "segmentation")


class MaskError(ValueError):
    pass


# -- storage helpers -----------------------------------------------------------------------------
def _rel(ctx: AppContext, slice_id: int, name: str) -> str:
    row = repo.get_slice_row(ctx, slice_id)
    return f"{slice_dir(row['study_id'], slice_id)}/{name}"


def load_gray(ctx: AppContext, slice_id: int) -> np.ndarray:
    return read_png_gray(ctx.files.read(_rel(ctx, slice_id, "original.png")))


def _spacing(row) -> Optional[tuple]:
    return (float(row["spacing_row"]), float(row["spacing_col"])) if row["spacing_row"] else None


def _study_plane(ctx: AppContext, study_id: int) -> str:
    return ctx.db.one("SELECT plane FROM studies WHERE id=?", (study_id,))["plane"]


def load_mask(ctx: AppContext, slice_id: int, which: str = "current") -> Optional[np.ndarray]:
    rel = _rel(ctx, slice_id, "mask_current.png" if which == "current" else "mask_model.png")
    if not ctx.files.exists(rel):
        return None
    return (read_png_gray(ctx.files.read(rel)) > 127).astype(np.uint8)


# -- classification ------------------------------------------------------------------------------
def run_classification(ctx: AppContext, slice_id: int, username: str, with_gradcam: bool = True) -> Dict[str, Any]:
    row = repo.get_slice_row(ctx, slice_id)
    gray = load_gray(ctx, slice_id)
    st = ctx.settings()
    clf = ctx.models.classifier()  # may raise ModelUnavailable
    tta = bool(st["classifier_tta"])
    with ctx.models.infer_lock:
        out = clf.predict(gray, tta=tta)
    needs_review = out.confidence < float(st["review_threshold"])
    gradcam_rel, gradcam_status = None, "not_requested"
    if with_gradcam:
        if not clf.gradcam_supported:
            gradcam_status = "unsupported_architecture"
        else:
            try:
                with ctx.models.infer_lock:
                    cam = clf.gradcam(gray, class_index=clf.classes.index(out.label))
                gradcam_rel = ctx.files.write(_rel(ctx, slice_id, "gradcam.png"), png_bytes((cam * 255).astype(np.uint8)))
                gradcam_status = "ok"
            except Exception as exc:  # report, never hide, and never substitute a fake map
                gradcam_status = f"failed: {type(exc).__name__}: {str(exc)[:160]}"
    ctx.db.update("studies", "id=?", (row["study_id"],), {"clinician_decision": None, "clinician_class": None})  # a new prediction needs a new verdict
    ctx.db.upsert("classifications", "slice_id", {
        "slice_id": slice_id, "label": out.label, "confidence": out.confidence,
        "probs_json": json.dumps(out.probabilities), "needs_review": int(needs_review),
        "model_json": json.dumps(clf.info()),
        "params_json": json.dumps({"tta": tta, "temperature": out.temperature, "review_threshold": float(st["review_threshold"])}),
        "gradcam_rel": gradcam_rel, "gradcam_status": gradcam_status, "inference_ms": out.inference_ms,
        "created_at": now_iso(),
    })
    ctx.db.log(username, "analysis.classify", "slice", slice_id,
               {"label": out.label, "confidence": round(out.confidence, 4), "model": clf.info()["short_id"]})
    repo.recompute_state(ctx, row["study_id"], results_changed=True)
    return classification_dict(ctx, slice_id)


def classification_dict(ctx: AppContext, slice_id: int) -> Optional[Dict[str, Any]]:
    r = ctx.db.one("SELECT * FROM classifications WHERE slice_id=?", (slice_id,))
    if not r:
        return None
    params = json.loads(r["params_json"])
    return {
        "label": r["label"], "confidence": r["confidence"], "probabilities": json.loads(r["probs_json"]),
        "needs_review": bool(r["needs_review"]), "model": json.loads(r["model_json"]), "params": params,
        "gradcam_status": r["gradcam_status"], "has_gradcam": bool(r["gradcam_rel"]),
        "inference_ms": r["inference_ms"], "created_at": r["created_at"],
        "score_kind": "model_confidence_estimate",
    }


# -- segmentation --------------------------------------------------------------------------------
def _store_segmentation(ctx: AppContext, slice_id: int, gray: np.ndarray, res, seg_info: Dict[str, Any],
                        tta: bool, inference_ms: float) -> None:
    row = repo.get_slice_row(ctx, slice_id)
    mask255 = (res.binary_mask > 0).astype(np.uint8) * 255
    ctx.files.write(_rel(ctx, slice_id, "prob.npy"), npy_bytes(res.prob_map.astype(np.float16)))
    mask_png = png_bytes(mask255)
    ctx.files.write(_rel(ctx, slice_id, "mask_model.png"), mask_png)
    ctx.files.write(_rel(ctx, slice_id, "mask_current.png"), mask_png)
    for name in ("unc_entropy.png", "unc_var.png"):  # stale after a new prediction
        rel = _rel(ctx, slice_id, name)
        if ctx.files.exists(rel):
            ctx.files._abs(rel).unlink()
    ctx.db.upsert("segmentations", "slice_id", {
        "slice_id": slice_id, "threshold": res.threshold, "tta": int(tta), "postprocess_json": json.dumps(res.postprocess),
        "model_json": json.dumps(seg_info), "prob_rel": _rel(ctx, slice_id, "prob.npy"),
        "mask_model_rel": _rel(ctx, slice_id, "mask_model.png"), "mask_current_rel": _rel(ctx, slice_id, "mask_current.png"),
        "edited": 0, "edited_at": None, "uncertainty_json": None, "unc_entropy_rel": None, "unc_var_rel": None,
        "inference_ms": inference_ms, "created_at": now_iso(),
    })
    recompute_measurements(ctx, slice_id)


def run_segmentation(ctx: AppContext, slice_id: int, username: str) -> Dict[str, Any]:
    row = repo.get_slice_row(ctx, slice_id)
    gray = load_gray(ctx, slice_id)
    st = ctx.settings()
    svc = ctx.models.segmenter()  # may raise ModelUnavailable
    tta = svc.defaults.get("tta_hflip", False) if st["segmenter_tta"] is None else bool(st["segmenter_tta"])
    with ctx.models.infer_lock:
        prob, ms = svc.predict_prob(gray, tta=tta)
    res = svc.finalize(prob, gray, st["segmentation_threshold"], bool(tta))
    _store_segmentation(ctx, slice_id, gray, res, svc.info(), bool(tta), ms)
    ctx.db.log(username, "analysis.segment", "slice", slice_id,
               {"area_px": res.tumor_area_px, "threshold": res.threshold, "model": svc.info()["short_id"]})
    repo.recompute_state(ctx, row["study_id"], results_changed=True)
    return segmentation_dict(ctx, slice_id)


def resegment(ctx: AppContext, slice_id: int, username: str, threshold: Optional[float],
              postprocess: Optional[Dict[str, Any]], discard_edits: bool = False) -> Dict[str, Any]:
    """Apply a new threshold/post-processing to the stored probability map without running the network."""
    row = repo.get_slice_row(ctx, slice_id)
    seg = ctx.db.one("SELECT * FROM segmentations WHERE slice_id=?", (slice_id,))
    if not seg:
        raise repo.NotFound("segmentation")
    if seg["edited"] and not discard_edits:
        raise MaskError("mask_has_manual_edits")
    if threshold is not None and not 0.0 < float(threshold) < 1.0:
        raise repo.Invalid("threshold_out_of_range")
    svc = ctx.models.segmenter()
    gray = load_gray(ctx, slice_id)
    prob = read_npy(ctx.files.read(seg["prob_rel"])).astype(np.float32)
    res = svc.finalize(prob, gray, threshold, bool(seg["tta"]), ) if postprocess is None else \
        svc.seg.finalize(prob, threshold=threshold, postprocess=postprocess, original_image=gray, tta=bool(seg["tta"]))
    ctx.files.write(_rel(ctx, slice_id, "mask_model.png"), png_bytes((res.binary_mask > 0).astype(np.uint8) * 255))
    ctx.files.write(_rel(ctx, slice_id, "mask_current.png"), png_bytes((res.binary_mask > 0).astype(np.uint8) * 255))
    for name in ("unc_entropy.png", "unc_var.png"):
        rel = _rel(ctx, slice_id, name)
        if ctx.files.exists(rel):
            ctx.files._abs(rel).unlink()
    ctx.db.update("segmentations", "slice_id=?", (slice_id,), {
        "threshold": res.threshold, "postprocess_json": json.dumps(res.postprocess), "edited": 0, "edited_at": None,
        "uncertainty_json": None, "unc_entropy_rel": None, "unc_var_rel": None})
    recompute_measurements(ctx, slice_id)
    ctx.db.log(username, "analysis.rethreshold", "slice", slice_id, {"threshold": res.threshold, "postprocess": res.postprocess})
    repo.recompute_state(ctx, row["study_id"], results_changed=True)
    return segmentation_dict(ctx, slice_id)


def compute_uncertainty(ctx: AppContext, slice_id: int, username: str) -> Dict[str, Any]:
    seg = ctx.db.one("SELECT * FROM segmentations WHERE slice_id=?", (slice_id,))
    if not seg:
        raise repo.NotFound("segmentation")
    svc = ctx.models.segmenter()
    gray = load_gray(ctx, slice_id)
    with ctx.models.infer_lock:
        unc = svc.uncertainty(gray, float(seg["threshold"]))
    ent = ctx.files.write(_rel(ctx, slice_id, "unc_entropy.png"), png_bytes((unc["entropy"] * 255).astype(np.uint8)))
    var = ctx.files.write(_rel(ctx, slice_id, "unc_var.png"), png_bytes((unc["variability"] * 255).astype(np.uint8)))
    ctx.db.update("segmentations", "slice_id=?", (slice_id,), {
        "uncertainty_json": json.dumps(unc["stats"]), "unc_entropy_rel": ent, "unc_var_rel": var})
    ctx.db.log(username, "analysis.uncertainty", "slice", slice_id, {"stability_dice": round(unc["stats"]["stability_dice_mean"], 3)})
    return segmentation_dict(ctx, slice_id)


def segmentation_dict(ctx: AppContext, slice_id: int) -> Optional[Dict[str, Any]]:
    r = ctx.db.one("SELECT * FROM segmentations WHERE slice_id=?", (slice_id,))
    if not r:
        return None
    return {
        "threshold": r["threshold"], "tta": bool(r["tta"]), "postprocess": json.loads(r["postprocess_json"]),
        "model": json.loads(r["model_json"]), "edited": bool(r["edited"]), "edited_at": r["edited_at"],
        "has_uncertainty": bool(r["unc_entropy_rel"]),
        "uncertainty": json.loads(r["uncertainty_json"]) if r["uncertainty_json"] else None,
        "inference_ms": r["inference_ms"], "created_at": r["created_at"],
    }


# -- manual correction ---------------------------------------------------------------------------
def save_mask(ctx: AppContext, slice_id: int, mask: np.ndarray, username: str) -> Dict[str, Any]:
    row = repo.get_slice_row(ctx, slice_id)
    seg = ctx.db.one("SELECT 1 FROM segmentations WHERE slice_id=?", (slice_id,))
    if not seg:
        raise repo.NotFound("segmentation")
    if mask.shape != (row["height"], row["width"]):
        raise MaskError("mask_size_mismatch")
    clean = ((mask > 127).astype(np.uint8)) * 255
    ctx.files.write(_rel(ctx, slice_id, "mask_current.png"), png_bytes(clean))
    ctx.db.update("segmentations", "slice_id=?", (slice_id,), {"edited": 1, "edited_at": now_iso()})
    recompute_measurements(ctx, slice_id)
    ctx.db.log(username, "mask.edit", "slice", slice_id, {"area_px": int((clean > 0).sum())})
    repo.recompute_state(ctx, row["study_id"], results_changed=True)
    return segmentation_dict(ctx, slice_id)


def reset_mask(ctx: AppContext, slice_id: int, username: str) -> Dict[str, Any]:
    row = repo.get_slice_row(ctx, slice_id)
    model_mask = load_mask(ctx, slice_id, "model")
    if model_mask is None:
        raise repo.NotFound("segmentation")
    ctx.files.write(_rel(ctx, slice_id, "mask_current.png"), png_bytes(model_mask * 255))
    ctx.db.update("segmentations", "slice_id=?", (slice_id,), {"edited": 0, "edited_at": None})
    recompute_measurements(ctx, slice_id)
    ctx.db.log(username, "mask.reset", "slice", slice_id)
    repo.recompute_state(ctx, row["study_id"], results_changed=True)
    return segmentation_dict(ctx, slice_id)


# -- measurements --------------------------------------------------------------------------------
def recompute_measurements(ctx: AppContext, slice_id: int) -> Optional[Dict[str, Any]]:
    mask = load_mask(ctx, slice_id)
    if mask is None:
        return None
    row = repo.get_slice_row(ctx, slice_id)
    gray = load_gray(ctx, slice_id)
    edited = bool(ctx.db.one("SELECT edited FROM segmentations WHERE slice_id=?", (slice_id,))["edited"])
    m = compute_measurements(gray, mask, _spacing(row), _study_plane(ctx, row["study_id"]))
    m["spacing_source"] = row["spacing_source"]
    ctx.db.upsert("measurements", "slice_id", {
        "slice_id": slice_id, "json": json.dumps(m), "computed_at": now_iso(), "mask_edited": int(edited)})
    return m


def measurements_dict(ctx: AppContext, slice_id: int) -> Optional[Dict[str, Any]]:
    r = ctx.db.one("SELECT json, mask_edited, computed_at FROM measurements WHERE slice_id=?", (slice_id,))
    if not r:
        return None
    m = json.loads(r["json"])
    m["mask_edited"] = bool(r["mask_edited"])
    m["computed_at"] = r["computed_at"]
    return m


# -- orchestration -------------------------------------------------------------------------------
def analyze(ctx: AppContext, slice_id: int, username: str, stages: Optional[List[str]] = None,
            with_gradcam: bool = True) -> Dict[str, Any]:
    stages = list(stages or STAGES)
    if any(s not in STAGES for s in stages):
        raise repo.Invalid("stage_invalid")
    skipped: Dict[str, Any] = {}
    for stage in stages:
        try:
            if stage == "classification":
                run_classification(ctx, slice_id, username, with_gradcam)
            else:
                run_segmentation(ctx, slice_id, username)
        except ModelUnavailable as exc:
            skipped[stage] = exc.to_dict()
    if len(skipped) == len(stages):
        raise ModelUnavailable(*[next(iter(skipped.values()))[k] for k in ("kind", "state", "code", "detail", "path")])
    result = slice_results(ctx, slice_id)
    result["skipped"] = skipped
    return result


def consistency_warnings(cls: Optional[Dict[str, Any]], meas: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not cls or not meas:
        return []
    detected = bool(meas.get("tumor_detected"))
    if cls["label"] == "no_tumor" and detected:
        return [warn("classifier_no_tumor_but_mask", WARNING, area_px=meas.get("area_px"))]
    if cls["label"] != "no_tumor" and not detected:
        return [warn("classifier_tumor_but_empty_mask", WARNING, label=cls["label"])]
    return []


def slice_results(ctx: AppContext, slice_id: int) -> Dict[str, Any]:
    row = repo.get_slice_row(ctx, slice_id)
    cls, seg, meas = classification_dict(ctx, slice_id), segmentation_dict(ctx, slice_id), measurements_dict(ctx, slice_id)
    warnings = list(json.loads(row["warnings_json"]))
    warnings += consistency_warnings(cls, meas)
    mask = load_mask(ctx, slice_id) if seg else None
    if mask is not None:
        warnings += segmentation_sanity(mask)
    return {"slice": repo.slice_dict(row, ctx=ctx), "classification": cls, "segmentation": seg,
            "measurements": meas, "warnings": warnings}


# -- rendering -----------------------------------------------------------------------------------
KINDS = ("original", "mask", "contour", "overlay", "gradcam", "gradcam_overlay", "uncertainty", "uncertainty_overlay",
         "variability", "variability_overlay", "probability")


def image_png(ctx: AppContext, slice_id: int, kind: str, opacity: Optional[float] = None,
              color: Optional[str] = None, contour: Optional[bool] = None, which_mask: str = "current") -> bytes:
    """PNG for the viewer. Overlay layers are RGBA so the client can control opacity."""
    st = ctx.settings()
    row = repo.get_slice_row(ctx, slice_id)
    if kind == "original":
        return ctx.files.read(_rel(ctx, slice_id, "original.png"))
    op = st["overlay_opacity"] if opacity is None else float(opacity)
    col = hex_to_rgb(color or st["overlay_color"])
    show_contour = st["show_contour"] if contour is None else contour
    gray = load_gray(ctx, slice_id)
    if kind == "contour":
        mask = load_mask(ctx, slice_id, which_mask)
        if mask is None:
            raise repo.NotFound("segmentation")
        layer = mask_rgba(np.zeros_like(mask), col, 0.0, contour_of(mask), (255, 224, 102))
        return png_bytes(layer)
    if kind in ("mask", "overlay"):
        mask = load_mask(ctx, slice_id, which_mask)
        if mask is None:
            raise repo.NotFound("segmentation")
        layer = mask_rgba(mask, col, op, contour_of(mask) if show_contour else None)
        return png_bytes(layer if kind == "mask" else blend_rgba(gray, layer))
    if kind in ("gradcam", "gradcam_overlay"):
        rel = ctx.db.one("SELECT gradcam_rel FROM classifications WHERE slice_id=?", (slice_id,))
        if not rel or not rel["gradcam_rel"]:
            raise repo.NotFound("gradcam")
        cam = read_png_gray(ctx.files.read(rel["gradcam_rel"])).astype(np.float32) / 255.0
        layer = heatmap_rgba(cam, cv2.COLORMAP_JET)
        return png_bytes(layer if kind == "gradcam" else blend_rgba(gray, layer))
    if kind in ("uncertainty", "uncertainty_overlay", "variability", "variability_overlay"):
        seg = ctx.db.one("SELECT unc_entropy_rel, unc_var_rel FROM segmentations WHERE slice_id=?", (slice_id,))
        rel = seg and (seg["unc_entropy_rel"] if kind.startswith("uncertainty") else seg["unc_var_rel"])
        if not rel:
            raise repo.NotFound("uncertainty")
        vals = read_png_gray(ctx.files.read(rel)).astype(np.float32) / 255.0
        layer = heatmap_rgba(vals, cv2.COLORMAP_INFERNO, max_alpha=0.9, floor=0.08)
        return png_bytes(layer if not kind.endswith("overlay") else blend_rgba(gray, layer))
    if kind == "probability":
        seg = ctx.db.one("SELECT prob_rel FROM segmentations WHERE slice_id=?", (slice_id,))
        if not seg:
            raise repo.NotFound("segmentation")
        prob = read_npy(ctx.files.read(seg["prob_rel"])).astype(np.float32)
        return png_bytes(heatmap_rgba(prob, cv2.COLORMAP_VIRIDIS, max_alpha=0.9, floor=0.02))
    raise repo.Invalid("kind_invalid")
