import asyncio
import json

import httpx
import pytest

import cryptochief.client
import vectors
from cryptochief import (
    APIError,
    Chain,
    CryptoChiefClient,
    CryptoChiefError,
    ErrorCode,
    EstimatePayoutRequest,
    idempotency_key,
    is_api_error,
)
from signed_request import NONCE_RE, assert_signed
from signed_request import expected_signature as expected_hmac

HMAC_VECTORS = {v["name"]: v for v in vectors.REQUEST_VECTORS}


def make_client(handler, **overrides):
    calls = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(len(calls) - 1, request)

    client = CryptoChiefClient(
        merchant_id="M1",
        api_key="secret",
        transport=httpx.MockTransport(wrapped),
        retry_backoff={"base_ms": 1, "max_ms": 2},
        **overrides,
    )
    return client, calls


async def test_signs_body_and_sets_auth_headers():
    def handler(attempt, request):
        return httpx.Response(
            200, json={"amount_to_receive": "0.0099", "fee_info": {"fee_mode": "service"}}
        )

    client, calls = make_client(handler)
    res = await client.payouts.estimate(
        EstimatePayoutRequest(
            network=Chain.ETH_SEPOLIA,
            coin="ETH",
            amount="0.0001",
            to_address="0xAbC",
            from_addresses=["0x111", "0x222"],
        )
    )
    assert res.amount_to_receive == "0.0099"
    assert res.fee_info.fee_mode == "service"

    req = calls[0]
    assert str(req.url) == "https://api-processing.crypto-chief.com/v1/payout/estimate"
    assert req.method == "POST"
    assert req.headers["Merchant"] == "M1"
    assert req.headers["Content-Type"] == "application/json"

    assert json.loads(req.content) == {
        "amount": "0.0001",
        "coin": "ETH",
        "from_addresses": ["0x111", "0x222"],
        "network": "ETH_SEPOLIA",
        "to_address": "0xAbC",
    }
    assert_signed(req)
    await client.aclose()


async def test_maps_error_envelope_to_api_error():
    def handler(attempt, request):
        return httpx.Response(
            400, json={"error": "SERVICE_ERROR", "msg": "INSUFFICIENT_FUNDS", "ok": False}
        )

    client, _ = make_client(handler)
    with pytest.raises(APIError) as ei:
        await client.payouts.info("u1")
    assert is_api_error(ei.value, ErrorCode.INSUFFICIENT_FUNDS)
    assert ei.value.http_status == 400
    await client.aclose()


async def test_retries_5xx_then_succeeds():
    def handler(attempt, request):
        if attempt == 0:
            return httpx.Response(503, text="upstream")
        return httpx.Response(200, json={"uuid": "u1", "status": "queue"})

    client, calls = make_client(handler)
    res = await client.payouts.info("u1")
    assert res.uuid == "u1"
    assert len(calls) == 2
    await client.aclose()


async def test_does_not_retry_4xx():
    def handler(attempt, request):
        return httpx.Response(400, json={"error": "INVALID_PARAMS", "ok": False})

    client, calls = make_client(handler)
    with pytest.raises(APIError):
        await client.payouts.info("x")
    assert len(calls) == 1
    await client.aclose()


async def test_retries_network_errors():
    def handler(attempt, request):
        if attempt == 0:
            raise httpx.ConnectError("fail")
        return httpx.Response(200, json={"uuid": "u2"})

    client, calls = make_client(handler)
    res = await client.payouts.info("u2")
    assert res.uuid == "u2"
    assert len(calls) == 2
    await client.aclose()


def ok_handler(attempt, request):
    return httpx.Response(200, json={"uuid": "u1"})


async def test_sends_only_hmac_v1_headers():
    client, calls = make_client(ok_handler)
    client._clock = lambda: 1789430400.9
    await client.payouts.info("u1")

    req = calls[0]
    assert "Signature" not in req.headers
    assert req.headers["X-CC-Timestamp"] == "1789430400"
    assert NONCE_RE.match(req.headers["X-CC-Nonce"])
    assert req.headers["X-CC-Signature"] == expected_hmac(req, "/v1/payout/info")
    assert "Idempotency-Key" not in req.headers
    await client.aclose()


async def test_hmac_matches_gateway_vector(monkeypatch):
    v = HMAC_VECTORS["wallets_info"]
    monkeypatch.setattr(cryptochief.client.secrets, "token_hex", lambda n: v["nonce"])

    def handler(attempt, request):
        return httpx.Response(200, json={})

    calls = []
    client = CryptoChiefClient(
        merchant_id=v["merchant"],
        api_key=v["api_key"],
        transport=httpx.MockTransport(lambda r: calls.append(r) or handler(0, r)),
    )
    client._clock = lambda: int(v["timestamp"])
    await client.request(v["path"], json.loads(v["body"]))

    req = calls[0]
    assert req.content == v["body"].encode("utf-8")
    assert req.headers["X-CC-Timestamp"] == v["timestamp"]
    assert req.headers["X-CC-Nonce"] == v["nonce"]
    assert req.headers["X-CC-Signature"] == "v1=" + v["signature"]
    await client.aclose()


async def test_query_comes_from_url_and_path_excludes_base_url(monkeypatch):
    v = HMAC_VECTORS["query"]
    monkeypatch.setattr(cryptochief.client.secrets, "token_hex", lambda n: v["nonce"])

    calls = []
    client = CryptoChiefClient(
        merchant_id=v["merchant"],
        api_key=v["api_key"],
        base_url="https://wl.example/platform/",
        transport=httpx.MockTransport(
            lambda r: calls.append(r) or httpx.Response(200, json={})
        ),
    )
    client._clock = lambda: int(v["timestamp"])
    await client.request(v["path"] + "?" + v["query"], json.loads(v["body"]))

    req = calls[0]
    assert str(req.url) == "https://wl.example/platform/v1/payments/history?a=1&b=2"
    assert req.content == v["body"].encode("utf-8")
    assert req.headers["X-CC-Signature"] == "v1=" + v["signature"]
    await client.aclose()


async def test_idempotency_key_is_sent_and_signed():
    client, calls = make_client(ok_handler)
    await client.request("/v1/payout/execute", {"order_id": "po-1"}, idempotency_key="k-1")

    req = calls[0]
    assert req.headers["Idempotency-Key"] == "k-1"
    assert req.headers["X-CC-Signature"] == expected_hmac(
        req, "/v1/payout/execute", idempotency_key="k-1"
    )
    assert req.headers["X-CC-Signature"] != expected_hmac(req, "/v1/payout/execute")
    await client.aclose()


async def test_idempotency_key_with_line_break_is_rejected_before_sending():
    client, calls = make_client(ok_handler)
    with pytest.raises(CryptoChiefError):
        await client.request("/v1/payout/execute", {}, idempotency_key="a\nb")
    assert calls == []
    await client.aclose()


@pytest.mark.parametrize(
    "key", ["ключ-1", "  k-1  ", "k-1\t", "\tk-1", " ", "k\x01", "k\x7f", "k\rv"]
)
async def test_idempotency_key_the_server_cannot_reproduce_is_rejected_before_sending(key):
    client, calls = make_client(ok_handler)
    with pytest.raises(CryptoChiefError) as ei:
        await client.request("/v1/payout/execute", {}, idempotency_key=key)
    assert not isinstance(ei.value, APIError)
    assert calls == []
    await client.aclose()


async def test_idempotency_key_keeps_inner_spaces():
    client, calls = make_client(ok_handler)
    await client.request("/v1/payout/execute", {}, idempotency_key="k 1")

    req = calls[0]
    assert req.headers["Idempotency-Key"] == "k 1"
    assert req.headers["X-CC-Signature"] == expected_hmac(
        req, "/v1/payout/execute", idempotency_key="k 1"
    )
    await client.aclose()


async def test_idempotency_key_from_the_context_is_sent_and_signed():
    client, calls = make_client(ok_handler)
    with idempotency_key("k-ctx"):
        await client.payouts.info("u1")  # a service call, unchanged
        await client.request("/v1/payout/execute", {}, idempotency_key="k-arg")
        await client.request("/v1/payout/execute", {}, idempotency_key="")
        await asyncio.create_task(client.payouts.info("u2"))
    await client.payouts.info("u3")

    service, arg, none, task, outside = calls
    assert service.headers["Idempotency-Key"] == "k-ctx"
    assert service.headers["X-CC-Signature"] == expected_hmac(
        service, "/v1/payout/info", idempotency_key="k-ctx"
    )
    assert arg.headers["Idempotency-Key"] == "k-arg"  # the argument wins
    assert task.headers["Idempotency-Key"] == "k-ctx"
    assert "Idempotency-Key" not in none.headers
    assert "Idempotency-Key" not in outside.headers
    assert outside.headers["X-CC-Signature"] == expected_hmac(outside, "/v1/payout/info")
    await client.aclose()


@pytest.mark.parametrize("key", ["ключ-1", " k-1", "k-1\t", " ", "k\n1"])
def test_idempotency_key_context_checks_the_key(key):
    with pytest.raises(CryptoChiefError, match="idempotency_key"):
        with idempotency_key(key):
            pass


async def test_signed_get_carries_the_query_and_no_body():
    client, calls = make_client(ok_handler)
    await client.request("/v1/payments/order/info?uuid=u1&note=a%20b", method="get")

    req = calls[0]
    assert req.method == "GET"
    assert req.content == b""
    assert "Content-Type" not in req.headers
    assert req.headers["X-CC-Signature"] == expected_hmac(
        req, "/v1/payments/order/info", query="uuid=u1&note=a%20b"
    )
    assert_signed(req)
    await client.aclose()


@pytest.mark.parametrize("method", ["get", "GET", "put", "PATCH", "delete"])
async def test_signed_request_with_an_arbitrary_method(method):
    client, calls = make_client(ok_handler)
    await client.request("/v1/wallets/info", {"address": "T9y"}, method=method)

    req = calls[0]
    assert req.method == method.upper()
    assert req.headers["Content-Type"] == "application/json"
    assert req.headers["X-CC-Signature"] == expected_hmac(req, "/v1/wallets/info")
    await client.aclose()


async def test_percent_escaped_path_is_signed_as_the_server_decodes_it():
    client, calls = make_client(ok_handler)
    await client.request("/v1/a%2Fb%20c?q=1%202", {"uuid": "u1"})

    req = calls[0]
    assert req.url.raw_path == b"/v1/a%2Fb%20c?q=1%202"
    assert req.headers["X-CC-Signature"] == expected_hmac(req, "/v1/a/b c", query="q=1%202")
    assert_signed(req)
    await client.aclose()


async def test_percent_escaped_path_excludes_the_base_url_prefix():
    client, calls = make_client(ok_handler, base_url="https://wl.example/platform")
    await client.request("/v1/a%2Fb", {"uuid": "u1"})

    req = calls[0]
    assert req.url.raw_path == b"/platform/v1/a%2Fb"
    assert req.headers["X-CC-Signature"] == expected_hmac(req, "/v1/a/b")
    await client.aclose()


async def test_retry_recomputes_timestamp_nonce_and_signature():
    ticks = iter([1789430400.0, 1789430460.0, 1789430520.0])

    def handler(attempt, request):
        if attempt == 0:
            return httpx.Response(503, text="upstream")
        return httpx.Response(200, json={"uuid": "u1"})

    client, calls = make_client(handler)
    client._clock = lambda: next(ticks)
    await client.payouts.info("u1")

    assert len(calls) == 2
    first, second = calls
    assert first.headers["X-CC-Timestamp"] == "1789430400"
    assert second.headers["X-CC-Timestamp"] == "1789430460"
    assert first.headers["X-CC-Nonce"] != second.headers["X-CC-Nonce"]
    assert first.headers["X-CC-Signature"] != second.headers["X-CC-Signature"]
    for req in calls:
        assert req.headers["X-CC-Signature"] == expected_hmac(req, "/v1/payout/info")
    assert first.content == second.content
    await client.aclose()


async def test_client_has_no_signature_scheme_option():
    with pytest.raises(TypeError):
        CryptoChiefClient(merchant_id="M1", api_key="secret", hmac_only=True)  # type: ignore[call-arg]


def out_of_range(server_time):
    body = {
        "ok": False,
        "error": "SIGNATURE_TIMESTAMP_OUT_OF_RANGE",
        "msg": "X-CC-Timestamp differs from server time by more than 300 seconds",
    }
    if server_time is not None:
        body["server_time"] = server_time
    return httpx.Response(401, json=body)


def out_of_range_white_label(server_time):
    details = {"code": "SIGNATURE_TIMESTAMP_OUT_OF_RANGE", "server_time": server_time}
    return httpx.Response(
        401,
        json={
            "data": None,
            "error": {
                "status": 401,
                "name": "UnauthorizedError",
                "message": "X-CC-Timestamp is out of range",
                "details": details,
            },
            "server_time": server_time,
        },
    )


async def test_white_label_timestamp_out_of_range_corrects_clock_once_and_retries():
    def handler(attempt, request):
        if attempt == 0:
            return out_of_range_white_label(1789430400)
        return httpx.Response(200, json={"uuid": "u1"})

    client, calls = make_client(handler)
    client._clock = lambda: 1789429000.5
    res = await client.payouts.info("u1")

    assert res.uuid == "u1"
    assert len(calls) == 2
    assert calls[0].headers["X-CC-Timestamp"] == "1789429000"
    assert calls[1].headers["X-CC-Timestamp"] == "1789430400"
    assert calls[0].headers["X-CC-Nonce"] != calls[1].headers["X-CC-Nonce"]
    assert calls[1].headers["X-CC-Signature"] == expected_hmac(calls[1], "/v1/payout/info")
    await client.aclose()


async def test_white_label_timestamp_out_of_range_is_retried_only_once():
    client, calls = make_client(
        lambda attempt, request: out_of_range_white_label(1789430400 + attempt)
    )
    client._clock = lambda: 1789429000.0
    with pytest.raises(APIError) as ei:
        await client.payouts.info("u1")

    assert ei.value.code == ErrorCode.SIGNATURE_TIMESTAMP_OUT_OF_RANGE
    assert ei.value.http_status == 401
    assert ei.value.server_time == 1789430401
    assert len(calls) == 2
    await client.aclose()


async def test_timestamp_out_of_range_corrects_clock_once_and_retries():
    def handler(attempt, request):
        if attempt == 0:
            return out_of_range(1789430400)
        return httpx.Response(200, json={"uuid": "u1"})

    client, calls = make_client(handler)
    client._clock = lambda: 1789429000.5
    res = await client.payouts.info("u1")

    assert res.uuid == "u1"
    assert len(calls) == 2
    assert calls[0].headers["X-CC-Timestamp"] == "1789429000"
    assert calls[1].headers["X-CC-Timestamp"] == "1789430400"
    assert calls[0].headers["X-CC-Nonce"] != calls[1].headers["X-CC-Nonce"]
    assert calls[1].headers["X-CC-Signature"] == expected_hmac(calls[1], "/v1/payout/info")

    await client.payouts.info("u1")  # the offset persists on the client
    assert calls[2].headers["X-CC-Timestamp"] == "1789430400"
    await client.aclose()


async def test_timestamp_out_of_range_is_retried_only_once():
    client, calls = make_client(lambda attempt, request: out_of_range(1789430400 + attempt))
    client._clock = lambda: 1789429000.0
    with pytest.raises(APIError) as ei:
        await client.payouts.info("u1")

    assert ei.value.code == ErrorCode.SIGNATURE_TIMESTAMP_OUT_OF_RANGE
    assert ei.value.http_status == 401
    assert len(calls) == 2
    await client.aclose()


async def test_timestamp_out_of_range_without_server_time_is_not_retried():
    client, calls = make_client(lambda attempt, request: out_of_range(None))
    with pytest.raises(APIError) as ei:
        await client.payouts.info("u1")

    assert ei.value.code == ErrorCode.SIGNATURE_TIMESTAMP_OUT_OF_RANGE
    assert len(calls) == 1
    await client.aclose()


@pytest.mark.parametrize(
    "status,code",
    [(401, "SIGNATURE_REPLAYED"), (413, "PAYLOAD_TOO_LARGE")],
)
async def test_new_auth_codes_are_typed_and_not_retried(status, code):
    client, calls = make_client(
        lambda attempt, request: httpx.Response(status, json={"ok": False, "error": code})
    )
    with pytest.raises(APIError) as ei:
        await client.payouts.info("u1")

    assert is_api_error(ei.value, ErrorCode(code))
    assert len(calls) == 1
    await client.aclose()
