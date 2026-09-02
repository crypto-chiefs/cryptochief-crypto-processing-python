"""Error-envelope resolution: which wire field becomes ``APIError.code``."""

import json

import httpx
import pytest

from cryptochief import APIError, CryptoChiefClient, ErrorCode, is_api_error
from cryptochief.transport import parse_api_error

LABEL_SENTENCE = "label is longer than 255 characters"


def _client(response: httpx.Response) -> CryptoChiefClient:
    return CryptoChiefClient(
        merchant_id="M1",
        api_key="secret",
        transport=httpx.MockTransport(lambda request: response),
        retry_backoff={"base_ms": 1, "max_ms": 2},
    )


def test_gateway_envelope_code_comes_from_error_field():
    """The gateway's own refusal puts the machine code in ``error``."""
    body = json.dumps({"ok": False, "error": "LABEL_TOO_LONG", "msg": LABEL_SENTENCE})
    err = parse_api_error(400, body)

    assert err.code == ErrorCode.LABEL_TOO_LONG
    assert err.code == "LABEL_TOO_LONG"
    # the sentence is the human half, never the code
    assert err.message == LABEL_SENTENCE
    assert LABEL_SENTENCE in str(err)
    assert err.raw == body  # full body preserved
    assert err.http_status == 400


def test_upstream_envelope_code_still_comes_from_msg():
    """A relayed upstream refusal keeps its token in ``msg``."""
    body = json.dumps({"ok": False, "error": "SERVICE_ERROR", "msg": "wallet_not_found"})
    err = parse_api_error(400, body)

    assert err.code == "wallet_not_found"
    assert err.message == "wallet_not_found"
    assert err.raw == body


def test_error_only_envelope():
    err = parse_api_error(400, json.dumps({"ok": False, "error": "INVALID_PARAMS"}))
    assert err.code == ErrorCode.INVALID_PARAMS
    assert err.message == "INVALID_PARAMS"


def test_bare_service_error_falls_back_to_the_marker():
    """``SERVICE_ERROR`` with nothing in ``msg`` is all we have to report."""
    err = parse_api_error(502, json.dumps({"ok": False, "error": "SERVICE_ERROR", "msg": ""}))
    assert err.code == ErrorCode.SERVICE_ERROR


def test_empty_envelope_falls_back_to_http_status():
    assert parse_api_error(503, "not json at all").code == "HTTP_503"
    assert parse_api_error(503, json.dumps({"ok": False})).code == "HTTP_503"


async def test_gateway_code_reaches_the_caller_typed():
    """``is_api_error`` / ``ErrorCode`` comparison matches a gateway-side code."""

    client = _client(
        httpx.Response(400, json={"ok": False, "error": "LABEL_TOO_LONG", "msg": LABEL_SENTENCE})
    )
    with pytest.raises(APIError) as ei:
        await client.wallets.set_label("0xAbC", "x" * 256)

    assert is_api_error(ei.value, ErrorCode.LABEL_TOO_LONG)
    assert ei.value.code == ErrorCode.LABEL_TOO_LONG
    assert ei.value.message == LABEL_SENTENCE
    await client.aclose()
