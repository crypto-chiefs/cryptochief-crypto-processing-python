"""Native-coin purchase service through a mocked transport.

Validates the wire shapes of ``/v1/native/quote`` (free), ``/v1/native/buy``
(required signed ``Idempotency-Key`` header) and ``/v1/native/order`` (lookup
by idempotency key), and the response mappings - including the recovery of an
order reported on a non-2xx answer (502/402 ``refused``, 409 ``unresolved``).
On a ``refused`` order nothing was charged: ``total_usd`` / ``credits`` /
``tx_hash`` are absent, while ``transfer_fee`` / ``coin_price_usd`` arrive as
``""`` / ``"0.00"`` - no price was kept.
"""

import json

import httpx
import pytest

from cryptochief import (
    APIError,
    CryptoChiefClient,
    CryptoChiefError,
    NativeBuyRequest,
    NativeOrderStatus,
    NativeQuoteRequest,
    idempotency_key,
    is_native_order_terminal,
)
from signed_request import assert_signed

TRON = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
KEY = "native-2026-09-18-0001"

QUOTE_BODY = {
    "ref": "nq_01J8ZK3W2M",
    "network": "TRON_MAINNET",
    "receive_address": TRON,
    "amount": "25",
    "coin_price_usd": "7.14",
    "transfer_fee": "1.1",
    "transfer_fee_usd": "0.31",
    "subtotal_usd": "7.45",
    "total_usd": "9.69",
    "credits": 96_900_000,
    "coin_usd": "0.28571429",
    "expires_at": "2026-09-18T12:01:30Z",
    "expires_in_sec": 90,
}

DELIVERED_ORDER_BODY = {
    "id": 4201,
    "idempotency_key": KEY,
    "status": "delivered",
    "network": "TRON_MAINNET",
    "receive_address": TRON,
    "amount": "25",
    "tx_hash": "a1b2c3d4e5f6",
    "transfer_fee": "1.1",
    "transfer_fee_usd": "0.31",
    "coin_price_usd": "7.14",
    "total_usd": "9.69",
    "credits": 96_900_000,
    "coin_usd": "0.28571429",
    "settled": True,
    "needs_attention": False,
    "created_at": "2026-09-18T12:00:01Z",
    "delivered_at": "2026-09-18T12:00:04Z",
}

# A refused order (502) was never charged: tx_hash / total_usd / credits are
# absent, the ever-present price fields arrive zeroed, and the failure carries
# a machine code plus a sanitised sentence.
REFUSED_ORDER_BODY = {
    "id": 4202,
    "idempotency_key": KEY,
    "status": "refused",
    "network": "TRON_MAINNET",
    "receive_address": TRON,
    "amount": "25",
    "transfer_fee": "",
    "transfer_fee_usd": "0.00",
    "coin_price_usd": "0.00",
    "coin_usd": "",
    "settled": True,
    "needs_attention": False,
    "error_code": "INSUFFICIENT_LIQUIDITY",
    "error": "we cannot fund that sale from our own wallet right now; nothing was bought and nothing was charged",
    "created_at": "2026-09-18T12:10:00Z",
}

# An unresolved order (409): the transfer's outcome never arrived, so the
# coins may already be sent - charged, not settled, needs attention.
UNRESOLVED_ORDER_BODY = {
    "id": 4203,
    "idempotency_key": KEY,
    "status": "unresolved",
    "network": "TRON_MAINNET",
    "receive_address": TRON,
    "amount": "25",
    "transfer_fee": "1.1",
    "transfer_fee_usd": "0.31",
    "coin_price_usd": "7.14",
    "total_usd": "9.69",
    "credits": 96_900_000,
    "coin_usd": "0.28571429",
    "settled": False,
    "needs_attention": True,
    "error_code": "SEND_UNKNOWN",
    "error": "the transfer's outcome never came back, so the order will not be retried - it may already have been sent; ask us to check it",
    "created_at": "2026-09-18T12:11:00Z",
}

# A 402 refusal: the credits balance did not cover the order.
INSUFFICIENT_CREDITS_ORDER_BODY = {
    **REFUSED_ORDER_BODY,
    "id": 4204,
    "error_code": "INSUFFICIENT_CREDITS",
    "error": "your credit balance did not cover this order; nothing was bought and nothing was charged",
}


def _client(handler, *, retries: int = 3) -> CryptoChiefClient:
    return CryptoChiefClient(
        merchant_id="M1",
        api_key="secret",
        transport=httpx.MockTransport(handler),
        retries=retries,
        retry_backoff={"base_ms": 1, "max_ms": 2},
    )


async def test_quote_posts_body_and_maps_fields():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json=QUOTE_BODY)

    client = _client(handler)
    quote = await client.native.quote(
        NativeQuoteRequest(network="TRON_MAINNET", receive_address=TRON, amount="25")
    )

    req = captured["request"]
    assert str(req.url) == "https://api-processing.crypto-chief.com/v1/native/quote"
    assert req.method == "POST"
    assert json.loads(req.content) == {
        "network": "TRON_MAINNET",
        "receive_address": TRON,
        "amount": "25",
    }
    assert_signed(req)

    assert quote.ref == "nq_01J8ZK3W2M"
    assert quote.network == "TRON_MAINNET"
    assert quote.receive_address == TRON
    assert quote.amount == "25"
    assert quote.coin_price_usd == "7.14"
    assert quote.transfer_fee == "1.1"
    assert quote.transfer_fee_usd == "0.31"
    assert quote.subtotal_usd == "7.45"
    assert quote.total_usd == "9.69"
    assert quote.credits == 96_900_000
    assert quote.coin_usd == "0.28571429"
    assert quote.expires_at == "2026-09-18T12:01:30Z"
    assert quote.expires_in_sec == 90
    await client.aclose()


async def test_buy_sends_signed_idempotency_key_and_maps_order():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json=DELIVERED_ORDER_BODY)

    client = _client(handler)
    order = await client.native.buy(
        NativeBuyRequest(network="TRON_MAINNET", receive_address=TRON, amount="25"),
        idempotency_key=KEY,
    )

    req = captured["request"]
    assert str(req.url) == "https://api-processing.crypto-chief.com/v1/native/buy"
    assert req.headers["Idempotency-Key"] == KEY
    assert json.loads(req.content) == {
        "network": "TRON_MAINNET",
        "receive_address": TRON,
        "amount": "25",
    }
    assert_signed(req, idempotency_key=KEY)  # the key is covered by the signature

    assert order.id == 4201
    assert order.idempotency_key == KEY
    assert order.status == "delivered"
    assert is_native_order_terminal(order.status)
    assert order.network == "TRON_MAINNET"
    assert order.receive_address == TRON
    assert order.amount == "25"
    assert order.tx_hash == "a1b2c3d4e5f6"
    assert order.transfer_fee == "1.1"
    assert order.transfer_fee_usd == "0.31"
    assert order.coin_price_usd == "7.14"
    assert order.total_usd == "9.69"
    assert order.credits == 96_900_000
    assert order.coin_usd == "0.28571429"
    assert order.settled is True
    assert order.needs_attention is False
    assert order.error_code is None
    assert order.error is None
    assert order.created_at == "2026-09-18T12:00:01Z"
    assert order.delivered_at == "2026-09-18T12:00:04Z"
    await client.aclose()


async def test_buy_with_quote_ref_sends_only_the_ref():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json=DELIVERED_ORDER_BODY)

    client = _client(handler)
    with idempotency_key(KEY):
        await client.native.buy(NativeBuyRequest(quote_ref="nq_01J8ZK3W2M"))

    req = captured["request"]
    assert req.headers["Idempotency-Key"] == KEY
    assert req.content.decode("utf-8") == '{"quote_ref":"nq_01J8ZK3W2M"}'
    assert_signed(req, idempotency_key=KEY)
    await client.aclose()


async def test_buy_without_key_raises_before_sending():
    sent: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json=DELIVERED_ORDER_BODY)

    client = _client(handler)
    with pytest.raises(CryptoChiefError, match="idempotency_key is required"):
        await client.native.buy(NativeBuyRequest(network="TRON_MAINNET", amount="25"))
    await client.aclose()
    assert sent == []


async def test_buy_refused_order_comes_back_on_a_502():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, json=REFUSED_ORDER_BODY)

    # 502 retries are pointless here - the order is settled. retries=0.
    client = _client(handler, retries=0)
    order = await client.native.buy(
        NativeBuyRequest(network="TRON_MAINNET", receive_address=TRON, amount="25"),
        idempotency_key=KEY,
    )
    await client.aclose()

    assert order.id == 4202
    assert order.status == NativeOrderStatus.REFUSED == "refused"
    assert is_native_order_terminal(order.status)
    assert order.settled is True
    assert order.needs_attention is False
    assert order.error_code == "INSUFFICIENT_LIQUIDITY"
    assert order.error == (
        "we cannot fund that sale from our own wallet right now; "
        "nothing was bought and nothing was charged"
    )
    # nothing was sent or charged: tx_hash / total_usd / credits are absent on
    # the wire, None here
    assert order.tx_hash is None
    assert order.total_usd is None
    assert order.credits is None
    # the ever-present price fields arrive zeroed rather than absent
    assert order.transfer_fee == ""
    assert order.transfer_fee_usd == "0.00"
    assert order.coin_price_usd == "0.00"
    assert order.coin_usd == ""
    assert order.delivered_at is None


async def test_buy_refused_for_insufficient_credits_comes_back_on_a_402():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(402, json=INSUFFICIENT_CREDITS_ORDER_BODY)

    client = _client(handler)
    order = await client.native.buy(
        NativeBuyRequest(network="TRON_MAINNET", receive_address=TRON, amount="25"),
        idempotency_key=KEY,
    )
    await client.aclose()

    assert order.status == "refused"
    assert order.error_code == "INSUFFICIENT_CREDITS"
    assert order.credits is None


async def test_buy_unresolved_order_comes_back_on_a_409():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json=UNRESOLVED_ORDER_BODY)

    client = _client(handler)
    order = await client.native.buy(
        NativeBuyRequest(network="TRON_MAINNET", receive_address=TRON, amount="25"),
        idempotency_key=KEY,
    )
    await client.aclose()

    # 409 + needs_attention: do NOT retry; follow the order with order()
    assert order.status == NativeOrderStatus.UNRESOLVED == "unresolved"
    assert not is_native_order_terminal(order.status)
    assert order.settled is False
    assert order.needs_attention is True
    assert order.error_code == "SEND_UNKNOWN"
    # charged, because the coins may already be sent
    assert order.credits == 96_900_000


async def test_buy_envelope_error_raises_as_before():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            409,
            json={
                "ok": False,
                "error": "QUOTE_EXPIRED",
                "msg": "that quote has expired; ask for a new price",
            },
        )

    client = _client(handler)
    with pytest.raises(APIError) as ei:
        await client.native.buy(NativeBuyRequest(quote_ref="nq_01J8ZK3W2M"), idempotency_key=KEY)
    await client.aclose()

    assert ei.value.code == "QUOTE_EXPIRED"
    assert ei.value.http_status == 409


async def test_order_posts_idempotency_key_and_maps_order():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json=DELIVERED_ORDER_BODY)

    client = _client(handler)
    order = await client.native.order(KEY)

    req = captured["request"]
    assert str(req.url) == "https://api-processing.crypto-chief.com/v1/native/order"
    assert req.content.decode("utf-8") == '{"key":"' + KEY + '"}'
    assert_signed(req)

    assert order.id == 4201
    assert order.idempotency_key == KEY
    assert order.status == NativeOrderStatus.DELIVERED.value
    assert order.delivered_at == "2026-09-18T12:00:04Z"
    await client.aclose()


def test_unresolved_is_not_terminal():
    assert not is_native_order_terminal(NativeOrderStatus.UNRESOLVED.value)
    assert is_native_order_terminal("delivered")
    assert is_native_order_terminal("refused")
