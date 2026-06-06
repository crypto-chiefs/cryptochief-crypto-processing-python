"""Transport helpers: error-envelope parsing and retry backoff."""

from __future__ import annotations

import json
import random

from .errors import APIError, ErrorCode


def parse_api_error(status: int, body: str) -> APIError:
    """Parse a non-2xx response body into an :class:`APIError` with a stable code.

    The code is ``msg or error or HTTP_<status>``, and the message prefers
    ``msg`` when it differs from ``error``.
    """
    env: dict = {}
    try:
        parsed = json.loads(body)
        if isinstance(parsed, dict):
            env = parsed
    except ValueError:
        pass  # non-JSON error body -> fall back to HTTP_<status>
    code = env.get("msg") or env.get("error") or f"HTTP_{status}"
    message = env.get("error") or ""
    if env.get("msg") and env.get("msg") != env.get("error"):
        message = env.get("msg")
    return APIError(code, http_status=status, message=message, raw=body)


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
