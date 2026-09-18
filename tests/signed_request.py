"""Check the HMAC v1 headers of a request the client sent."""

import re

import httpx

from cryptochief import hmac_v1_sign

NONCE_RE = re.compile(r"^[0-9a-f]{32}$")


def expected_signature(
    request: httpx.Request,
    path: str,
    *,
    api_key: str = "secret",
    merchant: str = "M1",
    query: str = "",
    idempotency_key: str = "",
) -> str:
    return hmac_v1_sign(
        api_key,
        timestamp=request.headers["X-CC-Timestamp"],
        nonce=request.headers["X-CC-Nonce"],
        method=request.method,
        path=path,
        merchant=merchant,
        query=query,
        idempotency_key=idempotency_key,
        body=request.content,
    )


def assert_signed(
    request: httpx.Request,
    *,
    api_key: str = "secret",
    merchant: str = "M1",
    idempotency_key: str = "",
) -> None:
    """The request carries only HMAC v1 signature headers, valid for its sent bytes."""
    assert "Signature" not in request.headers
    assert request.headers["Merchant"] == merchant
    assert request.headers["X-CC-Timestamp"].isdigit()
    assert NONCE_RE.match(request.headers["X-CC-Nonce"])
    assert request.headers["X-CC-Signature"] == expected_signature(
        request,
        request.url.path,
        api_key=api_key,
        merchant=merchant,
        query=request.url.query.decode("ascii"),
        idempotency_key=idempotency_key,
    )
