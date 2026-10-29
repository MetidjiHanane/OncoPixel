#!/usr/bin/env python3
"""Create RANDOM-WEIGHT test checkpoints and a synthetic phantom image.

These files exist only to exercise the software (loading, shapes, endpoints, exports).
Their predictions are meaningless. Both checkpoints carry ``fixture: true``, so the
application shows an "untrained test model" banner and never presents them as real analysis.

Usage:  python scripts/make_test_fixtures.py [output_dir]
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import torch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

CLASSES = ["glioma", "meningioma", "no_tumor", "pituitary"]


def make_classifier(path: Path, seed: int = 0) -> None:
    import timm

    torch.manual_seed(seed)
    name = "convnext_tiny.fb_in22k_ft_in1k"
    model = timm.create_model(name, pretrained=False, num_classes=len(CLASSES))
    torch.save({"state": model.state_dict(), "classes": CLASSES, "class_to_idx": {c: i for i, c in enumerate(CLASSES)},
                "model": name, "size": 256, "temperature": 1.0, "epoch": 0, "merge_val_into_train": False,
                "fixture": True}, path)


def make_segmenter(path: Path, seed: int = 0) -> None:
    from oncopixel.ml import segmenter as S

    torch.manual_seed(seed)
    arch = {"encoder": "resnet34", "in_channels": 1, "classes": 1, "norm_mean": 0.449, "norm_std": 0.226}
    net = S.SegNet(arch, pretrained=False)
    cfg = {"model_name": "fixture_unet_resnet34", "arch": arch, "preprocess": {"input_size": 512},
           "inference_defaults": {"threshold": 0.5, "tta_hflip": False, "contour_thickness": 1,
                                  "postprocess": {"min_component_area": 0, "keep_largest": False, "fill_holes": False}},
           "fixture": True}
    torch.save({"config": cfg, "state_dict": net.state_dict()}, path)


def phantom(size: int = 256, seed: int = 0) -> np.ndarray:
    """Synthetic head-like ellipse with a bright blob. Not a medical image."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[:size, :size].astype(np.float32)
    c = size / 2
    head = (((xx - c) / (size * 0.38)) ** 2 + ((yy - c) / (size * 0.45)) ** 2) < 1
    img = np.zeros((size, size), np.float32)
    img[head] = 90
    inner = (((xx - c) / (size * 0.33)) ** 2 + ((yy - c) / (size * 0.4)) ** 2) < 1
    img[inner] = 120
    blob = (((xx - c * 1.25) / (size * 0.09)) ** 2 + ((yy - c * 0.85) / (size * 0.07)) ** 2) < 1
    img[blob] = 215
    img += rng.normal(0, 6, img.shape)
    return np.clip(img, 0, 255).astype(np.uint8)


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parent / "tests" / "_fixtures"
    (out / "classification").mkdir(parents=True, exist_ok=True)
    (out / "segmentation").mkdir(parents=True, exist_ok=True)
    make_classifier(out / "classification" / "best.pt")
    make_segmenter(out / "segmentation" / "tumor_seg_model.pt")
    import cv2

    cv2.imwrite(str(out / "phantom.png"), phantom())
    print(f"Fixtures written to {out}\nThese are untrained test models; do not use them for any analysis.")


if __name__ == "__main__":
    main()
