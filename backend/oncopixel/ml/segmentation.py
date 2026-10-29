"""Segmentation service around the user's unchanged ``segmenter.py`` plus a derived uncertainty map.

The uncertainty map is NOT produced by a trained uncertainty head. It is computed from the
model's own output in two ways, both clearly labelled in the interface:

* predictive entropy of the mean probability over a small set of test-time perturbations
  (flip, gamma and contrast changes that lie inside the training augmentation range);
* pixel-wise standard deviation across those perturbed predictions.

Neither is a calibrated measure of error; they indicate where the prediction is unstable.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from . import segmenter as S
from .classifier import CheckpointError


class SegmentationService:
    def __init__(self, path: Path, device: str = "cpu"):
        self.path = Path(path)
        if self.path.suffix.lower() != ".pt":
            raise CheckpointError("unsupported_file", "Segmentation checkpoint must be the .pt bundle file")
        try:
            self.seg = S.TumorSegmenter(self.path, device=device)
        except FileNotFoundError as exc:
            raise CheckpointError("missing_file", str(exc)) from exc
        except KeyError as exc:
            raise CheckpointError(
                "missing_keys", f"Checkpoint lacks the key {exc}; expected 'config' and 'state_dict'"
            ) from exc
        except ModuleNotFoundError as exc:
            raise CheckpointError("missing_dependency", f"{exc}. Install backend/requirements.txt") from exc
        except Exception as exc:
            raise CheckpointError(
                "weights_do_not_match_architecture",
                f"{type(exc).__name__}: {exc}. The state dict must match the U-Net described in the checkpoint config.",
            ) from exc
        self.device = str(self.seg.device)
        self.is_test_fixture = bool(self.seg.config.get("fixture"))
        self.size_mb = self.path.stat().st_size / 1e6

    @property
    def defaults(self) -> Dict[str, Any]:
        return dict(self.seg.defaults)

    def info(self) -> Dict[str, Any]:
        cfg = self.seg.config
        sha = self.seg.model_info.get("weights_sha256", "")
        return {
            "kind": "segmentation",
            "name": cfg.get("model_name", "brisc_tumor_seg"),
            "encoder": cfg.get("arch", {}).get("encoder"),
            "sha256": sha,
            "short_id": sha[:12],
            "input_size": int(cfg["preprocess"]["input_size"]),
            "defaults": self.defaults,
            "segmenter_version": S.__version__,
            "device": self.device,
            "size_mb": round(self.size_mb, 1),
            "limitations": cfg.get("limitations", S.DEFAULT_LIMITATIONS),
            "test_fixture": self.is_test_fixture,
        }

    # -- prediction -----------------------------------------------------------------------------
    def predict_prob(self, gray: np.ndarray, tta: Optional[bool]) -> Tuple[np.ndarray, float]:
        t0 = time.perf_counter()
        prob = self.seg.predict_prob(gray, tta=tta)
        return prob, (time.perf_counter() - t0) * 1000.0

    def finalize(self, prob: np.ndarray, gray: np.ndarray, threshold: Optional[float], tta: bool) -> "S.SegmentationResult":
        return self.seg.finalize(prob, threshold=threshold, original_image=gray, tta=tta)

    # -- uncertainty ----------------------------------------------------------------------------
    def uncertainty(self, gray: np.ndarray, threshold: float) -> Dict[str, Any]:
        """Return maps (float32 in [0, 1]) and summary statistics. See module docstring."""
        t0 = time.perf_counter()
        probs: List[np.ndarray] = []
        for name, fn, inv in _perturbations():
            p = self.seg.predict_prob(fn(gray), tta=False)
            probs.append(inv(p))
        stack = np.stack(probs).astype(np.float32)
        mean_p = stack.mean(0)
        std_p = stack.std(0)
        eps = 1e-6
        ent = -(mean_p * np.log2(mean_p + eps) + (1 - mean_p) * np.log2(1 - mean_p + eps))
        entropy_map = np.clip(ent, 0, 1).astype(np.float32)
        variability_map = np.clip(std_p * 2.0, 0, 1).astype(np.float32)  # std of a probability is at most 0.5

        consensus = (mean_p >= threshold).astype(np.uint8)
        dices = []
        for p in stack:
            m = (p >= threshold).astype(np.uint8)
            inter = int((m & consensus).sum())
            denom = int(m.sum() + consensus.sum())
            dices.append(1.0 if denom == 0 else 2.0 * inter / denom)

        stats: Dict[str, Any] = {
            "n_perturbations": int(len(stack)),
            "stability_dice_mean": float(np.mean(dices)),
            "stability_dice_min": float(np.min(dices)),
            "consensus_area_px": int(consensus.sum()),
            "method": "entropy and std over flip/gamma/contrast perturbations of the model output",
            "calibrated": False,
        }
        if consensus.any():
            k = max(3, int(round(0.02 * max(gray.shape))))
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * k + 1, 2 * k + 1))
            band = (cv2.dilate(consensus, kernel) > 0) & ~(cv2.erode(consensus, kernel) > 0)
            near = cv2.dilate(consensus, kernel) > 0
            unsure = (mean_p > 0.1) & (mean_p < 0.9) & near
            stats.update(
                boundary_entropy_mean=float(entropy_map[band].mean()) if band.any() else None,
                boundary_variability_mean=float(variability_map[band].mean()) if band.any() else None,
                uncertain_pixels_px=int(unsure.sum()),
                uncertain_fraction_of_mask=float(unsure.sum() / consensus.sum()),
            )
        else:
            stats.update(boundary_entropy_mean=None, boundary_variability_mean=None,
                         uncertain_pixels_px=0, uncertain_fraction_of_mask=None)
        stats["inference_ms"] = (time.perf_counter() - t0) * 1000.0
        return {"entropy": entropy_map, "variability": variability_map, "stats": stats}


def _perturbations():
    """(name, forward transform on uint8, inverse transform on the probability map)."""
    ident = lambda a: a  # noqa: E731

    def gamma(g):
        table = (255.0 * (np.arange(256) / 255.0) ** g).clip(0, 255).astype(np.uint8)
        return lambda a: table[a]

    def contrast(c):
        def f(a):
            m = float(a.mean())
            return np.clip((a.astype(np.float32) - m) * c + m, 0, 255).astype(np.uint8)
        return f

    flip = lambda a: np.ascontiguousarray(a[:, ::-1])  # noqa: E731
    return [
        ("identity", ident, ident),
        ("hflip", flip, flip),
        ("gamma_0.82", gamma(0.82), ident),
        ("gamma_1.22", gamma(1.22), ident),
        ("contrast_0.88", contrast(0.88), ident),
        ("contrast_1.12", contrast(1.12), ident),
    ]
