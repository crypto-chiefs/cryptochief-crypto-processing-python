"""Transport helpers: error-envelope parsing and retry backoff."""

from __future__ import annotations

import json
import random

from .errors import APIError, ErrorCode


def _field(env: dict, key: str) -> str:
    """Read ``key`` from an error envelope as a trimmed string (``""`` if absent)."""
    value = env.get(key)
    return value.strip() if isinstance(value, str) else ""


def parse_api_error(status: int, body: str) -> APIError:
    """Parse a non-2xx response body into an :class:`APIError` with a stable code.

    Refusals arrive in two envelope shapes. When the gateway itself refuses, the
    machine code is in ``error`` and ``msg`` holds an English sentence
    (``{"error": "LABEL_TOO_LONG", "msg": "label is longer than 255 characters"}``).
    When it relays an upstream refusal, ``error`` is the generic
    ``SERVICE_ERROR`` marker and the machine code is in ``msg``
    (``{"error": "SERVICE_ERROR", "msg": "wallet_not_found"}``).

    So the code is ``error`` unless that is ``SERVICE_ERROR``, in which case it
    is ``msg``; an empty result falls back to ``error`` and then
    ``HTTP_<status>``. The human-readable message prefers ``msg`` and falls back
    to ``error``.
    """
    env: dict = {}
    try:
        parsed = json.loads(body)
        if isinstance(parsed, dict):
            env = parsed
    except ValueError:
        pass  # non-JSON error body -> fall back to HTTP_<status>

    error = _field(env, "error")
    msg = _field(env, "msg")
    code = error if error and error != ErrorCode.SERVICE_ERROR else (msg or error)
    return APIError(
        code or f"HTTP_{status}",
        http_status=status,
        message=msg or error,
        raw=body,
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
