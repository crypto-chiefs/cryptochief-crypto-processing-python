"""Transport helpers: error-envelope parsing and retry backoff."""

from __future__ import annotations

import json
import math
import random
from typing import Any, Optional

from .errors import APIError, ErrorCode


def _field(env: dict, key: str) -> str:
    """Read ``key`` from an error envelope as a string (``""`` if absent)."""
    value = env.get(key)
    return value if isinstance(value, str) else ""


def _unix_seconds(value: Any) -> Optional[int]:
    """A JSON number as whole Unix seconds, or ``None``."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return int(value)
    return None


def parse_api_error(status: int, body: str) -> APIError:
    """Parse a non-2xx response body into an :class:`APIError` with a stable code.

    Gateway envelope (``error`` is a string):

    - own refusal: code in ``error``, sentence in ``msg``
      (``{"ok": false, "error": "LABEL_TOO_LONG", "msg": "label is longer ..."}``);
    - relayed upstream refusal: ``error`` is ``SERVICE_ERROR``, code in ``msg``
      (``{"ok": false, "error": "SERVICE_ERROR", "msg": "wallet_not_found"}``).

    The code is ``error`` unless that is ``SERVICE_ERROR``, in which case it is
    ``msg``; the message prefers ``msg`` and falls back to ``error``.

    White-label installation envelope (``error`` is an object): code in
    ``error.details.code``, else ``error.name``; message in ``error.message``
    (``{"data": null, "error": {"status": 401, "name": "UnauthorizedError",
    "message": "...", "details": {"code": "INVALID_SIGNATURE"}}}``).

    ``server_time`` is read from the top level, then from ``error.details``.
    An empty code falls back to ``HTTP_<status>``.
    """
    env: dict = {}
    try:
        parsed = json.loads(body)
        if isinstance(parsed, dict):
            env = parsed
    except ValueError:
        pass  # non-JSON error body -> fall back to HTTP_<status>

    st = _unix_seconds(env.get("server_time"))
    raw_error = env.get("error")
    if isinstance(raw_error, dict):
        details = raw_error.get("details")
        details = details if isinstance(details, dict) else {}
        code = _field(details, "code") or _field(raw_error, "name")
        message = _field(raw_error, "message")
        if st is None:
            st = _unix_seconds(details.get("server_time"))
    else:
        error = _field(env, "error")
        msg = _field(env, "msg")
        code = error if error and error != ErrorCode.SERVICE_ERROR else (msg or error)
        message = msg or error

    return APIError(
        code or f"HTTP_{status}",
        http_status=status,
        message=message,
        raw=body,
        server_time=st,
    )


def backoff_delay(attempt: int, base_ms: float, max_ms: float) -> float:
    """Exponential backoff with full jitter, capped at ``max_ms``.

    ``attempt`` is 1-indexed (first retry = 1). Returns seconds.
    """
    if base_ms <= 0:
        base_ms = 200
    if max_ms <= 0:
        max_ms = 5000
    d = base_ms * (2 ** (attempt - 1))
    if d <= 0 or d > max_ms:
        d = max_ms
    return random.uniform(0, d) / 1000.0  # full jitter, uniform in [0, d] ms


def network_error(message: str) -> APIError:
    """Build an :class:`APIError` for a transport-level (network) failure."""
    return APIError(ErrorCode.NETWORK_ERROR, message=message)
