"""Encrypted manual backup and restore of the whole data directory.

Patient data and images are already encrypted individually with the vault key. The backup
archive stores them as they are plus the vault key, which is itself encrypted with a key
derived from the user's passphrase (scrypt). Without the passphrase the archive is useless.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from cryptography.fernet import Fernet, InvalidToken

from .. import config
from ..context import AppContext
from ..security import derive_backup_key

MAGIC = "oncopixel-backup/1"


class BackupError(ValueError):
    pass


def create_backup(ctx: AppContext, passphrase: str, dest_dir: Path) -> Path:
    if len(passphrase) < 8:
        raise BackupError("passphrase_too_short")
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = dest_dir / f"OncoPixel-backup-{stamp}.opbackup"
    salt = os.urandom(16)
    f = Fernet(derive_backup_key(passphrase, salt))
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "oncopixel.db"
        src = sqlite3.connect(str(ctx.db.path))
        dst = sqlite3.connect(str(snap))
        with dst:
            src.backup(dst)  # consistent snapshot even while the app is running
        src.close(); dst.close()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("manifest.json", json.dumps({
                "format": MAGIC, "app_version": config.VERSION, "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "salt_hex": salt.hex()}))
            z.writestr("vault.key.enc", f.encrypt(ctx.vault.key_bytes()))
            z.write(snap, "oncopixel.db")
            root = ctx.files.root
            for p in root.rglob("*"):
                if p.is_file() and not p.name.endswith(".tmp"):
                    z.write(p, "files/" + p.relative_to(root).as_posix())
    return out


def restore_backup(ctx: AppContext, archive: Path, passphrase: str) -> Dict[str, Any]:
    try:
        z = zipfile.ZipFile(archive)
    except zipfile.BadZipFile as exc:
        raise BackupError("not_a_backup") from exc
    with z:
        try:
            manifest = json.loads(z.read("manifest.json"))
        except KeyError as exc:
            raise BackupError("not_a_backup") from exc
        if manifest.get("format") != MAGIC:
            raise BackupError("unsupported_backup_version")
        f = Fernet(derive_backup_key(passphrase, bytes.fromhex(manifest["salt_hex"])))
        try:
            key = f.decrypt(z.read("vault.key.enc"))
        except InvalidToken as exc:
            raise BackupError("wrong_passphrase") from exc
        data = ctx.data_dir
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        safety = data / f"pre_restore_{stamp}"
        safety.mkdir(parents=True, exist_ok=True)
        ctx.db.close()
        for name in ("oncopixel.db", "oncopixel.db-wal", "oncopixel.db-shm"):
            if (data / name).exists():
                shutil.move(str(data / name), str(safety / name))
        if (data / "files").exists():
            shutil.move(str(data / "files"), str(safety / "files"))
        if (data / "vault.key").exists():
            shutil.move(str(data / "vault.key"), str(safety / "vault.key"))
        for member in z.namelist():
            if member in ("manifest.json", "vault.key.enc"):
                continue
            target = (data / member).resolve()
            if data.resolve() not in target.parents:
                raise BackupError("unsafe_archive_path")
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(member) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
        (data / "vault.key").write_bytes(key)
        try:
            os.chmod(data / "vault.key", 0o600)
        except OSError:
            pass
    ctx.reopen()
    return {"restored_from": manifest.get("created"), "safety_copy": str(safety)}
