"""Smoke test of the loaded models on a synthetic phantom image.

Checks structure, not accuracy: output shapes, probability ranges, finite values and timing.
The result is never stored as an analysis and never shown as a prediction about a patient.
"""
from __future__ import annotations

import math
import time
from typing import Any, Dict

import numpy as np

from ..ml.registry import ModelRegistry, ModelUnavailable


def phantom(size: int = 256) -> np.ndarray:
    yy, xx = np.mgrid[:size, :size].astype(np.float32)
    c = size / 2
    img = np.zeros((size, size), np.float32)
    img[(((xx - c) / (size * 0.38)) ** 2 + ((yy - c) / (size * 0.45)) ** 2) < 1] = 90
    img[(((xx - c) / (size * 0.33)) ** 2 + ((yy - c) / (size * 0.4)) ** 2) < 1] = 120
    img[(((xx - c * 1.25) / (size * 0.09)) ** 2 + ((yy - c * 0.85) / (size * 0.07)) ** 2) < 1] = 215
    return np.clip(img, 0, 255).astype(np.uint8)


def _check(name: str, ok: bool, detail: str = "") -> Dict[str, Any]:
    return {"name": name, "ok": bool(ok), "detail": detail}


def run(models: ModelRegistry) -> Dict[str, Any]:
    img = phantom()
    out: Dict[str, Any] = {"classification": None, "segmentation": None, "device": models.device()}
    try:
        clf = models.classifier()
        checks = []
        t0 = time.perf_counter()
        with models.infer_lock:
            res = clf.predict(img, tta=True)
        ms = (time.perf_counter() - t0) * 1000
        p = list(res.probabilities.values())
        checks += [_check("four_classes_in_expected_order", clf.classes == ["glioma", "meningioma", "no_tumor", "pituitary"], str(clf.classes)),
                   _check("probabilities_sum_to_one", abs(sum(p) - 1) < 1e-4, f"sum={sum(p):.6f}"),
                   _check("finite_outputs", all(math.isfinite(v) for v in res.logits)),
                   _check("input_size", clf.size > 0, f"{clf.size}px")]
        if clf.gradcam_supported:
            try:
                with models.infer_lock:
                    cam = clf.gradcam(img)
                checks.append(_check("gradcam_shape", cam.shape == img.shape and 0 <= float(cam.min()) and float(cam.max()) <= 1.0, f"{cam.shape}"))
            except Exception as exc:
                checks.append(_check("gradcam_shape", False, f"{type(exc).__name__}: {exc}"))
        out["classification"] = {"state": "ready", "info": clf.info(), "checks": checks, "forward_ms": round(ms, 1)}
    except ModelUnavailable as exc:
        out["classification"] = {"state": exc.state, "error": exc.to_dict(), "checks": []}
    try:
        seg = models.segmenter()
        t0 = time.perf_counter()
        with models.infer_lock:
            prob, _ = seg.predict_prob(img, tta=False)
        ms = (time.perf_counter() - t0) * 1000
        checks = [_check("probability_map_shape", prob.shape == img.shape, f"{prob.shape} vs {img.shape}"),
                  _check("probabilities_in_unit_range", float(prob.min()) >= 0 and float(prob.max()) <= 1, f"[{prob.min():.3f}, {prob.max():.3f}]"),
                  _check("finite_outputs", bool(np.isfinite(prob).all())),
                  _check("input_size", seg.seg.input_size > 0, f"{seg.seg.input_size}px")]
        out["segmentation"] = {"state": "ready", "info": seg.info(), "checks": checks, "forward_ms": round(ms, 1)}
    except ModelUnavailable as exc:
        out["segmentation"] = {"state": exc.state, "error": exc.to_dict(), "checks": []}
    out["all_ok"] = all(
        (out[k] or {}).get("state") == "ready" and all(c["ok"] for c in out[k]["checks"]) for k in ("classification", "segmentation"))
    out["test_fixture"] = any(bool(((out[k] or {}).get("info") or {}).get("test_fixture")) for k in ("classification", "segmentation"))
    return out
