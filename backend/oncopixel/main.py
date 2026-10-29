"""FastAPI application factory.

The server listens on 127.0.0.1 only. Defence in depth against other local web pages:
* every ``/api`` request must carry the per-launch application token (set by the desktop shell);
* the session cookie is HttpOnly and SameSite=Strict;
* the ``Host`` header must be a loopback address (blocks DNS rebinding).
"""
from __future__ import annotations

import os
import secrets
from contextlib import asynccontextmanager
from urllib.parse import urlsplit
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .api import auth, clinical, core
from .api.deps import ApiError, error_body
from .context import AppContext
from .ml.registry import ModelUnavailable
from .services import analysis, repo
from .services.watcher import FolderWatcher

LOOPBACK = {"127.0.0.1", "localhost", "::1"}
TOKEN_HEADER = "x-oncopixel-app"


def create_app(data_dir: Optional[Path] = None, frontend_dir: Optional[Path] = None, app_token: Optional[str] = None,
               start_watcher: bool = True) -> FastAPI:
    ctx = AppContext(data_dir)
    if app_token is not None:
        ctx.app_token = app_token
    ctx.watcher = FolderWatcher(ctx)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if start_watcher:
            ctx.watcher.start()
        yield
        ctx.close()

    app = FastAPI(title="OncoPixel API", version=config.VERSION, docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.ctx = ctx

    @app.middleware("http")
    async def guard(request: Request, call_next):
        host = urlsplit("//" + (request.headers.get("host") or "")).hostname or ""
        if host not in LOOPBACK:
            return JSONResponse(error_body("bad_host"), status_code=403)
        if request.url.path.startswith("/api") and ctx.app_token:
            if not secrets.compare_digest(request.headers.get(TOKEN_HEADER, ""), ctx.app_token):
                return JSONResponse(error_body("app_token_required"), status_code=403)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Content-Security-Policy", "frame-ancestors 'none'")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    # -- errors ---------------------------------------------------------------------------------
    @app.exception_handler(ApiError)
    async def _api_error(_r: Request, exc: ApiError):
        d = dict(exc.detail)
        return JSONResponse({"error": d}, status_code=exc.status_code)

    @app.exception_handler(ModelUnavailable)
    async def _model(_r: Request, exc: ModelUnavailable):
        d = exc.to_dict()
        return JSONResponse(error_body("MODEL_MISSING", exc.detail, kind=d["kind"], state=d["state"], reason=d["code"], path=d["path"]),
                            status_code=409)

    @app.exception_handler(repo.NotFound)
    async def _nf(_r: Request, exc: repo.NotFound):
        return JSONResponse(error_body("not_found", str(exc)), status_code=404)

    @app.exception_handler(repo.Invalid)
    async def _inv(_r: Request, exc: repo.Invalid):
        return JSONResponse(error_body(str(exc)), status_code=422)

    @app.exception_handler(analysis.MaskError)
    async def _mask(_r: Request, exc: analysis.MaskError):
        return JSONResponse(error_body(str(exc)), status_code=409)

    @app.exception_handler(ValueError)
    async def _value(_r: Request, exc: ValueError):
        return JSONResponse(error_body("invalid_value", str(exc)), status_code=422)

    @app.exception_handler(RequestValidationError)
    async def _validation(_r: Request, exc: RequestValidationError):
        return JSONResponse(error_body("validation_error", "Invalid request", fields=[
            {"loc": [str(x) for x in e["loc"]], "msg": e["msg"]} for e in exc.errors()]), status_code=422)

    app.include_router(auth.router)
    app.include_router(core.router)
    app.include_router(clinical.router)

    @app.get("/api/health")
    def health():
        return {"ok": True, "version": config.VERSION}

    # -- frontend -------------------------------------------------------------------------------
    fe = Path(frontend_dir or os.environ.get("ONCOPIXEL_FRONTEND_DIR") or config.REPO_ROOT / "desktop" / "dist")
    if (fe / "index.html").exists():
        if (fe / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=fe / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                return JSONResponse(error_body("not_found"), status_code=404)
            target = (fe / path).resolve()
            if path and fe.resolve() in target.parents and target.is_file():
                return FileResponse(target)
            return FileResponse(fe / "index.html")
    else:
        @app.get("/", include_in_schema=False)
        def no_frontend():
            return JSONResponse({"message": "OncoPixel API is running. The interface has not been built (desktop/dist missing)."})
    return app
