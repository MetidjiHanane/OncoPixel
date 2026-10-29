"""Shared FastAPI dependencies and the error contract.

Every error response has the shape ``{"error": {"code": str, "message": str, ...}}`` so the
interface can translate it. Codes are stable identifiers, never display text.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, Request

from ..context import AppContext

COOKIE = "op_session"


class ApiError(HTTPException):
    def __init__(self, status: int, code: str, message: str = "", **extra: Any):
        super().__init__(status_code=status, detail={"code": code, "message": message or code, **extra})


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx


def current_user(request: Request, ctx: AppContext = Depends(get_ctx)) -> str:
    user = ctx.sessions.validate(request.cookies.get(COOKIE))
    if not user:
        raise ApiError(401, "not_authenticated", "Sign in to continue")
    return user


def error_body(code: str, message: str = "", **extra: Any) -> Dict[str, Any]:
    return {"error": {"code": code, "message": message or code, **extra}}
