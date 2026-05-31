"""Reusable FastAPI runtime security for hosted SOPilot demos."""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse


def csv_env(name: str) -> list[str]:
    raw = os.environ.get(name, "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def install_api_security(
    app: FastAPI,
    *,
    token_env: str = "SOPILOT_APP_TOKEN",
    access_code_env: str = "",
    cors_origins_env: str = "SOPILOT_CORS_ORIGINS",
    exempt_paths: Sequence[str] = ("/api/health",),
    access_code_exempt_paths: Sequence[str] = ("/api/health", "/api/auth/check"),
    protected_path: Callable[[str], bool] | None = None,
) -> None:
    """Install optional CORS and app-token gating on a FastAPI app.

    The token gate is intentionally simple: if ``token_env`` is unset, no token
    is required. If set, protected API routes must send ``x-app-token``.
    If ``access_code_env`` is set, protected API routes must also send a
    user-entered ``x-trial-code``. Unlike app tokens, this code is not embedded
    into the static app and is suitable for lightweight invite-only trials.
    """

    origins = csv_env(cors_origins_env)
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=[
                "content-type",
                "x-app-token",
                "x-trial-code",
                "x-session-id",
                "authorization",
            ],
        )

    is_protected = protected_path or (lambda path: path.startswith("/api/"))
    exempt = set(exempt_paths)
    access_code_exempt = set(access_code_exempt_paths)

    @app.middleware("http")
    async def app_token_gate(request: Request, call_next):
        app_token = os.environ.get(token_env, "")
        access_code = os.environ.get(access_code_env, "") if access_code_env else ""
        if (
            app_token
            and is_protected(request.url.path)
            and request.url.path not in exempt
            and request.headers.get("x-app-token") != app_token
        ):
            return JSONResponse({"ok": False, "reason": "Invalid app token."}, status_code=401)
        if (
            access_code
            and is_protected(request.url.path)
            and request.url.path not in access_code_exempt
            and request.headers.get("x-trial-code") != access_code
        ):
            return JSONResponse({"ok": False, "reason": "Invalid access code."}, status_code=401)
        return await call_next(request)
