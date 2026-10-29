"""Brain-tumor classifier, rebuilt exactly as in ``brisc_classification.ipynb``.

Checkpoint layout (written by the notebook)::

    {"state": state_dict, "classes": [...], "class_to_idx": {...}, "model": "<timm name>",
     "size": 256, "temperature": float, "epoch": int, "merge_val_into_train": bool}

Preprocessing (notebook ``build_tfms(size, train=False)``): grayscale replicated to three
channels, resize to ``size x size``, ``ToTensor``, ImageNet mean/std normalisation.
Inference: softmax of ``(logits_original + logits_hflip) / 2 / temperature`` (flip TTA is
used in the notebook; it can be switched off in the settings).
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
import numpy as np
import torch
from PIL import Image

from ..config import EXPECTED_CLASSES

MEAN = (0.485, 0.456, 0.406)
STD = (0.229, 0.224, 0.225)
REQUIRED_KEYS = ("state", "classes", "model", "size")


class CheckpointError(Exception):
    """The checkpoint exists but cannot be used. ``code`` is a stable machine-readable reason."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def file_sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


@dataclass
class ClassificationOutput:
    label: str
    confidence: float
    probabilities: Dict[str, float]
    logits: List[float]
    temperature: float
    tta: bool
    inference_ms: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "confidence": self.confidence,
            "probabilities": self.probabilities,
            "temperature": self.temperature,
            "tta": self.tta,
            "inference_ms": self.inference_ms,
        }


class Classifier:
    def __init__(self, path: Path, device: str = "cpu"):
        import timm
        from torchvision import transforms as T

        self.path = Path(path)
        try:
            ckpt = torch.load(self.path, map_location="cpu", weights_only=True)
        except Exception as exc:  # unpickling error, truncated file, wrong format
            raise CheckpointError(
                "unreadable_checkpoint",
                f"torch.load(weights_only=True) failed: {type(exc).__name__}: {exc}. "
                "The file must be the dict saved by the training notebook (plain tensors, lists and numbers).",
            ) from exc
        if not isinstance(ckpt, dict):
            raise CheckpointError("unexpected_format", f"Expected a dict checkpoint, found {type(ckpt).__name__}")
        missing = [k for k in REQUIRED_KEYS if k not in ckpt]
        if missing:
            raise CheckpointError("missing_keys", f"Checkpoint lacks keys {missing}; found {sorted(ckpt.keys())}")

        self.classes: List[str] = [str(c) for c in ckpt["classes"]]
        if tuple(self.classes) != EXPECTED_CLASSES:
            raise CheckpointError(
                "class_order_mismatch",
                f"Checkpoint classes {self.classes} differ from the expected order {list(EXPECTED_CLASSES)}. "
                "The application will not guess a mapping.",
            )
        self.arch_name = str(ckpt["model"])
        self.size = int(ckpt["size"])
        self.temperature = float(ckpt.get("temperature", 1.0))
        self.epoch = ckpt.get("epoch")
        self.is_test_fixture = bool(ckpt.get("fixture"))
        if not (self.temperature > 0):
            raise CheckpointError("bad_temperature", f"Temperature must be positive, found {self.temperature}")

        try:
            model = timm.create_model(self.arch_name, pretrained=False, num_classes=len(self.classes))
        except Exception as exc:
            raise CheckpointError("unknown_architecture", f"timm cannot build '{self.arch_name}': {exc}") from exc
        try:
            model.load_state_dict(ckpt["state"], strict=True)
        except Exception as exc:
            raise CheckpointError(
                "weights_do_not_match_architecture",
                f"State dict does not match timm '{self.arch_name}' with {len(self.classes)} classes: {exc}",
            ) from exc

        self.device = device
        self.model = model.to(device).eval()
        self.tfm = T.Compose([
            T.Grayscale(num_output_channels=3),
            T.Resize((self.size, self.size)),
            T.ToTensor(),
            T.Normalize(MEAN, STD),
        ])
        self.sha256 = file_sha256(self.path)
        self.size_mb = self.path.stat().st_size / 1e6
        self.gradcam_supported = hasattr(self.model, "stages") and len(self.model.stages) > 0

    # -- identity -------------------------------------------------------------------------------
    def info(self) -> Dict[str, Any]:
        return {
            "kind": "classification",
            "name": self.arch_name,
            "sha256": self.sha256,
            "short_id": self.sha256[:12],
            "epoch": self.epoch,
            "input_size": self.size,
            "classes": self.classes,
            "temperature": self.temperature,
            "device": self.device,
            "size_mb": round(self.size_mb, 1),
            "gradcam_supported": self.gradcam_supported,
            "test_fixture": self.is_test_fixture,
        }

    # -- inference ------------------------------------------------------------------------------
    def _tensor(self, gray: np.ndarray) -> torch.Tensor:
        if gray.ndim != 2 or gray.dtype != np.uint8:
            raise ValueError("expected a 2D uint8 grayscale array")
        return self.tfm(Image.fromarray(gray).convert("RGB")).unsqueeze(0)

    def predict(self, gray: np.ndarray, tta: bool = True) -> ClassificationOutput:
        t0 = time.perf_counter()
        x = self._tensor(gray).to(self.device)
        with torch.inference_mode():
            logits = self.model(x).float()
            if tta:
                logits = (logits + self.model(torch.flip(x, dims=[3])).float()) / 2
            probs = torch.softmax(logits / self.temperature, dim=1)[0].cpu()
        conf, idx = probs.max(0)
        return ClassificationOutput(
            label=self.classes[int(idx)],
            confidence=float(conf),
            probabilities={c: float(p) for c, p in zip(self.classes, probs)},
            logits=[float(v) for v in logits[0].cpu()],
            temperature=self.temperature,
            tta=bool(tta),
            inference_ms=(time.perf_counter() - t0) * 1000.0,
        )

    def gradcam(self, gray: np.ndarray, class_index: Optional[int] = None) -> np.ndarray:
        """Grad-CAM on the last ConvNeXt stage, returned at the input resolution in [0, 1].

        Raises ``NotImplementedError`` when the architecture exposes no ``stages`` module.
        """
        if not self.gradcam_supported:
            raise NotImplementedError(f"Grad-CAM target layer not found for architecture {self.arch_name}")
        h, w = gray.shape
        layer = self.model.stages[-1]
        store: Dict[str, torch.Tensor] = {}

        def fwd_hook(_m, _i, out):
            store["act"] = out
            out.register_hook(lambda g: store.__setitem__("grad", g))

        handle = layer.register_forward_hook(fwd_hook)
        try:
            x = self._tensor(gray).to(self.device)
            with torch.enable_grad():
                logits = self.model(x)
                idx = int(logits.argmax(1)) if class_index is None else int(class_index)
                self.model.zero_grad(set_to_none=True)
                logits[0, idx].backward()
        finally:
            handle.remove()
        act, grad = store["act"].detach(), store["grad"].detach()
        weights = grad.mean(dim=(2, 3), keepdim=True)
        cam = torch.relu((weights * act).sum(dim=1, keepdim=True))[0, 0].float().cpu().numpy()
        cam = cv2.resize(cam, (w, h), interpolation=cv2.INTER_LINEAR)
        peak = float(cam.max())
        return (cam / peak).astype(np.float32) if peak > 0 else np.zeros_like(cam, dtype=np.float32)
