"""SQLite persistence (standard library only) and the encrypted file store."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .config import default_settings
from .security import Vault

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, display_name TEXT,
  pw_hash TEXT NOT NULL, failed_attempts INTEGER NOT NULL DEFAULT 0,
  locked_until REAL NOT NULL DEFAULT 0, created_at TEXT NOT NULL, recovery_hash TEXT);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS patients(
  id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, name_enc BLOB NOT NULL, age INTEGER, sex TEXT,
  referring_enc BLOB, history_enc BLOB, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS studies(
  id INTEGER PRIMARY KEY, code TEXT UNIQUE, patient_id INTEGER REFERENCES patients(id) ON DELETE SET NULL,
  study_date TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending', flagged INTEGER NOT NULL DEFAULT 0, flag_reason TEXT,
  modality TEXT NOT NULL DEFAULT 'MRI', sequence TEXT NOT NULL DEFAULT 'T1', plane TEXT NOT NULL DEFAULT 'unknown',
  source_type TEXT NOT NULL, indication_enc BLOB, primary_slice_id INTEGER,
  reviewed_by TEXT, reviewed_at TEXT, review_note_enc BLOB,
  clinician_decision TEXT, clinician_class TEXT);
CREATE TABLE IF NOT EXISTS slices(
  id INTEGER PRIMARY KEY, study_id INTEGER NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
  idx INTEGER NOT NULL, file_rel TEXT, width INTEGER NOT NULL, height INTEGER NOT NULL,
  orig_name_enc BLOB, spacing_row REAL, spacing_col REAL, spacing_source TEXT,
  dicom_json TEXT, warnings_json TEXT NOT NULL DEFAULT '[]', sha256 TEXT);
CREATE TABLE IF NOT EXISTS classifications(
  slice_id INTEGER PRIMARY KEY REFERENCES slices(id) ON DELETE CASCADE,
  label TEXT NOT NULL, confidence REAL NOT NULL, probs_json TEXT NOT NULL, needs_review INTEGER NOT NULL,
  model_json TEXT NOT NULL, params_json TEXT NOT NULL, gradcam_rel TEXT, gradcam_status TEXT,
  inference_ms REAL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS segmentations(
  slice_id INTEGER PRIMARY KEY REFERENCES slices(id) ON DELETE CASCADE,
  threshold REAL NOT NULL, tta INTEGER NOT NULL, postprocess_json TEXT NOT NULL, model_json TEXT NOT NULL,
  prob_rel TEXT, mask_model_rel TEXT, mask_current_rel TEXT, edited INTEGER NOT NULL DEFAULT 0, edited_at TEXT,
  uncertainty_json TEXT, unc_entropy_rel TEXT, unc_var_rel TEXT, inference_ms REAL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS measurements(
  slice_id INTEGER PRIMARY KEY REFERENCES slices(id) ON DELETE CASCADE,
  json TEXT NOT NULL, computed_at TEXT NOT NULL, mask_edited INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS activity(
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, username TEXT, action TEXT NOT NULL,
  entity TEXT, entity_id INTEGER, detail_json TEXT);
CREATE TABLE IF NOT EXISTS watch_seen(path TEXT PRIMARY KEY, mtime REAL NOT NULL, size INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS idx_slices_study ON slices(study_id, idx);
CREATE INDEX IF NOT EXISTS idx_studies_patient ON studies(patient_id);
CREATE INDEX IF NOT EXISTS idx_studies_status ON studies(status, flagged);
CREATE INDEX IF NOT EXISTS idx_activity_ts ON activity(ts DESC);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    """Thin wrapper around one sqlite3 connection guarded by a re-entrant lock."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        with self._lock:
            self._conn.executescript(SCHEMA)
            cols = [r["name"] for r in self._conn.execute("PRAGMA table_info(users)").fetchall()]
            if "recovery_hash" not in cols:  # databases created before the recovery key existed
                self._conn.execute("ALTER TABLE users ADD COLUMN recovery_hash TEXT")
            scols = [r["name"] for r in self._conn.execute("PRAGMA table_info(studies)").fetchall()]
            for col in ("clinician_decision", "clinician_class"):  # databases created before the clinician review box
                if col not in scols:
                    self._conn.execute(f"ALTER TABLE studies ADD COLUMN {col} TEXT")
            self._conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    # -- primitives ---------------------------------------------------------------------------
    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, tuple(params))

    def one(self, sql: str, params: Iterable[Any] = ()) -> Optional[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, tuple(params)).fetchone()

    def all(self, sql: str, params: Iterable[Any] = ()) -> List[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, tuple(params)).fetchall()

    def insert(self, table: str, values: Dict[str, Any]) -> int:
        cols = ", ".join(values)
        marks = ", ".join("?" for _ in values)
        with self._lock:
            cur = self._conn.execute(f"INSERT INTO {table}({cols}) VALUES({marks})", tuple(values.values()))
            return int(cur.lastrowid)

    def upsert(self, table: str, key: str, values: Dict[str, Any]) -> None:
        cols = ", ".join(values)
        marks = ", ".join("?" for _ in values)
        updates = ", ".join(f"{c}=excluded.{c}" for c in values if c != key)
        with self._lock:
            self._conn.execute(
                f"INSERT INTO {table}({cols}) VALUES({marks}) ON CONFLICT({key}) DO UPDATE SET {updates}",
                tuple(values.values()),
            )

    def update(self, table: str, where: str, where_params: Iterable[Any], values: Dict[str, Any]) -> None:
        sets = ", ".join(f"{c}=?" for c in values)
        with self._lock:
            self._conn.execute(f"UPDATE {table} SET {sets} WHERE {where}", tuple(values.values()) + tuple(where_params))

    def transaction(self):
        return _Tx(self)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- settings -----------------------------------------------------------------------------
    def load_settings(self, data_dir: Path) -> Dict[str, Any]:
        out = default_settings(data_dir)
        for row in self.all("SELECT key, value FROM settings"):
            if row["key"] in out:
                try:
                    out[row["key"]] = json.loads(row["value"])
                except ValueError:
                    pass
        return out

    def save_setting(self, key: str, value: Any) -> None:
        self.upsert("settings", "key", {"key": key, "value": json.dumps(value)})

    # -- activity log -------------------------------------------------------------------------
    def log(self, username: Optional[str], action: str, entity: Optional[str] = None,
            entity_id: Optional[int] = None, detail: Optional[Dict[str, Any]] = None) -> None:
        self.insert("activity", {
            "ts": now_iso(), "username": username, "action": action, "entity": entity,
            "entity_id": entity_id, "detail_json": json.dumps(detail) if detail else None,
        })


class _Tx:
    def __init__(self, db: Database):
        self.db = db

    def __enter__(self):
        self.db._lock.acquire()
        self.db._conn.execute("BEGIN")
        return self.db

    def __exit__(self, exc_type, exc, tb):
        try:
            self.db._conn.execute("ROLLBACK" if exc_type else "COMMIT")
        finally:
            self.db._lock.release()
        return False


class FileStore:
    """Encrypted blob storage under ``<data_dir>/files``. Paths are stored relative to it."""

    def __init__(self, root: Path, vault: Vault):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.vault = vault

    def _abs(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if self.root.resolve() not in p.parents:
            raise ValueError("path escapes the file store")
        return p

    def write(self, rel: str, data: bytes) -> str:
        p = self._abs(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_bytes(self.vault.encrypt(data))
        tmp.replace(p)
        return rel

    def read(self, rel: str) -> bytes:
        return self.vault.decrypt(self._abs(rel).read_bytes())

    def exists(self, rel: Optional[str]) -> bool:
        return bool(rel) and self._abs(rel).exists()

    def delete_tree(self, rel_dir: str) -> None:
        import shutil

        p = self._abs(rel_dir)
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
