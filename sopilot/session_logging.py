"""Small structured session logger for hosted SOPilot trials."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Mapping

from fastapi import Request

LOGGER = logging.getLogger("sopilot.session")
if not LOGGER.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    LOGGER.addHandler(handler)
LOGGER.setLevel(logging.INFO)
LOGGER.propagate = False


def session_id_from_request(request: Request) -> str:
    return _safe_text(request.headers.get("x-session-id", ""))


def log_session_event(
    event: str,
    *,
    app: str = "sopilot",
    session_id: str = "",
    **fields: Any,
) -> dict[str, Any]:
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "app": app,
        "event": event,
        "session_id": _safe_text(session_id),
    }
    payload.update(_sanitize(fields))
    LOGGER.info(json.dumps(payload, separators=(",", ":"), sort_keys=True))
    return payload


def _sanitize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _sanitize(item)
            for key, item in value.items()
            if not _looks_sensitive(str(key))
        }
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _looks_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in ("key", "token", "secret", "password", "authorization"))


def _safe_text(value: Any) -> str:
    return str(value or "")[:120]
