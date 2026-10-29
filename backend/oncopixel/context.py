"""Application context shared by all routers: database, vault, file store, models, sessions."""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from .config import SETTING_CHOICES, default_data_dir
from .db import Database, FileStore
from .ml.registry import ModelRegistry
from .security import SessionStore, Vault


class AppContext:
    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = Path(data_dir) if data_dir else default_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db = Database(self.data_dir / "oncopixel.db")
        self.vault = Vault(self.data_dir)
        self.files = FileStore(self.data_dir / "files", self.vault)
        self.sessions = SessionStore()
        self._settings_cache: Optional[Dict[str, Any]] = None
        self._settings_lock = threading.Lock()
        self.models = ModelRegistry(self.settings)
        self.app_token = os.environ.get("ONCOPIXEL_APP_TOKEN", "")
        self.watcher = None  # set by the application factory

    # -- settings ---------------------------------------------------------------------------------
    def settings(self) -> Dict[str, Any]:
        with self._settings_lock:
            if self._settings_cache is None:
                self._settings_cache = self.db.load_settings(self.data_dir)
            return dict(self._settings_cache)

    def update_settings(self, changes: Dict[str, Any]) -> Dict[str, Any]:
        current = self.settings()
        for key, value in changes.items():
            if key not in current:
                raise KeyError(key)
            allowed = SETTING_CHOICES.get(key)
            if allowed is not None and value not in allowed:
                raise ValueError(f"{key} must be one of {sorted(allowed)}")
            if key in ("review_threshold",) and not (0.0 < float(value) <= 1.0):
                raise ValueError("review_threshold must be in (0, 1]")
            if key in ("segmentation_threshold",) and value is not None and not (0.0 < float(value) < 1.0):
                raise ValueError("segmentation_threshold must be in (0, 1) or null")
            if key == "overlay_opacity" and not (0.0 <= float(value) <= 1.0):
                raise ValueError("overlay_opacity must be in [0, 1]")
            self.db.save_setting(key, value)
        with self._settings_lock:
            self._settings_cache = None
        if {"device", "classification_checkpoint", "segmentation_checkpoint"} & set(changes):
            self.models.invalidate()
        return self.settings()

    def export_dir(self) -> Path:
        p = Path(self.settings()["export_dir"]).expanduser()
        p.mkdir(parents=True, exist_ok=True)
        return p

    # -- lifecycle ---------------------------------------------------------------------------------
    def reopen(self) -> None:
        """Reload database, vault and file store after a restore replaced the data directory."""
        try:
            self.db.close()
        except Exception:
            pass
        self.db = Database(self.data_dir / "oncopixel.db")
        self.vault = Vault(self.data_dir)
        self.files = FileStore(self.data_dir / "files", self.vault)
        self.sessions.clear()
        with self._settings_lock:
            self._settings_cache = None
        self.models.invalidate()

    def close(self) -> None:
        if self.watcher:
            self.watcher.stop()
        self.db.close()
