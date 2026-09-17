"""The gateway's HMAC v1 check, re-implemented from the public signature spec.

The verifying side the SDK is tested against: the vector-driven test and the mock
gateway the client talks to over HTTP both go through :func:`check`. The string to
sign is built here from the received request, not with the SDK's signer.
"""

import hashlib
import hmac
import re
import string
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

SCOPE = "CC-HMAC-SHA256-REQ-V1"
SIGNATURE_PREFIX = "v1="
WINDOW = 300
NONCE_MIN, NONCE_MAX = 16, 64
TIMESTAMP_MAX_DIGITS = 18

HEADER_MERCHANT = "Merchant"
HEADER_TIMESTAMP = "X-CC-Timestamp"
HEADER_NONCE = "X-CC-Nonce"
HEADER_SIGNATURE = "X-CC-Signature"
HEADER_IDEMPOTENCY_KEY = "Idempotency-Key"
HEADER_CONTENT_TYPE = "Content-Type"

# Outcomes, named as the vector file's "expect".
OK = "ok"
BAD_AUTH_HEADERS = "bad_auth_headers"
TIMESTAMP_OUT_OF_RANGE = "timestamp_out_of_range"
INVALID_SIGNATURE = "invalid_signature"

_ASCII_LOWER = str.maketrans(string.ascii_uppercase, string.ascii_lowercase)
_ASCII_UPPER = str.maketrans(string.ascii_lowercase, string.ascii_uppercase)
_NONCE_RE = re.compile(r"[A-Za-z0-9_-]+")
_HEX64_RE = re.compile(r"[0-9a-fA-F]{64}")
_TOKEN = r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+"
#: One media-type parameter: ``; token=token`` or ``; token="quoted"``.
_PARAM_RE = re.compile(r'\s*;\s*' + _TOKEN + r'\s*=\s*(?:' + _TOKEN + r'|"(?:[^"\\]|\\.)*")')


@dataclass
class SignedRequest:
    """What the server reads: ``path`` percent-decoded, ``query`` raw, body as received."""

    method: str
    path: str
    query: str = ""
    body: bytes = b""
    #: Every header as received, in order, one entry per repeat.
    headers: List[Tuple[str, str]] = field(default_factory=list)


def string_to_sign(
    *,
    timestamp: str,
    nonce: str,
    method: str,
    path: str,
    query: str,
    merchant: str,
    idempotency_key: str,
    body: bytes,
) -> Optional[str]:
    """The string to sign, or ``None`` when a field carries CR or LF."""
    fields = [
        timestamp,
        nonce,
        method.translate(_ASCII_UPPER),
        path,
        query,
        merchant,
        idempotency_key,
    ]
    if any("\r" in f or "\n" in f for f in fields):
        return None
    return "\n".join([SCOPE, *fields, hashlib.sha256(body).hexdigest()])


def _single(headers: Sequence[Tuple[str, str]], name: str) -> Tuple[str, bool]:
    """The only value of a header without surrounding spaces and tabs.

    ``ok`` is ``False`` when the header is repeated; an absent header is ``("", True)``.
    """
    wanted = name.translate(_ASCII_LOWER)
    values = [v for n, v in headers if n.translate(_ASCII_LOWER) == wanted]
    if len(values) > 1:
        return "", False
    if not values:
        return "", True
    return values[0].strip(" \t"), True


def _first(headers: Sequence[Tuple[str, str]], name: str) -> str:
    wanted = name.translate(_ASCII_LOWER)
    for n, v in headers:
        if n.translate(_ASCII_LOWER) == wanted:
            return v
    return ""


def _is_decimal(value: str, max_len: int) -> bool:
    return (
        bool(value)
        and len(value) <= max_len
        and not (len(value) > 1 and value[0] == "0")
        and all("0" <= c <= "9" for c in value)
    )


def _is_nonce(value: str) -> bool:
    return NONCE_MIN <= len(value) <= NONCE_MAX and _NONCE_RE.fullmatch(value) is not None


def _is_json_content_type(value: str) -> bool:
    """``application/json`` ignoring ASCII case, with parameters that parse."""
    base, _, _ = value.partition(";")
    if base.strip(" \t").translate(_ASCII_LOWER) != "application/json":
        return False
    rest = value[len(base) :]
    while rest.strip():
        if rest.strip() == ";":  # a trailing semicolon is ignored
            break
        m = _PARAM_RE.match(rest)
        if m is None:
            return False
        rest = rest[m.end() :]
    return True


def check(req: SignedRequest, *, api_key: str, now: int) -> str:
    """Headers, timestamp window, key and signature; one of the outcome constants.

    Nonce replay is the caller's (the mock gateway keeps the used nonces).
    """
    merchant, ok1 = _single(req.headers, HEADER_MERCHANT)
    ts, ok2 = _single(req.headers, HEADER_TIMESTAMP)
    nonce, ok3 = _single(req.headers, HEADER_NONCE)
    sig, ok4 = _single(req.headers, HEADER_SIGNATURE)
    idem, ok5 = _single(req.headers, HEADER_IDEMPOTENCY_KEY)
    if not (ok1 and ok2 and ok3 and ok4 and ok5):
        return BAD_AUTH_HEADERS
    if not merchant or not _is_decimal(ts, TIMESTAMP_MAX_DIGITS) or not _is_nonce(nonce):
        return BAD_AUTH_HEADERS

    hex_signature = sig[len(SIGNATURE_PREFIX) :] if sig.startswith(SIGNATURE_PREFIX) else ""
    if _HEX64_RE.fullmatch(hex_signature) is None:
        return BAD_AUTH_HEADERS

    if req.body and not _is_json_content_type(_first(req.headers, HEADER_CONTENT_TYPE)):
        return BAD_AUTH_HEADERS

    sts = string_to_sign(
        timestamp=ts,
        nonce=nonce,
        method=req.method,
        path=req.path,
        query=req.query,
        merchant=merchant,
        idempotency_key=idem,
        body=req.body,
    )
    if sts is None:
        return BAD_AUTH_HEADERS

    if abs(now - int(ts)) > WINDOW:
        return TIMESTAMP_OUT_OF_RANGE

    # A project whose api_key is empty or only spaces and tabs never passes.
    if not api_key.strip(" \t"):
        return INVALID_SIGNATURE

    expected = hmac.new(api_key.encode("utf-8"), sts.encode("utf-8"), hashlib.sha256).digest()
    if not hmac.compare_digest(expected, bytes.fromhex(hex_signature)):
        return INVALID_SIGNATURE
    return OK
