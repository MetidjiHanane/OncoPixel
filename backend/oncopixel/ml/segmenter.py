"""
segmenter.py -- inference and evaluation interface for the BRISC 2D brain-tumor
segmentation model ("Model 2").

Design
------
* One code path for training-time evaluation, notebook evaluation and desktop
  inference: the notebook imports this module, so the preprocessing, probability
  back-projection, thresholding, post-processing and metric definitions used to
  report results are the ones the application executes.
* Two interchangeable backends: PyTorch (``tumor_seg_model.pt``) and ONNX Runtime
  (``tumor_seg.onnx``). The ONNX backend needs only numpy, OpenCV and onnxruntime.
* The network always outputs a probability map. Thresholding, post-processing and
  contour extraction are cheap, network-free steps (``rethreshold``) so a viewer can
  expose a live threshold control without re-running the model.

Geometry conventions
--------------------
* Input is converted to 8-bit grayscale, letterboxed (aspect preserved, zero padded)
  to ``S x S`` and scaled to [0, 1]. The probability map is cropped and resized back to
  the original ``H x W``; every returned array is aligned with the input pixel grid.
* ``binary_mask``  : uint8 {0, 1}, shape (H, W), ``prob_map >= threshold`` (+ optional post-processing).
* ``contour_mask`` : uint8 {0, 255}, shape (H, W), closed boundary curve of ``binary_mask``.
* ``contours``     : polylines in original-pixel coordinates (x = column, y = row of the
  boundary pixel; add 0.5 for continuous pixel-centre coordinates).

Limitations are recorded in the model config and returned with every result; the model
is trained on T1-weighted BRISC slices only and carries no validity guarantee for other
sequences, scanners or populations. It is not a medical device.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import cv2
import numpy as np

try:  # the ONNX backend must work without torch installed
    import torch
    import torch.nn as nn

    _HAS_TORCH = True
except Exception:  # pragma: no cover
    torch = None  # type: ignore
    nn = None  # type: ignore
    _HAS_TORCH = False

__version__ = "1.0.0"
SCHEMA_VERSION = "1.0"

ImageSource = Union[str, Path, np.ndarray, Any]  # Any: PIL.Image.Image

DEFAULT_LIMITATIONS = (
    "Trained on 2D T1-weighted BRISC slices (glioma, meningioma, pituitary tumor; axial, "
    "sagittal, coronal) with an image-level split; patient-level independence was not "
    "established. No validity is claimed for other MRI sequences, scanners, protocols or "
    "populations. Overlap metrics (Dice, IoU) require a reference mask and cannot be "
    "computed for an unlabeled scan. Research use only; not a medical device."
)


# --------------------------------------------------------------------------------------
# Image / mask I/O
# --------------------------------------------------------------------------------------
def _to_uint8(arr: np.ndarray) -> np.ndarray:
    """Best-effort conversion to uint8. Callers should supply 8-bit data."""
    if arr.dtype == np.uint8:
        return arr
    a = arr.astype(np.float64)
    if np.issubdtype(arr.dtype, np.floating):
        mx = float(np.nanmax(a)) if a.size else 0.0
        if mx <= 1.0 + 1e-6:
            a = a * 255.0
        return np.clip(np.rint(np.nan_to_num(a)), 0, 255).astype(np.uint8)
    mx = float(a.max()) if a.size else 0.0
    if mx > 255.0:  # >8-bit integer data: scale by the image maximum
        a = a * (255.0 / mx)
    return np.clip(np.rint(a), 0, 255).astype(np.uint8)


def load_gray_uint8(src: ImageSource) -> np.ndarray:
    """Load a path, ndarray or PIL image as a contiguous (H, W) uint8 grayscale array.

    Paths are decoded with ``cv2.imdecode`` (Unicode-safe on Windows). Colour input is
    converted with ITU-R 601 luma weights; ndarray input is assumed RGB, decoded files BGR.
    """
    from_file = False
    if isinstance(src, (str, Path)):
        buf = np.fromfile(str(src), dtype=np.uint8)
        arr = cv2.imdecode(buf, cv2.IMREAD_UNCHANGED)
        if arr is None:
            raise ValueError(f"Cannot decode image: {src}")
        from_file = True
    elif isinstance(src, np.ndarray):
        arr = src
    else:  # PIL image or array-like
        arr = np.asarray(src)
    arr = _to_uint8(np.asarray(arr))
    if arr.ndim == 3:
        ch = arr.shape[2]
        if ch == 1:
            arr = arr[..., 0]
        elif ch == 2:
            arr = arr[..., 0]
        else:
            code = cv2.COLOR_BGR2GRAY if from_file else cv2.COLOR_RGB2GRAY
            arr = cv2.cvtColor(np.ascontiguousarray(arr[..., :3]), code)
    if arr.ndim != 2:
        raise ValueError(f"Expected a 2D image, got array of shape {arr.shape}")
    return np.ascontiguousarray(arr)


def load_mask_raw(path: Union[str, Path]) -> Tuple[np.ndarray, str]:
    """Read a mask PNG as raw uint8 values without any thresholding.

    Returns ``(array, pil_mode)``. Palette masks return their indices, 16-bit masks are
    rescaled to 0..255, RGB(A) masks are reduced to luma.
    """
    from PIL import Image

    with Image.open(path) as im:
        mode = im.mode
        if mode == "P":
            arr = np.array(im)
        elif mode in ("L", "1"):
            arr = np.array(im.convert("L"))
        elif mode.startswith("I") or mode == "F":
            a = np.array(im).astype(np.float64)
            arr = np.clip(a * (255.0 / 65535.0) if a.max() > 255 else a, 0, 255).astype(np.uint8)
        else:
            arr = np.array(im.convert("L"))
    return np.ascontiguousarray(arr.astype(np.uint8, copy=False)), mode


def binarize_mask(raw: np.ndarray, threshold: int) -> np.ndarray:
    """Foreground = raw > threshold. Returns uint8 {0, 1}."""
    return (raw > threshold).astype(np.uint8)


# --------------------------------------------------------------------------------------
# Letterbox geometry
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class LetterboxMeta:
    orig_h: int
    orig_w: int
    size: int
    scale: float
    new_h: int
    new_w: int
    pad_top: int
    pad_left: int

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


def letterbox(
    img: np.ndarray, size: int, interpolation: Optional[int] = None, pad_value: float = 0
) -> Tuple[np.ndarray, LetterboxMeta]:
    """Resize the longer side to ``size`` (aspect preserved) and centre on a square canvas."""
    h, w = img.shape[:2]
    scale = size / float(max(h, w))
    new_h = max(1, int(round(h * scale)))
    new_w = max(1, int(round(w * scale)))
    if (new_h, new_w) != (h, w):
        interp = interpolation if interpolation is not None else (
            cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
        )
        resized = cv2.resize(img, (new_w, new_h), interpolation=interp)
    else:
        resized = img
    pad_top = (size - new_h) // 2
    pad_left = (size - new_w) // 2
    canvas = np.full((size, size), pad_value, dtype=img.dtype)
    canvas[pad_top : pad_top + new_h, pad_left : pad_left + new_w] = resized
    return canvas, LetterboxMeta(h, w, size, scale, new_h, new_w, pad_top, pad_left)


def unletterbox(
    square: np.ndarray, meta: LetterboxMeta, interpolation: int = cv2.INTER_LINEAR
) -> np.ndarray:
    """Inverse of :func:`letterbox` for a map defined on the square canvas."""
    crop = square[meta.pad_top : meta.pad_top + meta.new_h, meta.pad_left : meta.pad_left + meta.new_w]
    if (meta.new_h, meta.new_w) != (meta.orig_h, meta.orig_w):
        crop = cv2.resize(crop, (meta.orig_w, meta.orig_h), interpolation=interpolation)
    return np.ascontiguousarray(crop)


def letterbox_mask(mask_bin: np.ndarray, size: int) -> Tuple[np.ndarray, LetterboxMeta]:
    """Letterbox a binary mask; interpolated at float precision then re-binarised at 0.5."""
    canvas, meta = letterbox(mask_bin.astype(np.float32), size, pad_value=0.0)
    return (canvas > 0.5).astype(np.uint8), meta


# --------------------------------------------------------------------------------------
# Post-processing, contours, boundary
# --------------------------------------------------------------------------------------
@dataclass
class PostProcessConfig:
    """Mask clean-up applied after thresholding (all disabled by default).

    ``min_component_area`` drops 8-connected components smaller than this many pixels at
    original resolution but never removes the largest component, so a detected tumor
    cannot be erased entirely. ``keep_largest`` retains only the largest component.
    ``fill_holes`` fills interior holes. Order: small-component removal, largest-component
    selection, hole filling.
    """

    min_component_area: int = 0
    keep_largest: bool = False
    fill_holes: bool = False

    @classmethod
    def from_any(cls, value: Union[None, "PostProcessConfig", Dict[str, Any]]) -> "PostProcessConfig":
        if value is None:
            return cls()
        if isinstance(value, cls):
            return value
        return cls(
            min_component_area=int(value.get("min_component_area", 0)),
            keep_largest=bool(value.get("keep_largest", False)),
            fill_holes=bool(value.get("fill_holes", False)),
        )

    @property
    def is_noop(self) -> bool:
        return self.min_component_area <= 0 and not self.keep_largest and not self.fill_holes

    @property
    def name(self) -> str:
        parts = []
        if self.min_component_area > 0:
            parts.append(f"min_area={self.min_component_area}")
        if self.keep_largest:
            parts.append("keep_largest")
        if self.fill_holes:
            parts.append("fill_holes")
        return "+".join(parts) if parts else "none"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "min_component_area": int(self.min_component_area),
            "keep_largest": bool(self.keep_largest),
            "fill_holes": bool(self.fill_holes),
        }


def apply_threshold(prob: np.ndarray, threshold: float) -> np.ndarray:
    """Foreground = prob >= threshold. Returns uint8 {0, 1}."""
    return (prob >= float(threshold)).astype(np.uint8)


def postprocess_mask(mask: np.ndarray, cfg: Union[None, PostProcessConfig, Dict[str, Any]]) -> np.ndarray:
    cfg = PostProcessConfig.from_any(cfg)
    m = (mask > 0).astype(np.uint8)
    if cfg.is_noop or not m.any():
        return m
    if cfg.min_component_area > 0 or cfg.keep_largest:
        n, labels, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
        if n > 2:  # more than one foreground component
            areas = stats[1:, cv2.CC_STAT_AREA]
            largest = 1 + int(np.argmax(areas))
            keep = np.zeros(n, dtype=bool)
            keep[largest] = True
            if not cfg.keep_largest:
                keep[1:] |= areas >= cfg.min_component_area
            m = keep[labels].astype(np.uint8)
    if cfg.fill_holes:
        contours, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        filled = np.zeros_like(m)
        cv2.drawContours(filled, contours, -1, 1, thickness=cv2.FILLED)
        m = filled
    return m


@dataclass
class Contour:
    points: np.ndarray  # (N, 2) float32, columns (x, y) in original-pixel coordinates
    is_hole: bool

    def to_dict(self) -> Dict[str, Any]:
        return {"is_hole": bool(self.is_hole), "points": self.points.astype(float).tolist()}


def _find_contours(mask: np.ndarray):
    m = np.ascontiguousarray((mask > 0).astype(np.uint8))
    contours, hierarchy = cv2.findContours(m, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    return contours, hierarchy


def mask_to_contours(mask: np.ndarray) -> List[Contour]:
    contours, hierarchy = _find_contours(mask)
    out: List[Contour] = []
    for i, c in enumerate(contours):
        is_hole = bool(hierarchy is not None and hierarchy[0][i][3] != -1)
        out.append(Contour(points=c[:, 0, :].astype(np.float32), is_hole=is_hole))
    return out


def contour_mask_from_mask(mask: np.ndarray, thickness: int = 1) -> np.ndarray:
    """Closed boundary curve of ``mask`` as uint8 {0, 255}; ``thickness`` in pixels."""
    contours, _ = _find_contours(mask)
    canvas = np.zeros(mask.shape[:2], dtype=np.uint8)
    if contours:
        cv2.drawContours(canvas, contours, -1, 255, thickness=int(max(1, thickness)))
    return canvas


def _inner_boundary(mask_u8: np.ndarray) -> np.ndarray:
    er = cv2.erode(mask_u8, np.ones((3, 3), np.uint8), borderType=cv2.BORDER_CONSTANT, borderValue=0)
    return (mask_u8 > 0) & (er == 0)


# --------------------------------------------------------------------------------------
# Rendering helpers (viewer-agnostic; the desktop application can reimplement these)
# --------------------------------------------------------------------------------------
def render_overlay(
    gray: np.ndarray,
    mask: np.ndarray,
    opacity: float = 0.4,
    color: Tuple[int, int, int] = (255, 0, 0),
    contour: Optional[np.ndarray] = None,
    contour_color: Tuple[int, int, int] = (255, 255, 0),
) -> np.ndarray:
    """RGB uint8 image: translucent filled mask plus an optional opaque contour."""
    rgb = np.repeat(gray[..., None], 3, axis=2).astype(np.float32)
    m = (mask > 0)[..., None]
    col = np.array(color, dtype=np.float32).reshape(1, 1, 3)
    rgb = np.where(m, (1.0 - opacity) * rgb + opacity * col, rgb)
    if contour is not None:
        rgb[contour > 0] = np.array(contour_color, dtype=np.float32)
    return np.clip(rgb, 0, 255).astype(np.uint8)


def render_probability(prob: np.ndarray) -> np.ndarray:
    cm = cv2.applyColorMap((np.clip(prob, 0, 1) * 255).astype(np.uint8), cv2.COLORMAP_JET)
    return cv2.cvtColor(cm, cv2.COLOR_BGR2RGB)


# --------------------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------------------
def confusion_counts(pred: np.ndarray, gt: np.ndarray) -> Dict[str, int]:
    p = pred.astype(bool)
    g = gt.astype(bool)
    if p.shape != g.shape:
        raise ValueError(f"pred {p.shape} and gt {g.shape} must have the same shape")
    tp = int(np.count_nonzero(p & g))
    fp = int(np.count_nonzero(p)) - tp
    fn = int(np.count_nonzero(g)) - tp
    tn = int(p.size) - tp - fp - fn
    return {"TP": tp, "FP": fp, "TN": tn, "FN": fn}


def metrics_from_counts(tp: int, fp: int, tn: int, fn: int) -> Dict[str, float]:
    """Overlap metrics from pixel counts.

    Empty-mask conventions (documented in the training notebook):
      * reference and prediction both empty -> Dice = IoU = 1;
      * exactly one of them empty            -> Dice = IoU = 0;
      * a ratio whose denominator is zero is undefined and returned as NaN
        (precision when nothing is predicted, recall when the reference is empty).
    """
    nan = float("nan")
    gt_pos, pred_pos = tp + fn, tp + fp
    if gt_pos == 0 and pred_pos == 0:
        dice = iou = 1.0
    elif tp == 0:
        dice = iou = 0.0
    else:
        dice = 2.0 * tp / (2.0 * tp + fp + fn)
        iou = tp / float(tp + fp + fn)
    total = tp + fp + tn + fn
    return {
        "dice": dice,
        "iou": iou,
        "precision": tp / pred_pos if pred_pos > 0 else nan,
        "recall": tp / gt_pos if gt_pos > 0 else nan,
        "specificity": tn / (tn + fp) if (tn + fp) > 0 else nan,
        "pixel_accuracy": (tp + tn) / total if total > 0 else nan,
    }


def surface_distance_metrics(pred: np.ndarray, gt: np.ndarray) -> Tuple[float, float]:
    """Symmetric 95th-percentile Hausdorff distance and average surface distance, in pixels.

    Distances are measured between inner boundary pixels. NaN if either mask is empty.
    """
    p = (pred > 0).astype(np.uint8)
    g = (gt > 0).astype(np.uint8)
    if not p.any() or not g.any():
        return float("nan"), float("nan")
    pb, gb = _inner_boundary(p), _inner_boundary(g)
    dt_to_g = cv2.distanceTransform((~gb).astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    dt_to_p = cv2.distanceTransform((~pb).astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    d_pg, d_gp = dt_to_g[pb], dt_to_p[gb]
    both = np.concatenate([d_pg, d_gp])
    return float(np.percentile(both, 95)), float(0.5 * (d_pg.mean() + d_gp.mean()))


def segmentation_metrics(pred: np.ndarray, gt: np.ndarray, with_surface: bool = True) -> Dict[str, float]:
    """Counts, overlap metrics and (optionally) surface distances for one image pair."""
    counts = confusion_counts(pred, gt)
    out: Dict[str, float] = dict(counts)
    out.update(metrics_from_counts(counts["TP"], counts["FP"], counts["TN"], counts["FN"]))
    if with_surface:
        out["hd95_px"], out["assd_px"] = surface_distance_metrics(pred, gt)
    return out


# --------------------------------------------------------------------------------------
# Network
# --------------------------------------------------------------------------------------
if _HAS_TORCH:

    class SegNet(nn.Module):
        """U-Net with a configurable encoder. Input (B, 1, H, W) in [0, 1]; output logits.

        Intensity standardisation is part of the graph, so exported models consume raw
        [0, 1] pixels.
        """

        def __init__(self, arch: Dict[str, Any], pretrained: bool = False):
            super().__init__()
            import segmentation_models_pytorch as smp

            self.net = smp.Unet(
                encoder_name=arch["encoder"],
                encoder_weights="imagenet" if pretrained else None,
                in_channels=int(arch.get("in_channels", 1)),
                classes=int(arch.get("classes", 1)),
            )
            self.register_buffer("norm_mean", torch.tensor(float(arch.get("norm_mean", 0.449))).view(1, 1, 1, 1))
            self.register_buffer("norm_std", torch.tensor(float(arch.get("norm_std", 0.226))).view(1, 1, 1, 1))

        def forward(self, x):  # type: ignore[override]
            return self.net((x - self.norm_mean) / self.norm_std)


def file_sha256(path: Union[str, Path], chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


# --------------------------------------------------------------------------------------
# Result container
# --------------------------------------------------------------------------------------
@dataclass
class SegmentationResult:
    prob_map: np.ndarray  # (H, W) float32 in [0, 1], original resolution
    binary_mask: np.ndarray  # (H, W) uint8 {0, 1}
    contour_mask: np.ndarray  # (H, W) uint8 {0, 255}
    contours: List[Contour]
    threshold: float
    original_size: Tuple[int, int]  # (H, W)
    model_input_size: Tuple[int, int]  # (S, S) network input
    model_output_size: Tuple[int, int]  # (S, S) network output before back-projection
    letterbox: Dict[str, Any]
    postprocess: Dict[str, Any]
    tta_hflip: bool
    contour_thickness: int = 1
    original_image: Optional[np.ndarray] = None  # (H, W) uint8
    image_path: Optional[str] = None
    model_info: Dict[str, Any] = field(default_factory=dict)

    # ---- derived quantities ----
    @property
    def tumor_detected(self) -> bool:
        return bool(self.binary_mask.any())

    @property
    def tumor_area_px(self) -> int:
        return int(np.count_nonzero(self.binary_mask))

    @property
    def tumor_area_fraction(self) -> float:
        return self.tumor_area_px / float(self.binary_mask.size)

    @property
    def bbox_xyxy(self) -> Optional[List[int]]:
        ys, xs = np.nonzero(self.binary_mask)
        if ys.size == 0:
            return None
        return [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]

    @property
    def n_components(self) -> int:
        if not self.tumor_detected:
            return 0
        return int(cv2.connectedComponents(self.binary_mask, connectivity=8)[0] - 1)

    # ---- viewer support ----
    def render(
        self,
        mode: str = "overlay",
        opacity: float = 0.4,
        color: Tuple[int, int, int] = (255, 0, 0),
        show_contour: bool = True,
        contour_color: Tuple[int, int, int] = (255, 255, 0),
    ) -> np.ndarray:
        """RGB uint8 view: 'original' | 'probability' | 'mask' | 'overlay' | 'contour'."""
        if self.original_image is None and mode in ("original", "overlay", "contour"):
            raise ValueError("original_image was not retained; call predict(..., include_image=True)")
        if mode == "original":
            return np.repeat(self.original_image[..., None], 3, axis=2)
        if mode == "probability":
            return render_probability(self.prob_map)
        if mode == "mask":
            return np.repeat((self.binary_mask * 255)[..., None], 3, axis=2).astype(np.uint8)
        if mode == "overlay":
            return render_overlay(
                self.original_image, self.binary_mask, opacity, color,
                self.contour_mask if show_contour else None, contour_color,
            )
        if mode == "contour":
            return render_overlay(
                self.original_image, np.zeros_like(self.binary_mask), 0.0, color,
                self.contour_mask, contour_color,
            )
        raise ValueError(f"unknown render mode: {mode}")

    def to_metadata(self, include_contours: bool = True) -> Dict[str, Any]:
        """JSON-serialisable description of the result (no pixel arrays)."""
        h, w = self.original_size
        meta: Dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "image_path": self.image_path,
            "original_size": {"height": int(h), "width": int(w)},
            "model_input_size": {"height": int(self.model_input_size[0]), "width": int(self.model_input_size[1])},
            "model_output_size": {"height": int(self.model_output_size[0]), "width": int(self.model_output_size[1])},
            "letterbox": self.letterbox,
            "threshold": float(self.threshold),
            "threshold_rule": "binary_mask = prob_map >= threshold",
            "tta_hflip": bool(self.tta_hflip),
            "postprocess": self.postprocess,
            "contour_thickness": int(self.contour_thickness),
            "tumor_detected": self.tumor_detected,
            "tumor_area_px": self.tumor_area_px,
            "tumor_area_fraction": self.tumor_area_fraction,
            "bbox_xyxy": self.bbox_xyxy,
            "n_components": self.n_components,
            "contour_coordinates": "x=column, y=row of boundary pixel, original image grid",
            "model_info": self.model_info,
        }
        if include_contours:
            meta["contours"] = [c.to_dict() for c in self.contours]
        return meta

    def save(self, out_dir: Union[str, Path], stem: Optional[str] = None, save_npy: bool = True) -> Dict[str, str]:
        """Write prob (16-bit PNG [+ float32 npy]), mask, contour, overlay and JSON metadata."""
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        if stem is None:
            stem = Path(self.image_path).stem if self.image_path else "result"
        paths: Dict[str, str] = {}

        def _write_png(name: str, arr: np.ndarray) -> None:
            ok, buf = cv2.imencode(".png", arr)
            if not ok:
                raise RuntimeError(f"PNG encoding failed for {name}")
            p = out_dir / f"{stem}_{name}.png"
            buf.tofile(str(p))
            paths[name] = str(p)

        _write_png("prob16", np.rint(np.clip(self.prob_map, 0, 1) * 65535.0).astype(np.uint16))
        _write_png("mask", (self.binary_mask * 255).astype(np.uint8))
        _write_png("contour", self.contour_mask)
        if self.original_image is not None:
            _write_png("overlay", cv2.cvtColor(self.render("overlay"), cv2.COLOR_RGB2BGR))
        if save_npy:
            p = out_dir / f"{stem}_prob.npy"
            np.save(p, self.prob_map.astype(np.float32))
            paths["prob_npy"] = str(p)
        p = out_dir / f"{stem}_result.json"
        p.write_text(json.dumps(self.to_metadata(), indent=2))
        paths["json"] = str(p)
        return paths


# --------------------------------------------------------------------------------------
# Segmenter
# --------------------------------------------------------------------------------------
class TumorSegmenter:
    """Loads a Model-2 bundle and exposes ``predict`` / ``rethreshold``.

    Parameters
    ----------
    model_path : ``.pt`` (PyTorch) or ``.onnx`` (ONNX Runtime) file produced by the notebook.
    config_path : ``inference_config.json``; required for ``.onnx`` unless it sits next to the model.
    device : ``"auto"``, ``"cpu"``, ``"cuda"`` (torch backend) -- ONNX picks CUDA when available.
    """

    def __init__(
        self,
        model_path: Union[str, Path],
        config_path: Optional[Union[str, Path]] = None,
        device: str = "auto",
    ):
        model_path = Path(model_path)
        if not model_path.exists():
            raise FileNotFoundError(model_path)
        suffix = model_path.suffix.lower()
        self.model_path = model_path
        if suffix == ".pt":
            if not _HAS_TORCH:
                raise RuntimeError("PyTorch is not installed; use the .onnx model instead")
            self.backend = "torch"
            try:
                ckpt = torch.load(model_path, map_location="cpu", weights_only=True)
            except TypeError:  # torch < 1.13
                ckpt = torch.load(model_path, map_location="cpu")
            self.config: Dict[str, Any] = ckpt["config"]
            self.device = torch.device(
                ("cuda" if torch.cuda.is_available() else "cpu") if device == "auto" else device
            )
            self.model = SegNet(self.config["arch"], pretrained=False)
            self.model.load_state_dict(ckpt["state_dict"])
            self.model.to(self.device).eval()
        elif suffix == ".onnx":
            import onnxruntime as ort

            cfg_path = Path(config_path) if config_path else model_path.with_name("inference_config.json")
            if not cfg_path.exists():
                raise FileNotFoundError(f"inference_config.json not found at {cfg_path}")
            self.config = json.loads(cfg_path.read_text())
            avail = ort.get_available_providers()
            want = [p for p in ("CUDAExecutionProvider", "CPUExecutionProvider") if p in avail]
            if device == "cpu":
                want = ["CPUExecutionProvider"]
            self.backend = "onnx"
            self.session = ort.InferenceSession(str(model_path), providers=want)
            self.input_name = self.session.get_inputs()[0].name
            self.device = want[0]
        else:
            raise ValueError(f"unsupported model file: {model_path}")

        self.input_size = int(self.config["preprocess"]["input_size"])
        self.defaults: Dict[str, Any] = dict(self.config.get("inference_defaults", {}))
        self.model_info: Dict[str, Any] = {
            "name": self.config.get("model_name", "brisc_tumor_seg"),
            "backend": self.backend,
            "weights_sha256": file_sha256(model_path),
            "encoder": self.config["arch"].get("encoder"),
            "segmenter_version": __version__,
            "limitations": self.config.get("limitations", DEFAULT_LIMITATIONS),
        }

    @classmethod
    def from_bundle(cls, bundle_dir: Union[str, Path], backend: str = "auto", device: str = "auto") -> "TumorSegmenter":
        bundle_dir = Path(bundle_dir)
        pt, onnx_p = bundle_dir / "tumor_seg_model.pt", bundle_dir / "tumor_seg.onnx"
        if backend == "auto":
            backend = "torch" if (_HAS_TORCH and pt.exists()) else "onnx"
        if backend == "torch":
            return cls(pt, device=device)
        return cls(onnx_p, config_path=bundle_dir / "inference_config.json", device=device)

    # ---- network forward ----
    def _forward(self, batch: np.ndarray) -> np.ndarray:
        """(B, 1, S, S) float32 in [0, 1] -> (B, S, S) float32 probabilities."""
        if self.backend == "torch":
            with torch.inference_mode():
                x = torch.from_numpy(np.ascontiguousarray(batch)).to(self.device)
                return torch.sigmoid(self.model(x))[:, 0].float().cpu().numpy()
        out = self.session.run(None, {self.input_name: np.ascontiguousarray(batch, dtype=np.float32)})[0]
        return out[:, 0]

    def _probs_from_grays(self, grays: Sequence[np.ndarray], tta: bool, batch_size: int) -> List[np.ndarray]:
        S = self.input_size
        out: List[np.ndarray] = []
        for i in range(0, len(grays), batch_size):
            chunk = grays[i : i + batch_size]
            canvases, metas = zip(*[letterbox(g, S) for g in chunk])
            x = (np.stack(canvases).astype(np.float32) / 255.0)[:, None]
            p = self._forward(x)
            if tta:
                p = 0.5 * (p + self._forward(np.ascontiguousarray(x[..., ::-1]))[..., ::-1])
            for pi, m in zip(p, metas):
                out.append(np.clip(unletterbox(np.ascontiguousarray(pi, dtype=np.float32), m), 0.0, 1.0))
        return out

    # ---- public API ----
    def predict_prob(self, source: ImageSource, tta: Optional[bool] = None) -> np.ndarray:
        """Probability map (H, W) float32 aligned with the input pixel grid."""
        tta = bool(self.defaults.get("tta_hflip", False)) if tta is None else bool(tta)
        return self._probs_from_grays([load_gray_uint8(source)], tta, 1)[0]

    def predict_probs(self, sources: Sequence[ImageSource], tta: Optional[bool] = None, batch_size: int = 8) -> List[np.ndarray]:
        tta = bool(self.defaults.get("tta_hflip", False)) if tta is None else bool(tta)
        return self._probs_from_grays([load_gray_uint8(s) for s in sources], tta, batch_size)

    def finalize(
        self,
        prob_map: np.ndarray,
        threshold: Optional[float] = None,
        postprocess: Union[None, PostProcessConfig, Dict[str, Any]] = None,
        original_image: Optional[np.ndarray] = None,
        image_path: Optional[str] = None,
        tta: bool = False,
        contour_thickness: Optional[int] = None,
    ) -> SegmentationResult:
        """Network-free step: threshold -> post-process -> contours -> result."""
        thr = float(self.defaults.get("threshold", 0.5) if threshold is None else threshold)
        pp = PostProcessConfig.from_any(
            self.defaults.get("postprocess") if postprocess is None else postprocess
        )
        thick = int(self.defaults.get("contour_thickness", 1) if contour_thickness is None else contour_thickness)
        mask = postprocess_mask(apply_threshold(prob_map, thr), pp)
        h, w = prob_map.shape
        S = self.input_size
        _, meta = letterbox(np.zeros((h, w), np.uint8), S)
        return SegmentationResult(
            prob_map=prob_map.astype(np.float32, copy=False),
            binary_mask=mask,
            contour_mask=contour_mask_from_mask(mask, thick),
            contours=mask_to_contours(mask),
            threshold=thr,
            original_size=(h, w),
            model_input_size=(S, S),
            model_output_size=(S, S),
            letterbox=meta.to_dict(),
            postprocess=pp.to_dict(),
            tta_hflip=bool(tta),
            contour_thickness=thick,
            original_image=original_image,
            image_path=image_path,
            model_info=dict(self.model_info),
        )

    def predict(
        self,
        source: ImageSource,
        threshold: Optional[float] = None,
        postprocess: Union[None, PostProcessConfig, Dict[str, Any]] = None,
        tta: Optional[bool] = None,
        include_image: bool = True,
    ) -> SegmentationResult:
        """Segment one 2D image. ``None`` arguments fall back to the validation-tuned defaults."""
        tta = bool(self.defaults.get("tta_hflip", False)) if tta is None else bool(tta)
        gray = load_gray_uint8(source)
        prob = self._probs_from_grays([gray], tta, 1)[0]
        path = str(source) if isinstance(source, (str, Path)) else None
        return self.finalize(prob, threshold, postprocess, gray if include_image else None, path, tta)

    def predict_batch(
        self,
        sources: Sequence[ImageSource],
        threshold: Optional[float] = None,
        postprocess: Union[None, PostProcessConfig, Dict[str, Any]] = None,
        tta: Optional[bool] = None,
        include_image: bool = True,
        batch_size: int = 8,
    ) -> List[SegmentationResult]:
        tta = bool(self.defaults.get("tta_hflip", False)) if tta is None else bool(tta)
        grays = [load_gray_uint8(s) for s in sources]
        probs = self._probs_from_grays(grays, tta, batch_size)
        results = []
        for s, g, p in zip(sources, grays, probs):
            path = str(s) if isinstance(s, (str, Path)) else None
            results.append(self.finalize(p, threshold, postprocess, g if include_image else None, path, tta))
        return results

    def rethreshold(
        self,
        result: SegmentationResult,
        threshold: Optional[float] = None,
        postprocess: Union[None, PostProcessConfig, Dict[str, Any]] = None,
        contour_thickness: Optional[int] = None,
    ) -> SegmentationResult:
        """Recompute mask, contour and metadata from a stored probability map (no network call)."""
        return self.finalize(
            result.prob_map, threshold, postprocess, result.original_image, result.image_path,
            result.tta_hflip, contour_thickness,
        )


__all__ = [
    "SegmentationResult", "TumorSegmenter", "PostProcessConfig", "Contour", "LetterboxMeta",
    "load_gray_uint8", "load_mask_raw", "binarize_mask", "letterbox", "unletterbox", "letterbox_mask",
    "apply_threshold", "postprocess_mask", "mask_to_contours", "contour_mask_from_mask",
    "render_overlay", "render_probability", "confusion_counts", "metrics_from_counts",
    "surface_distance_metrics", "segmentation_metrics", "file_sha256", "DEFAULT_LIMITATIONS",
] + (["SegNet"] if _HAS_TORCH else [])
