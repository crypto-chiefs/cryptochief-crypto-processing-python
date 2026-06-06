import httpx
import pytest

from cryptochief import (
    APIError,
    Chain,
    CryptoChiefClient,
    ErrorCode,
    EstimatePayoutRequest,
    canonical_json,
    is_api_error,
    sign,
)


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

    expected = canonical_json(
        {
            "amount": "0.0001",
            "coin": "ETH",
            "from_addresses": ["0x111", "0x222"],
            "network": "ETH_SEPOLIA",
            "to_address": "0xAbC",
        }
    )
    assert req.content.decode("utf-8") == expected
    assert req.headers["Signature"] == sign(expected, "secret")
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
