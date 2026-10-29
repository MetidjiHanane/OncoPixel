"""Polling folder watcher: imports new image/DICOM files that appear in a chosen folder.

Polling avoids a native file-system-events dependency. A file is imported once its size and
modification time have been stable for ``STABLE_SECONDS`` and it has not been seen before.
Imported studies stay ``pending``; nothing is analysed without the user asking for it.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Dict, List

from ..context import AppContext
from .imaging import IMAGE_EXT, is_hidden
from .importer import import_paths

STABLE_SECONDS = 2.0
POLL_SECONDS = 4.0


class FolderWatcher:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_scan: float | None = None
        self.last_error: str | None = None
        self.imported_total = 0

    # -- control ----------------------------------------------------------------------------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="oncopixel-watch", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def status(self) -> Dict[str, Any]:
        st = self.ctx.settings()
        return {"enabled": bool(st["watch_enabled"]), "dir": st["watch_dir"], "running": bool(self._thread and self._thread.is_alive()),
                "last_scan": self.last_scan, "last_error": self.last_error, "imported_total": self.imported_total}

    # -- scanning ---------------------------------------------------------------------------------
    def scan_once(self) -> List[int]:
        st = self.ctx.settings()
        self.last_scan = time.time()
        if not st["watch_enabled"] or not st["watch_dir"]:
            return []
        root = Path(st["watch_dir"]).expanduser()
        if not root.is_dir():
            self.last_error = "watch_dir_missing"
            return []
        self.last_error = None
        fresh: List[str] = []
        for p in root.rglob("*"):
            if not p.is_file() or is_hidden(p) or (p.suffix.lower() not in IMAGE_EXT and p.suffix):
                continue
            stat = p.stat()
            if time.time() - stat.st_mtime < STABLE_SECONDS:
                continue
            seen = self.ctx.db.one("SELECT mtime, size FROM watch_seen WHERE path=?", (str(p),))
            if seen and seen["mtime"] == stat.st_mtime and seen["size"] == stat.st_size:
                continue
            fresh.append(str(p))
        created: List[int] = []
        for path in fresh:
            st_ = Path(path).stat()
            try:
                res = import_paths(self.ctx, [path], "watcher")
                created += res["created"]
            except Exception as exc:  # keep watching; report the failure
                self.last_error = f"{Path(path).name}: {type(exc).__name__}"
            self.ctx.db.upsert("watch_seen", "path", {"path": path, "mtime": st_.st_mtime, "size": st_.st_size})
        if created:
            self.imported_total += len(created)
            self.ctx.db.log("watcher", "watch.import", None, None, {"studies": created})
        return created

    def _loop(self) -> None:
        while not self._stop.wait(POLL_SECONDS):
            try:
                self.scan_once()
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
