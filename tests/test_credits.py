"""Credits service (balance + top-up) through a mocked transport.

Validates the wire shapes (signed empty body against ``/v1/credits/balance``,
signed body with unset optional urls omitted against ``/v1/credits/topup``)
and the full response field mappings, including a negative ``usd_balance`` and
the optional ``order_uuid`` / ``expired_at`` both present and absent.
"""

import httpx

from cryptochief import CryptoChiefClient, canonical_json, sign


async def test_balance_posts_signed_empty_body_and_maps_fields():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(
            200,
            json={
                "credits_balance": -15_200_000,
                "usd_balance": "-1.52",
                "is_postpaid": True,
                "debt_limit_credits": 500_000_000,
                "can_execute_gas_operations": False,
                "gas_ops_min_credits": 3_000_000,
                "timestamp": "2026-08-18T12:00:00Z",
            },
        )

    client = CryptoChiefClient(
        merchant_id="M1", api_key="secret", transport=httpx.MockTransport(handler)
    )
    res = await client.credits.balance()

    req = captured["request"]
    assert str(req.url) == "https://api-processing.crypto-chief.com/v1/credits/balance"
    assert req.method == "POST"
    assert req.headers["Merchant"] == "M1"
    expected = canonical_json({})
    assert req.content.decode("utf-8") == expected == "{}"
    assert req.headers["Signature"] == sign(expected, "secret")

    assert res.credits_balance == -15_200_000
    assert res.usd_balance == "-1.52"
    assert res.is_postpaid is True
    assert res.debt_limit_credits == 500_000_000
    assert res.can_execute_gas_operations is False
    assert res.gas_ops_min_credits == 3_000_000
    assert res.timestamp == "2026-08-18T12:00:00Z"
    await client.aclose()


async def test_topup_posts_signed_body_with_urls_and_maps_full_response():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(
            200,
            json={
                "invoice_id": 90210,
                "payment_link": "https://pay.crypto-chief.com/topup/abc123",
                "amount": "150.00",
                "currency": "USDT",
                "status": "pending",
                "order_uuid": "018f2f3a-7c1d-7e6a-b1aa-3f0e5d9c1234",
                "expired_at": 1_766_000_000,
            },
        )

    client = CryptoChiefClient(
        merchant_id="M1", api_key="secret", transport=httpx.MockTransport(handler)
    )
    res = await client.credits.topup(
        amount="150.00",
        currency="USDT",
        url_success="https://example.com/ok",
        url_error="https://example.com/fail",
    )

    req = captured["request"]
    assert str(req.url) == "https://api-processing.crypto-chief.com/v1/credits/topup"
    assert req.method == "POST"
    assert req.headers["Merchant"] == "M1"
    expected = canonical_json(
        {
            "amount": "150.00",
            "currency": "USDT",
            "url_success": "https://example.com/ok",
            "url_error": "https://example.com/fail",
        }
    )
    assert req.content.decode("utf-8") == expected
    assert req.headers["Signature"] == sign(expected, "secret")

    assert res.invoice_id == 90210
    assert res.payment_link == "https://pay.crypto-chief.com/topup/abc123"
    assert res.amount == "150.00"
    assert res.currency == "USDT"
    assert res.status == "pending"
    assert res.order_uuid == "018f2f3a-7c1d-7e6a-b1aa-3f0e5d9c1234"
    assert res.expired_at == 1_766_000_000
    await client.aclose()


async def test_topup_omits_unset_urls_and_defaults_optional_response_fields():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(
            200,
            json={
                "invoice_id": 7,
                "payment_link": "https://pay.crypto-chief.com/topup/xyz789",
                "amount": "25",
                "currency": "USDC",
                "status": "pending",
            },
        )

    client = CryptoChiefClient(
        merchant_id="M1", api_key="secret", transport=httpx.MockTransport(handler)
    )
    res = await client.credits.topup(amount="25", currency="USDC")

    req = captured["request"]
    body = req.content.decode("utf-8")
    expected = canonical_json({"amount": "25", "currency": "USDC"})
    assert body == expected == '{"amount":"25","currency":"USDC"}'
    assert "url_success" not in body
    assert "url_error" not in body
    assert req.headers["Signature"] == sign(expected, "secret")

    assert res.invoice_id == 7
    assert res.payment_link == "https://pay.crypto-chief.com/topup/xyz789"
    assert res.amount == "25"
    assert res.currency == "USDC"
    assert res.status == "pending"
    assert res.order_uuid == ""
    assert res.expired_at == 0
    await client.aclose()
