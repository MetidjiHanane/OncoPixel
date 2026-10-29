"""Settings, models, folder watch, dashboard, activity log and backups."""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..context import AppContext
from ..services import backup, repo, selftest
from .deps import ApiError, current_user, get_ctx

router = APIRouter(prefix="/api", tags=["core"], dependencies=[Depends(current_user)])


# -- settings ------------------------------------------------------------------------------------
@router.get("/settings")
def get_settings(ctx: AppContext = Depends(get_ctx)):
    return ctx.settings()


@router.patch("/settings")
def patch_settings(changes: Dict[str, Any], user: str = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    try:
        new = ctx.update_settings(changes)
    except KeyError as exc:
        raise ApiError(422, "unknown_setting", key=str(exc).strip("'"))
    except (ValueError, TypeError) as exc:
        raise ApiError(422, "invalid_setting", str(exc))
    if {"watch_enabled", "watch_dir"} & set(changes) and ctx.watcher:
        ctx.watcher.start()
    ctx.db.log(user, "settings.update", detail={"keys": sorted(changes)})
    return new


# -- models --------------------------------------------------------------------------------------
@router.get("/models")
def models_status(ctx: AppContext = Depends(get_ctx)):
    return ctx.models.status_all()


@router.post("/models/reload")
def models_reload(ctx: AppContext = Depends(get_ctx)):
    ctx.models.invalidate()
    return ctx.models.status_all()


@router.post("/models/selftest")
def models_selftest(ctx: AppContext = Depends(get_ctx)):
    return selftest.run(ctx.models)


# -- folder watch --------------------------------------------------------------------------------
@router.get("/watch")
def watch_status(ctx: AppContext = Depends(get_ctx)):
    return ctx.watcher.status() if ctx.watcher else {"enabled": False}


@router.post("/watch/scan")
def watch_scan(ctx: AppContext = Depends(get_ctx)):
    if not ctx.watcher:
        raise ApiError(409, "watcher_unavailable")
    return {"created": ctx.watcher.scan_once(), **ctx.watcher.status()}


# -- dashboard and activity ----------------------------------------------------------------------
@router.get("/dashboard")
def dashboard(ctx: AppContext = Depends(get_ctx)):
    d = repo.dashboard(ctx)
    d["models"] = {k: v["state"] for k, v in ctx.models.status_all()["models"].items()}
    return d


@router.get("/activity")
def activity(limit: int = 100, offset: int = 0, action: Optional[str] = None, ctx: AppContext = Depends(get_ctx)):
    import json

    where, params = ("WHERE action LIKE ?", [action + "%"]) if action else ("", [])
    rows = ctx.db.all(f"SELECT * FROM activity {where} ORDER BY id DESC LIMIT ? OFFSET ?", params + [min(limit, 500), offset])
    total = ctx.db.one(f"SELECT COUNT(*) n FROM activity {where}", params)["n"]
    return {"total": total, "items": [{"id": r["id"], "ts": r["ts"], "user": r["username"], "action": r["action"], "entity": r["entity"],
                                       "entity_id": r["entity_id"], "detail": json.loads(r["detail_json"]) if r["detail_json"] else {}} for r in rows]}


# -- backup --------------------------------------------------------------------------------------
class BackupBody(BaseModel):
    passphrase: str


@router.post("/backup")
def make_backup(body: BackupBody, user: str = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    try:
        path = backup.create_backup(ctx, body.passphrase, ctx.export_dir())
    except backup.BackupError as exc:
        raise ApiError(422, str(exc))
    ctx.db.log(user, "backup.create", detail={"file": path.name})
    return {"path": str(path), "name": path.name, "size_mb": round(path.stat().st_size / 1e6, 2)}


@router.get("/backup/download")
def download_backup(name: str, ctx: AppContext = Depends(get_ctx)):
    p = (ctx.export_dir() / Path(name).name)
    if not p.is_file() or p.suffix != ".opbackup":
        raise ApiError(404, "not_found")
    return FileResponse(p, filename=p.name, media_type="application/octet-stream")


@router.post("/backup/restore")
def restore_backup(passphrase: str = Form(...), file: UploadFile = File(...), user: str = Depends(current_user),
                   ctx: AppContext = Depends(get_ctx)):
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "upload.opbackup"
        with open(tmp, "wb") as f:
            while chunk := file.file.read(1 << 20):
                f.write(chunk)
        try:
            out = backup.restore_backup(ctx, tmp, passphrase)
        except backup.BackupError as exc:
            raise ApiError(422, str(exc))
    return {**out, "sign_in_again": True}
