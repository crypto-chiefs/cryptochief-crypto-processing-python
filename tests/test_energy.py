"""Energy service (TRON energy rental) through a mocked transport.

Validates the wire shapes of ``/v1/energy/quote`` (free), ``/v1/energy/rent``
(required signed ``Idempotency-Key`` header) and ``/v1/energy/order`` (lookup
by idempotency key), and the response mappings - including the recovery of an
order reported on a non-2xx answer (502/402 ``refused``, 409 ``unresolved``)
and the absent ``price_usd`` / ``credits`` / ``trx_usd`` on a ``refused``
order, where nothing was charged.
"""

import json

import httpx
import pytest

from cryptochief import (
    APIError,
    CryptoChiefClient,
    CryptoChiefError,
    EnergyOrderStatus,
    EnergyQuoteRequest,
    EnergyRentRequest,
    idempotency_key,
    is_energy_order_terminal,
)
from signed_request import assert_signed

TRON = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
KEY = "energy-2026-09-18-0001"

QUOTE_BODY = {
    "ref": "eq_01J8ZK3W2M",
    "receive_address": TRON,
    "energy": 65000,
    "duration_sec": 3600,
    "price_sun": 2_730_000,
    "price_trx": "2.730000",
    "price_usd": "0.78",
    "credits": 7_800_000,
    "trx_usd": "0.28571429",
    "recipient_state": "active",
    "burn_price_sun": 13_585_900,
    "burn_price_trx": "13.585900",
    "burn_price_usd": "3.88",
    "burn_price_credits": 38_800_000,
    "saving_trx": "10.855900",
    "saving_usd": "3.10",
    "saving_credits": 31_000_000,
    "expires_at": "2026-09-18T12:05:00Z",
    "expires_in_sec": 300,
}

# With no TRX/USD rate the rate-dependent fields are omitted, not guessed.
QUOTE_NO_RATE_BODY = {
    "ref": "eq_01J8ZK3W2M",
    "receive_address": TRON,
    "energy": 65000,
    "duration_sec": 3600,
    "price_sun": 2_730_000,
    "price_trx": "2.730000",
    "recipient_state": "active",
    "burn_price_sun": 13_585_900,
    "burn_price_trx": "13.585900",
    "saving_trx": "10.855900",
    "expires_at": "2026-09-18T12:05:00Z",
    "expires_in_sec": 300,
}

DELIVERED_ORDER_BODY = {
    "id": 4471,
    "idempotency_key": KEY,
    "status": "delivered",
    "receive_address": TRON,
    "energy": 65000,
    "duration_sec": 3600,
    "price_sun": 2_730_000,
    "price_trx": "2.730000",
    "price_usd": "0.78",
    "credits": 7_800_000,
    "trx_usd": "0.28571429",
    "delivered_energy": 65000,
    "settled": True,
    "needs_attention": False,
    "created_at": "2026-09-18T12:00:01Z",
    "delivered_at": "2026-09-18T12:00:02Z",
}

# A refused order (502) was never charged: price_usd / credits / trx_usd are
# absent from the wire, and the failure carries a machine code plus a
# sanitised sentence.
REFUSED_ORDER_BODY = {
    "id": 4472,
    "idempotency_key": KEY,
    "status": "refused",
    "receive_address": TRON,
    "energy": 65000,
    "duration_sec": 3600,
    "price_sun": 2_730_000,
    "price_trx": "2.730000",
    "settled": True,
    "needs_attention": False,
    "error_code": "SUPPLIER_REFUSED",
    "error": "no supplier could take this order; nothing was bought and nothing was charged",
    "created_at": "2026-09-18T12:10:00Z",
}

# An unresolved order (409): the supplier's answer never arrived, so the
# energy may already be delegated - charged, not settled, needs attention.
UNRESOLVED_ORDER_BODY = {
    "id": 4473,
    "idempotency_key": KEY,
    "status": "unresolved",
    "receive_address": TRON,
    "energy": 65000,
    "duration_sec": 3600,
    "price_sun": 2_730_000,
    "price_trx": "2.730000",
    "price_usd": "0.78",
    "credits": 7_800_000,
    "trx_usd": "0.28571429",
    "settled": False,
    "needs_attention": True,
    "error_code": "SUPPLIER_UNKNOWN",
    "error": "the order's outcome never came back and it will not be retried - it may already have been bought; ask us to check it",
    "created_at": "2026-09-18T12:11:00Z",
}

# A 402 refusal: the credits balance did not cover the order.
INSUFFICIENT_CREDITS_ORDER_BODY = {
    **REFUSED_ORDER_BODY,
    "id": 4474,
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
    quote = await client.energy.quote(
        EnergyQuoteRequest(receive_address=TRON, energy=65000, duration_sec=3600)
    )

    req = captured["request"]
    assert str(req.url) == "https://api-processing.crypto-chief.com/v1/energy/quote"
    assert req.method == "POST"
    assert json.loads(req.content) == {
        "receive_address": TRON,
        "energy": 65000,
        "duration_sec": 3600,
    }
    assert_signed(req)

    assert quote.ref == "eq_01J8ZK3W2M"
    assert quote.receive_address == TRON
    assert quote.energy == 65000
    assert quote.duration_sec == 3600
    assert quote.price_sun == 2_730_000
    assert quote.price_trx == "2.730000"
    assert quote.price_usd == "0.78"
    assert quote.credits == 7_800_000
    assert quote.trx_usd == "0.28571429"
    assert quote.recipient_state == "active"
    assert quote.burn_price_sun == 13_585_900
    assert quote.burn_price_trx == "13.585900"
    assert quote.burn_price_usd == "3.88"
    assert quote.burn_price_credits == 38_800_000
    assert quote.saving_trx == "10.855900"
    assert quote.saving_usd == "3.10"
    assert quote.saving_credits == 31_000_000
    assert quote.expires_at == "2026-09-18T12:05:00Z"
    assert quote.expires_in_sec == 300
    await client.aclose()


async def test_quote_without_a_rate_leaves_the_rate_fields_none():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=QUOTE_NO_RATE_BODY)

    client = _client(handler)
    quote = await client.energy.quote(EnergyQuoteRequest(receive_address=TRON))
    await client.aclose()

    assert quote.price_sun == 2_730_000
    # no rate on the server: the conversions are omitted, decoded as None -
    # never as a guessed zero
    assert quote.price_usd is None
    assert quote.credits is None
    assert quote.trx_usd is None
    assert quote.burn_price_usd is None
    assert quote.burn_price_credits is None
    assert quote.saving_usd is None
    assert quote.saving_credits is None


async def test_quote_omits_unset_optionals():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json=QUOTE_BODY)

    client = _client(handler)
    await client.energy.quote(EnergyQuoteRequest(receive_address=TRON))

    body = captured["request"].content.decode("utf-8")
    assert body == '{"receive_address":"' + TRON + '"}'
    assert_signed(captured["request"])
    await client.aclose()


async def test_rent_sends_signed_idempotency_key_and_maps_order():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json=DELIVERED_ORDER_BODY)

    client = _client(handler)
    order = await client.energy.rent(
        EnergyRentRequest(quote_ref="eq_01J8ZK3W2M"),
        idempotency_key=KEY,
    )

    req = captured["request"]
    assert str(req.url) == "https://api-processing.crypto-chief.com/v1/energy/rent"
    assert req.headers["Idempotency-Key"] == KEY
    # quote_ref alone: the quote carries the address and the amount
    assert json.loads(req.content) == {"quote_ref": "eq_01J8ZK3W2M"}
    assert_signed(req, idempotency_key=KEY)  # the key is covered by the signature

    assert order.id == 4471
    assert order.idempotency_key == KEY
    assert order.status == "delivered"
    assert is_energy_order_terminal(order.status)
    assert order.receive_address == TRON
    assert order.energy == 65000
    assert order.duration_sec == 3600
    assert order.price_sun == 2_730_000
    assert order.price_trx == "2.730000"
    assert order.price_usd == "0.78"
    assert order.credits == 7_800_000
    assert order.trx_usd == "0.28571429"
    assert order.delivered_energy == 65000
    assert order.settled is True
    assert order.needs_attention is False
    assert order.error_code is None
    assert order.error is None
    assert order.created_at == "2026-09-18T12:00:01Z"
    assert order.delivered_at == "2026-09-18T12:00:02Z"
    await client.aclose()


async def test_rent_takes_the_key_from_the_context_manager():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json=DELIVERED_ORDER_BODY)

    client = _client(handler)
    with idempotency_key(KEY):
        await client.energy.rent(EnergyRentRequest(receive_address=TRON, energy=65000))

    req = captured["request"]
    assert req.headers["Idempotency-Key"] == KEY
    assert json.loads(req.content) == {"receive_address": TRON, "energy": 65000}
    assert_signed(req, idempotency_key=KEY)
    await client.aclose()


async def test_rent_without_key_raises_before_sending():
    sent: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json=DELIVERED_ORDER_BODY)

    client = _client(handler)
    with pytest.raises(CryptoChiefError, match="idempotency_key is required"):
        await client.energy.rent(EnergyRentRequest(receive_address=TRON))
    await client.aclose()
    assert sent == []


async def test_rent_refused_order_comes_back_on_a_502():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, json=REFUSED_ORDER_BODY)

    # 502 retries are pointless here - the order is settled. retries=0.
    client = _client(handler, retries=0)
    order = await client.energy.rent(EnergyRentRequest(receive_address=TRON), idempotency_key=KEY)
    await client.aclose()

    assert order.id == 4472
    assert order.status == EnergyOrderStatus.REFUSED == "refused"
    assert is_energy_order_terminal(order.status)
    assert order.settled is True
    assert order.needs_attention is False
    assert order.error_code == "SUPPLIER_REFUSED"
    assert order.error == (
        "no supplier could take this order; nothing was bought and nothing was charged"
    )
    # nothing was charged: the charge fields are absent on the wire, None here
    assert order.price_usd is None
    assert order.credits is None
    assert order.trx_usd is None
    assert order.delivered_energy == 0
    assert order.delivered_at is None


async def test_rent_refused_for_insufficient_credits_comes_back_on_a_402():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(402, json=INSUFFICIENT_CREDITS_ORDER_BODY)

    client = _client(handler)
    order = await client.energy.rent(EnergyRentRequest(receive_address=TRON), idempotency_key=KEY)
    await client.aclose()

    assert order.status == "refused"
    assert order.error_code == "INSUFFICIENT_CREDITS"
    assert order.credits is None


async def test_rent_unresolved_order_comes_back_on_a_409():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json=UNRESOLVED_ORDER_BODY)

    client = _client(handler)
    order = await client.energy.rent(EnergyRentRequest(receive_address=TRON), idempotency_key=KEY)
    await client.aclose()

    # 409 + needs_attention: do NOT retry; follow the order with order()
    assert order.status == EnergyOrderStatus.UNRESOLVED == "unresolved"
    assert not is_energy_order_terminal(order.status)
    assert order.settled is False
    assert order.needs_attention is True
    assert order.error_code == "SUPPLIER_UNKNOWN"
    # charged, because the energy may already be delegated
    assert order.credits == 7_800_000


async def test_rent_envelope_error_raises_as_before():
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
        await client.energy.rent(EnergyRentRequest(quote_ref="eq_01J8ZK3W2M"), idempotency_key=KEY)
    await client.aclose()

    assert ei.value.code == "QUOTE_EXPIRED"
    assert ei.value.http_status == 409
    assert ei.value.message == "that quote has expired; ask for a new price"


async def test_order_posts_idempotency_key_and_maps_order():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json=DELIVERED_ORDER_BODY)

    client = _client(handler)
    order = await client.energy.order(KEY)

    req = captured["request"]
    assert str(req.url) == "https://api-processing.crypto-chief.com/v1/energy/order"
    assert req.content.decode("utf-8") == '{"key":"' + KEY + '"}'
    assert_signed(req)

    assert order.id == 4471
    assert order.idempotency_key == KEY
    assert order.status == EnergyOrderStatus.DELIVERED.value
    assert order.delivered_at == "2026-09-18T12:00:02Z"
    await client.aclose()


def test_unresolved_is_not_terminal():
    assert not is_energy_order_terminal(EnergyOrderStatus.UNRESOLVED.value)
    assert is_energy_order_terminal("delivered")
    assert is_energy_order_terminal("refused")
    assert is_energy_order_terminal(EnergyOrderStatus.REFUNDED.value)
