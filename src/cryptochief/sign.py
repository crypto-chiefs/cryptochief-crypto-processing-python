"""Request and webhook signing: HMAC-SHA256 v1.

Requests carry ``X-CC-Signature``: see :func:`hmac_v1_string_to_sign` and
:func:`hmac_v1_sign`. Webhooks carry ``X-CC-Signature``: see
:func:`webhook_v1_string_to_sign` and :func:`sign_webhook_v1`. Both sign the body
bytes as sent.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import string
from typing import Union

from .errors import CryptoChiefError

#: First line of the HMAC v1 request string to sign.
HMAC_V1_SCOPE = "CC-HMAC-SHA256-REQ-V1"
#: Prefix of the ``X-CC-Signature`` value.
HMAC_V1_SIGNATURE_PREFIX = "v1="

HEADER_TIMESTAMP = "X-CC-Timestamp"
HEADER_NONCE = "X-CC-Nonce"
HEADER_HMAC_SIGNATURE = "X-CC-Signature"
HEADER_IDEMPOTENCY_KEY = "Idempotency-Key"

#: First line of the webhook string to sign.
WEBHOOK_V1_SCOPE = "CC-HMAC-SHA256-WEBHOOK-V1"

_DELIVERY_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,128}")

#: Largest ``X-CC-Timestamp`` value, the int64 maximum.
_MAX_TIMESTAMP = 2**63 - 1

_ASCII_UPPER = str.maketrans(string.ascii_lowercase, string.ascii_uppercase)


Body = Union[bytes, bytearray, memoryview, str]


def _checked_api_key(api_key: str) -> str:
    """The signing key. An empty one, or one of only spaces and tabs, is an error."""
    if not api_key or not api_key.strip(" \t"):
        raise CryptoChiefError("cryptochief: api_key is required")
    return api_key


def _body_bytes(body: Body) -> bytes:
    if not isinstance(body, str):
        return bytes(body)
    try:
        return body.encode("utf-8", "surrogateescape")
    except UnicodeEncodeError:
        return body.encode("utf-8", "surrogatepass")


def hmac_v1_body_sha256(body: Body = b"") -> str:
    """Lowercase hex SHA-256 of the body bytes (a ``str`` is UTF-8 encoded)."""
    return hashlib.sha256(_body_bytes(body)).hexdigest()


def hmac_v1_string_to_sign(
    *,
    timestamp: Union[int, str],
    nonce: str,
    method: str,
    path: str,
    merchant: str,
    query: str = "",
    idempotency_key: str = "",
    body: Body = b"",
) -> str:
    """Build the HMAC v1 string to sign.

    ``path`` is the API route (``/v1/payout/execute``), ``query`` has no ``?``,
    ``body`` is exactly the bytes sent. ``method`` is upper-cased in ASCII
    only. A value containing CR or LF raises :class:`CryptoChiefError`.
    """
    fields = [
        str(timestamp),
        nonce,
        method.translate(_ASCII_UPPER),
        path,
        query,
        merchant,
        idempotency_key,
    ]
    for f in fields:
        if "\r" in f or "\n" in f:
            raise CryptoChiefError("cryptochief: hmac v1 value contains CR or LF")
    return "\n".join([HMAC_V1_SCOPE, *fields, hmac_v1_body_sha256(body)])


def hmac_v1_sign(
    api_key: str,
    *,
    timestamp: Union[int, str],
    nonce: str,
    method: str,
    path: str,
    merchant: str,
    query: str = "",
    idempotency_key: str = "",
    body: Body = b"",
) -> str:
    """The ``X-CC-Signature`` header value of a request: ``"v1=" + hex(HMAC-SHA256(api_key, string_to_sign))``.

    An ``api_key`` that is empty or only spaces and tabs raises
    :class:`CryptoChiefError`.
    """
    _checked_api_key(api_key)
    string_to_sign = hmac_v1_string_to_sign(
        timestamp=timestamp,
        nonce=nonce,
        method=method,
        path=path,
        merchant=merchant,
        query=query,
        idempotency_key=idempotency_key,
        body=body,
    )
    return HMAC_V1_SIGNATURE_PREFIX + _mac(api_key, string_to_sign).hex()


def webhook_v1_string_to_sign(timestamp: int, delivery_id: str, body: Body = b"") -> str:
    """Build the webhook string to sign.

    ``timestamp`` is the ``X-CC-Timestamp`` value in Unix seconds, ``delivery_id``
    the ``X-Webhook-Delivery`` value, ``body`` the body bytes as sent (a ``str``
    is UTF-8 encoded). A timestamp that is not an integer from 1 to 2**63-1 or a
    delivery id that is not 1-128 characters ``[A-Za-z0-9_-]`` raises
    :class:`CryptoChiefError`.
    """
    if (
        isinstance(timestamp, bool)
        or not isinstance(timestamp, int)
        or not 0 < timestamp <= _MAX_TIMESTAMP
    ):
        raise CryptoChiefError(
            "cryptochief: webhook timestamp must be an integer from 1 to 2**63-1"
        )
    if not isinstance(delivery_id, str) or _DELIVERY_ID_RE.fullmatch(delivery_id) is None:
        raise CryptoChiefError(
            "cryptochief: webhook delivery id must be 1-128 characters [A-Za-z0-9_-]"
        )
    body_sha256 = hashlib.sha256(_body_bytes(body)).hexdigest()
    return "\n".join([WEBHOOK_V1_SCOPE, str(timestamp), delivery_id, body_sha256])


def sign_webhook_v1(api_key: str, timestamp: int, delivery_id: str, body: Body = b"") -> str:
    """``X-CC-Signature`` value of a webhook: ``"v1=" + hex(HMAC-SHA256(api_key, string_to_sign))``.

    Raises :class:`CryptoChiefError` on an ``api_key`` that is empty or only
    spaces and tabs, and on the values :func:`webhook_v1_string_to_sign` rejects.
    """
    _checked_api_key(api_key)
    string_to_sign = webhook_v1_string_to_sign(timestamp, delivery_id, body)
    return HMAC_V1_SIGNATURE_PREFIX + _mac(api_key, string_to_sign).hex()


def _mac(api_key: str, string_to_sign: str) -> bytes:
    return hmac.new(
        api_key.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256
    ).digest()
