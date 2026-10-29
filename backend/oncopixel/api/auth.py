"""Local sign-in: first-run account creation, login with lockout, logout, password change."""
from __future__ import annotations

import base64
import os
import time
from typing import Optional

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field

from .. import config
from ..context import AppContext
from ..db import now_iso
from ..security import (PasswordPolicyError, check_password_policy, hash_password, lock_seconds_for, verify_password)
from .deps import COOKIE, ApiError, current_user, get_ctx
from fastapi import Request

router = APIRouter(prefix="/api/auth", tags=["auth"])


class SetupBody(BaseModel):
    username: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9_.-]+$")
    display_name: str = Field(default="", max_length=80)
    password: str = Field(min_length=1, max_length=200)


class LoginBody(BaseModel):
    username: str
    password: str


class PasswordBody(BaseModel):
    current_password: str
    new_password: str


class ResetBody(BaseModel):
    username: str
    recovery_key: str = Field(min_length=8, max_length=80)
    new_password: str = Field(min_length=1, max_length=200)


class RecoveryBody(BaseModel):
    current_password: str


def _new_recovery_key() -> str:
    """120 random bits as 6 groups of 4 base32 characters. Only a scrypt hash of it is stored."""
    raw = base64.b32encode(os.urandom(15)).decode().rstrip("=")
    return "-".join(raw[i:i + 4] for i in range(0, 24, 4))


def _norm_key(key: str) -> str:
    return "".join(ch for ch in key.upper() if ch.isalnum())


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(COOKIE, token, httponly=True, samesite="strict", max_age=8 * 3600, path="/")


def _user_dict(row) -> dict:
    return {"username": row["username"], "display_name": row["display_name"] or row["username"], "has_recovery_key": bool(row["recovery_hash"])}


@router.get("/state")
def state(request: Request, ctx: AppContext = Depends(get_ctx)):
    user = ctx.sessions.validate(request.cookies.get(COOKIE))
    row = ctx.db.one("SELECT * FROM users WHERE username=?", (user,)) if user else None
    return {"setup_required": ctx.db.one("SELECT 1 FROM users LIMIT 1") is None, "authenticated": bool(row),
            "user": _user_dict(row) if row else None, "app": {"name": config.APP_NAME, "version": config.VERSION, "tagline": config.TAGLINE},
            "disclaimer": {"en": config.DISCLAIMER_EN, "fr": config.DISCLAIMER_FR}}


@router.post("/setup")
def setup(body: SetupBody, response: Response, ctx: AppContext = Depends(get_ctx)):
    if ctx.db.one("SELECT 1 FROM users LIMIT 1"):
        raise ApiError(409, "setup_already_done")
    try:
        check_password_policy(body.password)
    except PasswordPolicyError as exc:
        raise ApiError(422, str(exc))
    key = _new_recovery_key()
    ctx.db.insert("users", {"username": body.username, "display_name": body.display_name.strip() or body.username,
                            "pw_hash": hash_password(body.password), "created_at": now_iso(),
                            "recovery_hash": hash_password(_norm_key(key))})
    ctx.db.log(body.username, "auth.setup")
    _set_cookie(response, ctx.sessions.create(body.username))
    return {"ok": True, "recovery_key": key}


@router.post("/login")
def login(body: LoginBody, response: Response, ctx: AppContext = Depends(get_ctx)):
    row = ctx.db.one("SELECT * FROM users WHERE username=?", (body.username,))
    now = time.time()
    if row and row["locked_until"] > now:
        raise ApiError(423, "account_locked", retry_after=int(row["locked_until"] - now) + 1)
    if not row or not verify_password(body.password, row["pw_hash"]):
        if row:
            fails = row["failed_attempts"] + 1
            lock = lock_seconds_for(fails)
            ctx.db.update("users", "id=?", (row["id"],), {"failed_attempts": fails, "locked_until": now + lock if lock else 0})
            ctx.db.log(body.username, "auth.failed", detail={"attempts": fails})
            if lock:
                raise ApiError(423, "account_locked", retry_after=int(lock))
        time.sleep(0.4)  # blunt timing differences between unknown user and wrong password
        raise ApiError(401, "invalid_credentials")
    ctx.db.update("users", "id=?", (row["id"],), {"failed_attempts": 0, "locked_until": 0})
    ctx.db.log(row["username"], "auth.login")
    _set_cookie(response, ctx.sessions.create(row["username"]))
    return {"ok": True, "user": _user_dict(row)}


@router.post("/logout")
def logout(request: Request, response: Response, ctx: AppContext = Depends(get_ctx)):
    token = request.cookies.get(COOKIE)
    user = ctx.sessions.validate(token)
    ctx.sessions.revoke(token)
    response.delete_cookie(COOKIE, path="/")
    if user:
        ctx.db.log(user, "auth.logout")
    return {"ok": True}


@router.post("/password")
def change_password(body: PasswordBody, user: str = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    row = ctx.db.one("SELECT * FROM users WHERE username=?", (user,))
    if not row or not verify_password(body.current_password, row["pw_hash"]):
        raise ApiError(401, "invalid_credentials")
    try:
        check_password_policy(body.new_password)
    except PasswordPolicyError as exc:
        raise ApiError(422, str(exc))
    ctx.db.update("users", "id=?", (row["id"],), {"pw_hash": hash_password(body.new_password)})
    ctx.db.log(user, "auth.password_changed")
    return {"ok": True}


@router.post("/recovery-key")
def new_recovery_key(body: RecoveryBody, user: str = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    """Create (or replace) the recovery key. Needs the current password. The key is shown once."""
    row = ctx.db.one("SELECT * FROM users WHERE username=?", (user,))
    if not row or not verify_password(body.current_password, row["pw_hash"]):
        raise ApiError(401, "invalid_credentials")
    key = _new_recovery_key()
    ctx.db.update("users", "id=?", (row["id"],), {"recovery_hash": hash_password(_norm_key(key))})
    ctx.db.log(user, "auth.recovery_key_created")
    return {"recovery_key": key}


@router.post("/reset")
def reset_password(body: ResetBody, response: Response, ctx: AppContext = Depends(get_ctx)):
    """Forgotten password: choose a new one with the recovery key. The stored data is not affected
    (it is encrypted with a separate key). A new recovery key is issued and the old one stops working."""
    row = ctx.db.one("SELECT * FROM users WHERE username=?", (body.username,))
    now = time.time()
    if row and row["locked_until"] > now:
        raise ApiError(423, "account_locked", retry_after=int(row["locked_until"] - now) + 1)
    ok = bool(row and row["recovery_hash"] and verify_password(_norm_key(body.recovery_key), row["recovery_hash"]))
    if not ok:
        if row:
            fails = row["failed_attempts"] + 1
            lock = lock_seconds_for(fails)
            ctx.db.update("users", "id=?", (row["id"],), {"failed_attempts": fails, "locked_until": now + lock if lock else 0})
            ctx.db.log(body.username, "auth.reset_failed", detail={"attempts": fails})
        time.sleep(0.4)
        raise ApiError(401, "invalid_recovery_key")
    try:
        check_password_policy(body.new_password)
    except PasswordPolicyError as exc:
        raise ApiError(422, str(exc))
    key = _new_recovery_key()
    ctx.db.update("users", "id=?", (row["id"],), {"pw_hash": hash_password(body.new_password), "failed_attempts": 0,
                                                  "locked_until": 0, "recovery_hash": hash_password(_norm_key(key))})
    ctx.db.log(row["username"], "auth.password_reset")
    _set_cookie(response, ctx.sessions.create(row["username"]))
    return {"ok": True, "recovery_key": key}
