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


def test_order_body_code_comes_from_error_code_not_the_sentence():
    """An order reported on a non-2xx is no envelope: ``error`` is the human
    sentence there, and the machine code travels in ``error_code``."""
    body = json.dumps(
        {
            "id": 4472,
            "idempotency_key": "energy-2026-09-18-0002",
            "status": "refused",
            "settled": True,
            "needs_attention": False,
            "error_code": "SUPPLIER_REFUSED",
            "error": "no supplier could take this order; nothing was bought",
            "created_at": "2026-09-18T12:10:00Z",
        }
    )
    err = parse_api_error(502, body)

    assert err.code == "SUPPLIER_REFUSED"
    assert err.message == "no supplier could take this order; nothing was bought"
    assert err.raw == body


def test_order_body_without_error_code_falls_back_to_http_status():
    body = json.dumps({"id": 4473, "status": "unresolved", "error": "supplier never answered"})
    err = parse_api_error(409, body)

    assert err.code == "HTTP_409"
    assert err.message == "supplier never answered"


def test_envelope_fields_are_not_trimmed():
    err = parse_api_error(400, json.dumps({"ok": False, "error": " LABEL_TOO_LONG ", "msg": " m "}))
    assert err.code == " LABEL_TOO_LONG "
    assert err.message == " m "

    relayed = parse_api_error(400, json.dumps({"ok": False, "error": "SERVICE_ERROR", "msg": " x"}))
    assert relayed.code == " x"

    white_label = {"error": {"name": "N", "message": " m ", "details": {"code": " C "}}}
    err = parse_api_error(401, json.dumps(white_label))
    assert (err.code, err.message) == (" C ", " m ")


def test_empty_envelope_falls_back_to_http_status():
    assert parse_api_error(503, "not json at all").code == "HTTP_503"
    assert parse_api_error(503, json.dumps({"ok": False})).code == "HTTP_503"


def test_gateway_envelope_server_time():
    body = json.dumps(
        {
            "ok": False,
            "error": "SIGNATURE_TIMESTAMP_OUT_OF_RANGE",
            "msg": "timestamp out of range",
            "server_time": 1789430400,
        }
    )
    err = parse_api_error(401, body)
    assert err.code == ErrorCode.SIGNATURE_TIMESTAMP_OUT_OF_RANGE
    assert err.message == "timestamp out of range"
    assert err.server_time == 1789430400


def white_label_body(code, *, server_time=None, message="Unauthorized"):
    details = {"code": code}
    body = {
        "data": None,
        "error": {"status": 401, "name": "UnauthorizedError", "message": message},
    }
    if code is not None:
        body["error"]["details"] = details
    if server_time is not None:
        details["server_time"] = server_time
        body["server_time"] = server_time
    return json.dumps(body)


def test_white_label_envelope_code_comes_from_details():
    body = white_label_body("INVALID_SIGNATURE", message="Invalid signature")
    err = parse_api_error(401, body)

    assert err.code == ErrorCode.INVALID_SIGNATURE
    assert err.message == "Invalid signature"
    assert err.http_status == 401
    assert err.raw == body
    assert err.server_time is None


def test_white_label_envelope_server_time():
    body = white_label_body("SIGNATURE_TIMESTAMP_OUT_OF_RANGE", server_time=1789430400)
    err = parse_api_error(401, body)

    assert err.code == ErrorCode.SIGNATURE_TIMESTAMP_OUT_OF_RANGE
    assert err.server_time == 1789430400


def test_white_label_envelope_server_time_only_in_details():
    body = json.dumps(
        {
            "data": None,
            "error": {
                "status": 401,
                "name": "UnauthorizedError",
                "message": "Unauthorized",
                "details": {"code": "SIGNATURE_TIMESTAMP_OUT_OF_RANGE", "server_time": 1789430400},
            },
        }
    )
    assert parse_api_error(401, body).server_time == 1789430400


def test_white_label_envelope_without_code_falls_back_to_error_name():
    unauthorized = parse_api_error(401, white_label_body(None, message="Invalid signature"))
    assert unauthorized.code == "UnauthorizedError"
    assert unauthorized.message == "Invalid signature"

    body = json.dumps(
        {
            "data": None,
            "error": {
                "status": 400,
                "name": "ValidationError",
                "message": "Invalid",
                "details": {},
            },
        }
    )
    assert parse_api_error(400, body).code == "ValidationError"


def test_white_label_envelope_without_code_or_name_falls_back_to_http_status():
    body = json.dumps(
        {"data": None, "error": {"status": 409, "message": "Conflict", "details": {"code": ""}}}
    )
    err = parse_api_error(409, body)
    assert err.code == "HTTP_409"
    assert err.message == "Conflict"


def test_error_docs_name_the_white_label_installation():
    for doc in (APIError.__doc__, parse_api_error.__doc__):
        assert doc is not None
        assert "white-label installation" in doc.lower()
        assert "contour" not in doc.lower()


def test_server_time_rejects_non_numbers():
    for value in ("1789430400", True, None):
        body = json.dumps({"ok": False, "error": "X", "server_time": value})
        assert parse_api_error(401, body).server_time is None


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
