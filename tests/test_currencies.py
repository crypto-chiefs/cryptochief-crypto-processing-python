"""The two currency catalogues, and the wire shapes they answer with.

``/v1/currencies/fiats`` answers with a **bare top-level array** - no ``items``
envelope - which is how ``/v1/blockchains/list`` behaves and how nothing else
does. A model built around an envelope type-checks fine and finds nothing at
runtime.

``/v1/currencies/cryptos`` answers with an object whose ``by_exchange`` is a map
from exchange name to that exchange's tickers, so more than one exchange has to
survive decoding.

Both take an **empty object** as the request body rather than no body at all:
the body is what gets signed, so the empty ``{}`` has to reach the wire.
"""

import json

import httpx

from cryptochief import CryptoChiefClient, CryptoCurrencies, FiatCurrency

FIATS_RESPONSE = [
    {"code": "JMD", "name": "Jamaican Dollar"},
    {"code": "KYD", "name": "Cayman Islands Dollar"},
    {"code": "SEK", "name": "Swedish Krona"},
]

CRYPTOS_RESPONSE = {
    "by_exchange": {
        "binance": ["0G", "1000CAT", "BTC", "USDT"],
        "bybit": ["0G", "1INCH", "AAVE"],
        "exmo": ["AAVE", "ADA", "BCH"],
        "kucoin": ["0G", "A2Z", "AAVE"],
    },
    "count": 2529,
    "quote": "USDT",
    "tickers": ["0G", "1000CAT", "1INCH", "A2Z", "AAVE", "ADA", "BCH", "BTC", "USDT"],
}


def _client(captured: dict, payload) -> CryptoChiefClient:
    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json=payload)

    return CryptoChiefClient(
        merchant_id="M1", api_key="secret", transport=httpx.MockTransport(handler)
    )


def _raw_client(captured: dict, raw: bytes) -> CryptoChiefClient:
    """A client answering with ``raw`` bytes verbatim.

    ``httpx.Response(json=None)`` sends an *empty* body, not the four bytes
    ``null``, so the null-body cases have to hand over the bytes themselves.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, content=raw, headers={"Content-Type": "application/json"})

    return CryptoChiefClient(
        merchant_id="M1", api_key="secret", transport=httpx.MockTransport(handler)
    )


def _body(captured: dict) -> dict:
    return json.loads(captured["request"].content.decode())


async def test_fiats_decodes_a_bare_top_level_array():
    captured: dict = {}
    # Not {"items": [...]} - the server sends the array itself.
    client = _client(captured, FIATS_RESPONSE)

    fiats = await client.currencies.fiats()

    assert str(captured["request"].url).endswith("/v1/currencies/fiats")
    assert isinstance(fiats, list)
    assert all(isinstance(f, FiatCurrency) for f in fiats)
    assert [f.code for f in fiats] == ["JMD", "KYD", "SEK"]
    assert fiats[2].name == "Swedish Krona"
    await client.aclose()


async def test_fiats_sends_an_empty_object_because_the_body_is_signed():
    captured: dict = {}
    client = _client(captured, FIATS_RESPONSE)

    await client.currencies.fiats()

    # An empty body is still a body: it is what the Signature header is computed
    # over, so `{}` has to go out rather than nothing at all.
    assert _body(captured) == {}
    assert captured["request"].headers["Signature"]
    await client.aclose()


async def test_fiats_of_an_empty_platform_answer_is_an_empty_list():
    captured: dict = {}
    client = _client(captured, [])

    assert await client.currencies.fiats() == []
    await client.aclose()


async def test_fiats_on_a_literal_null_body():
    captured: dict = {}
    # The service builds its answer from a nil slice, so an empty catalogue
    # marshals as JSON `null` rather than `[]`. A method promising a list has to
    # hand back an empty one: not None, not an exception, not a decode error.
    client = _raw_client(captured, b"null")

    fiats = await client.currencies.fiats()

    assert fiats == []
    assert isinstance(fiats, list)
    # Safe to iterate without a None guard, which is the whole point.
    assert [f.code for f in fiats] == []
    await client.aclose()


async def test_cryptos_decodes_the_by_exchange_map_across_several_exchanges():
    captured: dict = {}
    client = _client(captured, CRYPTOS_RESPONSE)

    rates = await client.currencies.cryptos()

    assert str(captured["request"].url).endswith("/v1/currencies/cryptos")
    assert isinstance(rates, CryptoCurrencies)
    assert rates.by_exchange is not None
    # Every exchange survives, keyed by its own name, with its own ticker list -
    # not flattened into one and not just the first key.
    assert sorted(rates.by_exchange) == ["binance", "bybit", "exmo", "kucoin"]
    assert rates.by_exchange["binance"] == ["0G", "1000CAT", "BTC", "USDT"]
    assert rates.by_exchange["exmo"] == ["AAVE", "ADA", "BCH"]
    assert "AAVE" in rates.by_exchange["kucoin"]
    await client.aclose()


async def test_cryptos_reports_the_union_the_count_and_the_quote_asset():
    captured: dict = {}
    client = _client(captured, CRYPTOS_RESPONSE)

    rates = await client.currencies.cryptos()

    assert rates.quote == "USDT"
    assert rates.count == 2529
    assert rates.tickers is not None
    assert "BTC" in rates.tickers
    await client.aclose()


async def test_cryptos_sends_an_empty_object_because_the_body_is_signed():
    captured: dict = {}
    client = _client(captured, CRYPTOS_RESPONSE)

    await client.currencies.cryptos()

    assert _body(captured) == {}
    assert captured["request"].headers["Signature"]
    await client.aclose()


async def test_cryptos_tolerates_a_response_without_the_optional_lists():
    captured: dict = {}
    # A missing key is not an error: the fields the server did not send read as
    # None, and `rates.by_exchange or {}` is the idiom for walking them.
    client = _client(captured, {"quote": "USDT", "count": 0})

    rates = await client.currencies.cryptos()

    assert rates.tickers is None
    assert rates.by_exchange is None
    assert list(rates.by_exchange or {}) == []
    await client.aclose()


async def test_cryptos_on_a_literal_null_body():
    captured: dict = {}
    # `null` where an object was promised: an all-defaults CryptoCurrencies, not
    # a decode error and not None. The optional lists stay None - the declared
    # shape says they may be absent, and `rates.tickers or []` is the idiom -
    # but every field is readable.
    client = _raw_client(captured, b"null")

    rates = await client.currencies.cryptos()

    assert isinstance(rates, CryptoCurrencies)
    assert rates.tickers is None
    assert rates.by_exchange is None
    assert rates.count == 0
    assert rates.quote == ""
    assert list(rates.tickers or []) == []
    await client.aclose()


async def test_cryptos_reads_a_null_ticker_list_inside_by_exchange_as_empty():
    captured: dict = {}
    # A null nested one level down. `by_exchange` is declared
    # Dict[str, List[str]], so a None arriving as one of its values would be a
    # None sitting in a slot typed as a list - it type-checks and then blows up
    # in the caller's `for ticker in tickers` loop. An exchange carrying nothing
    # decodes as an empty list instead.
    client = _raw_client(
        captured,
        b'{"tickers": ["BTC"], "by_exchange": {"binance": ["BTC"], "exmo": null},'
        b' "count": 1, "quote": "USDT"}',
    )

    rates = await client.currencies.cryptos()

    assert rates.by_exchange is not None
    assert rates.by_exchange["exmo"] == []
    assert rates.by_exchange["binance"] == ["BTC"]
    # Every value of the map is iterable, with no per-key None guard.
    assert sorted(t for tickers in rates.by_exchange.values() for t in tickers) == ["BTC"]
    await client.aclose()
