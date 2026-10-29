"""Paths, defaults and user-adjustable settings.

Resolution order for every path: environment variable, then the value saved in the
application settings, then the default below. Model checkpoints are never bundled in the
repository; they are loaded from the configured local paths.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict

APP_NAME = "OncoPixel"
VERSION = "1.0.0"
TAGLINE = "See beyond the image"

# Class order used by the trained classifier (torchvision ImageFolder sorts folder names).
EXPECTED_CLASSES = ("glioma", "meningioma", "no_tumor", "pituitary")

DISCLAIMER_EN = "Designed to assist medical image analysis. Clinical judgment remains essential."
DISCLAIMER_FR = "Conçu pour assister l'analyse d'images médicales. Le jugement clinique reste essentiel."

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
REPO_ROOT = Path(__file__).resolve().parents[2]


def default_data_dir() -> Path:
    env = os.environ.get("ONCOPIXEL_DATA_DIR")
    if env:
        return Path(env).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    if sys.platform.startswith("win"):
        return Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / APP_NAME
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "oncopixel"


def default_models_dir() -> Path:
    env = os.environ.get("ONCOPIXEL_MODELS_DIR")
    if env:
        return Path(env).expanduser()
    in_repo = REPO_ROOT / "models"
    if in_repo.is_dir():
        return in_repo
    return default_data_dir() / "models"


def default_classifier_path() -> Path:
    return default_models_dir() / "classification" / "best.pt"


def default_segmenter_path() -> Path:
    return default_models_dir() / "segmentation" / "tumor_seg_model.pt"


def default_settings(data_dir: Path) -> Dict[str, Any]:
    """Defaults for every persisted setting. Keep this list short: only what users need."""
    return {
        # appearance and display
        "theme": "dark",  # dark | light
        "language": "en",  # en | fr
        "high_contrast": False,
        "font_size": "medium",  # small | medium | large
        "overlay_opacity": 0.45,
        "overlay_color": "#ff5a5f",
        "show_contour": True,
        # export
        "export_dir": str(data_dir / "exports"),
        "report_language": "en",  # en | fr
        "anonymize_exports": False,
        # inference
        "device": "auto",  # auto | mps | cpu | cuda
        "classifier_tta": True,
        "segmenter_tta": None,  # None: use the model's validated default
        "review_threshold": 0.90,  # confidence below this flags the result for human review
        "segmentation_threshold": None,  # None: use the model's validated default
        # models (empty: use defaults / environment)
        "classification_checkpoint": "",
        "segmentation_checkpoint": "",
        # import
        "watch_enabled": False,
        "watch_dir": "",
        "anonymize_dicom_on_import": True,
        "max_image_pixels": 36_000_000,
        "max_file_mb": 200,
        # onboarding
        "welcome_seen": False,
        "tour_done": False,
    }


SETTING_CHOICES = {
    "theme": {"dark", "light"},
    "language": {"en", "fr"},
    "font_size": {"small", "medium", "large"},
    "report_language": {"en", "fr"},
    "device": {"auto", "mps", "cpu", "cuda"},
}
