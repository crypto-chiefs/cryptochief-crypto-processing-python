"""Canonical JSON + request signing.

Crypto Chief signs the *canonical* serialization of a request body. The
canonical form is fully deterministic:

* object keys sorted lexicographically by their UTF-8 bytes, recursively;
* compact (no insignificant whitespace);
* the HTML-sensitive characters ``<``, ``>``, ``&`` and the U+2028 / U+2029
  line / paragraph separators emitted as their JSON unicode escapes;
* standard JSON escapes for ``"``, ``\\``, and control characters (``\\n``,
  ``\\r``, ``\\t`` short forms; everything else below 0x20 as ``\\u00XX``,
  lowercase hex).

The gateway re-derives this canonical form from the bytes it receives and
checks the signature against it, so the client must emit byte-identical output.
The regression vectors in ``tests/test_sign.py`` lock this down.
"""

from __future__ import annotations

import base64
import hashlib
from typing import Any, Tuple

from .errors import CryptoChiefError

_SHORT_ESCAPES = {
    0x22: '\\"',
    0x5C: "\\\\",
    0x0A: "\\n",
    0x0D: "\\r",
    0x09: "\\t",
    0x3C: "\\u003c",
    0x3E: "\\u003e",
    0x26: "\\u0026",
    0x2028: "\\u2028",
    0x2029: "\\u2029",
}


def _encode_string(s: str) -> str:
    out = ['"']
    for ch in s:
        code = ord(ch)
        esc = _SHORT_ESCAPES.get(code)
        if esc is not None:
            out.append(esc)
        elif code < 0x20:
            out.append("\\u%04x" % code)
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _encode_number(n: "int | float") -> str:
    if isinstance(n, bool):  # bool is a subclass of int - guard first
        return "true" if n else "false"
    if isinstance(n, int):
        return str(n)
    # Floats are not expected in signed bodies (amounts travel as strings), but
    # match the gateway's shortest-form rendering: integral floats drop the dot.
    if n != n or n in (float("inf"), float("-inf")):
        raise CryptoChiefError(f"cryptochief: cannot canonicalize non-finite number {n}")
    if n == int(n) and abs(n) < 1e21:
        return str(int(n))
    return repr(n)


def _encode_value(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return _encode_string(v)
    if isinstance(v, (int, float)):
        return _encode_number(v)
    if isinstance(v, dict):
        keys = [k for k, val in v.items() if val is not None]
        keys.sort(key=lambda k: str(k).encode("utf-8"))
        parts = [_encode_string(str(k)) + ":" + _encode_value(v[k]) for k in keys]
        return "{" + ",".join(parts) + "}"
    if isinstance(v, (list, tuple)):
        return "[" + ",".join(_encode_value(el) for el in v) + "]"
    raise CryptoChiefError(f"cryptochief: cannot canonicalize value of type {type(v).__name__}")


def canonical_json(value: Any) -> str:
    """Produce the canonical JSON string for a value.

    ``None`` collapses to an empty body, which signs as ``md5(api_key)``.
    """
    if value is None:
        return ""
    return _encode_value(value)


def sign(canonical_body: str, api_key: str) -> str:
    """Compute the ``Signature`` header for an already-canonical body.

    ``hex(md5(base64(canonical_body) + api_key))``. An empty body signs as
    ``md5(api_key)``.
    """
    b64 = base64.b64encode(canonical_body.encode("utf-8")).decode("ascii")
    return hashlib.md5((b64 + api_key).encode("utf-8")).hexdigest()


def sign_value(value: Any, api_key: str) -> Tuple[str, str]:
    """Canonicalize then sign a value, returning ``(canonical, signature)``."""
    canonical = canonical_json(value)
    return canonical, sign(canonical, api_key)
