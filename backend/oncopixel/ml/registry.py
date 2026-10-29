"""Locates, loads, verifies and caches the two models from configurable local paths.

The application never fabricates predictions: when a checkpoint is missing or does not
match its architecture, analysis endpoints raise ``ModelUnavailable`` and the interface
shows the reason.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from ..config import default_classifier_path, default_segmenter_path
from .classifier import CheckpointError, Classifier
from .devices import available_devices, resolve_device
from .segmentation import SegmentationService

KINDS = ("classification", "segmentation")
ENV_VARS = {"classification": "ONCOPIXEL_CLASSIFIER_CKPT", "segmentation": "ONCOPIXEL_SEGMENTER_CKPT"}
SETTING_KEYS = {"classification": "classification_checkpoint", "segmentation": "segmentation_checkpoint"}


class ModelUnavailable(Exception):
    def __init__(self, kind: str, state: str, code: str, detail: str, path: str):
        super().__init__(detail)
        self.kind, self.state, self.code, self.detail, self.path = kind, state, code, detail, path

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, "state": self.state, "code": self.code, "detail": self.detail, "path": self.path}


class ModelRegistry:
    def __init__(self, get_settings: Callable[[], Dict[str, Any]]):
        self._get_settings = get_settings
        self._lock = threading.RLock()
        self._cache: Dict[str, Tuple[Tuple, Any]] = {}
        self._errors: Dict[str, Tuple[Tuple, CheckpointError]] = {}
        self.infer_lock = threading.Lock()  # one inference at a time on an 8 GB machine

    # -- paths ----------------------------------------------------------------------------------
    def path_for(self, kind: str) -> Path:
        env = os.environ.get(ENV_VARS[kind])
        if env:
            return Path(env).expanduser()
        configured = (self._get_settings().get(SETTING_KEYS[kind]) or "").strip()
        if configured:
            return Path(configured).expanduser()
        return default_classifier_path() if kind == "classification" else default_segmenter_path()

    def path_source(self, kind: str) -> str:
        if os.environ.get(ENV_VARS[kind]):
            return "environment"
        return "settings" if (self._get_settings().get(SETTING_KEYS[kind]) or "").strip() else "default"

    def device(self) -> str:
        return resolve_device(str(self._get_settings().get("device", "auto")))

    # -- loading --------------------------------------------------------------------------------
    @staticmethod
    def _file_key(path: Path, device: str) -> Tuple:
        st = path.stat()
        return (str(path), st.st_mtime_ns, st.st_size, device)

    def invalidate(self) -> None:
        with self._lock:
            self._cache.clear()
            self._errors.clear()

    def _load(self, kind: str):
        path = self.path_for(kind)
        if not path.exists():
            raise ModelUnavailable(kind, "missing", "file_not_found", f"No checkpoint at {path}", str(path))
        if not path.is_file():
            raise ModelUnavailable(kind, "invalid", "not_a_file", f"{path} is not a file", str(path))
        device = self.device()
        key = self._file_key(path, device)
        with self._lock:
            hit = self._cache.get(kind)
            if hit and hit[0] == key:
                return hit[1]
            err = self._errors.get(kind)
            if err and err[0] == key:
                raise ModelUnavailable(kind, "invalid", err[1].code, err[1].detail, str(path))
            builder = Classifier if kind == "classification" else SegmentationService
            try:
                try:
                    obj = builder(path, device=device)
                except CheckpointError:
                    raise
                except Exception:
                    if device == "cpu":
                        raise
                    obj = builder(path, device="cpu")  # device problem: fall back to the CPU
                    key = self._file_key(path, "cpu")
            except CheckpointError as exc:
                self._errors[kind] = (key, exc)
                raise ModelUnavailable(kind, "invalid", exc.code, exc.detail, str(path)) from exc
            self._cache[kind] = (key, obj)
            return obj

    def classifier(self) -> Classifier:
        return self._load("classification")

    def segmenter(self) -> SegmentationService:
        return self._load("segmentation")

    # -- reporting ------------------------------------------------------------------------------
    def status(self, kind: str) -> Dict[str, Any]:
        path = self.path_for(kind)
        base: Dict[str, Any] = {
            "kind": kind, "path": str(path), "path_source": self.path_source(kind),
            "exists": path.exists(), "requested_device": self._get_settings().get("device", "auto"),
        }
        try:
            obj = self._load(kind)
        except ModelUnavailable as exc:
            return {**base, "state": exc.state, "code": exc.code, "detail": exc.detail, "info": None}
        return {**base, "state": "ready", "code": None, "detail": None, "info": obj.info()}

    def status_all(self) -> Dict[str, Any]:
        statuses = {k: self.status(k) for k in KINDS}
        return {
            "models": statuses,
            "devices": available_devices(),
            "resolved_device": self.device(),
            "any_test_fixture": any(bool((s.get("info") or {}).get("test_fixture")) for s in statuses.values()),
            "all_ready": all(s["state"] == "ready" for s in statuses.values()),
        }
