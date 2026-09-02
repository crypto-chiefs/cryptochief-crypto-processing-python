"""Wallet naming, master re-pointing, the deposit-callback endpoint and pay-in history.

Covers the wire shapes of ``/v1/wallets/generate`` (the optional ``label``),
``/v1/wallets/rebind-master``, ``/v1/wallets/callback-url`` and
``/v1/wallets/label`` - in particular that an empty ``callback_url`` or
``label`` is *sent* rather than dropped, because that is how the API says "stop
announcing deposits for this address" and "this wallet has no name", and that a
``null`` ``master_wallet_address`` / ``callback_url`` / ``label`` decodes to
``None`` instead of throwing.

Also ``/v1/wallets/history``, which answers with the same order records as
``/v1/payments/history`` - the same :class:`PayIn` rows and the same ``meta``
block - so the SDK decodes it into the same types rather than a second one.
"""

import json

import httpx
import pytest

from cryptochief import (
    ChainFamily,
    CryptoChiefClient,
    CryptoChiefError,
    GenerateWalletRequest,
    PayIn,
    PayInHistoryResponse,
    WalletType,
    canonical_json,
    sign,
)

PAYIN_HISTORY_RESPONSE = {
    "items": [
        {
            "uuid": "0a1b2c3d-4e5f-6789-abcd-ef0123456789",
            "order_id": "invoice-1002",
            "status": "paid",
            "amount_crypto": "10.5",
            "payment_coin": "USDT",
            "payment_network": "TRON_MAINNET",
            "to_address": "TQrY8bYc2yQ8sM8nJ1sZ9c2Zx7L2wq7pQb",
        }
    ],
    "meta": {"page": 1, "page_size": 20, "total": 1},
}

STATIC_WALLET = {
    "type": "static",
    "address": "0x4Afb4cE0215C53784861D7ABd44F741e17DB306b",
    "chain_family": "EVM",
    "frozen": False,
    "master_wallet_address": "0xcCb1c30b39d461364FC503da0CaA751212183DE2",
    "callback_url": "https://your-shop.example/webhooks/deposits",
    "label": "EU shop - order 4471",
}


def _client(captured: dict, payload: dict) -> CryptoChiefClient:
    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json=payload)

    return CryptoChiefClient(
        merchant_id="M1", api_key="secret", transport=httpx.MockTransport(handler)
    )


def _body(captured: dict) -> dict:
    return json.loads(captured["request"].content.decode())


async def test_generate_sends_the_label_and_omits_it_when_unset():
    captured: dict = {}
    client = _client(captured, {"address": "0xabc", "chain_family": "EVM", "wallet_type": "static"})

    await client.wallets.generate(
        GenerateWalletRequest(
            wallet_type=WalletType.STATIC,
            chain_family=ChainFamily.EVM,
            master_wallet_address="0xmaster",
            callback_url="https://your-shop.example/webhooks/deposits",
            label="EU shop - order 4471",
        )
    )

    req = captured["request"]
    assert str(req.url).endswith("/v1/wallets/generate")
    expected = canonical_json(
        {
            "wallet_type": "static",
            "chain_family": "EVM",
            "master_wallet_address": "0xmaster",
            "callback_url": "https://your-shop.example/webhooks/deposits",
            "label": "EU shop - order 4471",
        }
    )
    assert req.content.decode("utf-8") == expected
    assert req.headers["Signature"] == sign(expected, "secret")

    captured2: dict = {}
    client2 = _client(captured2, {"address": "0xdef", "chain_family": "EVM"})
    await client2.wallets.generate(
        GenerateWalletRequest(wallet_type=WalletType.MASTER, chain_family=ChainFamily.EVM)
    )
    # The endpoint refuses unknown fields and reads an empty string as a name,
    # so an unset label has to stay off the wire entirely.
    body2 = captured2["request"].content.decode("utf-8")
    assert body2 == canonical_json({"wallet_type": "master", "chain_family": "EVM"})
    assert "label" not in body2

    await client.aclose()
    await client2.aclose()


async def test_generate_labels_a_master_wallet_too():
    captured: dict = {}
    client = _client(captured, {"address": "0xabc", "chain_family": "TRON"})

    await client.wallets.generate(
        GenerateWalletRequest(
            wallet_type=WalletType.MASTER, chain_family=ChainFamily.TRON, label="treasury"
        )
    )

    # The label names the wallet, it is not a property of the static role.
    assert _body(captured) == {
        "wallet_type": "master",
        "chain_family": "TRON",
        "label": "treasury",
    }
    await client.aclose()


async def test_rebind_master_posts_the_documented_body_and_returns_the_wallet():
    captured: dict = {}
    client = _client(captured, STATIC_WALLET)

    out = await client.wallets.rebind_master("0x4Afb", "0xcCb1")

    req = captured["request"]
    assert str(req.url) == "https://api-processing.crypto-chief.com/v1/wallets/rebind-master"
    assert req.method == "POST"
    assert req.headers["Merchant"] == "M1"
    # master_wallet_address, not master_address: the spelling the rest of the
    # surface uses, and the one this endpoint answers with.
    expected = canonical_json({"address": "0x4Afb", "master_wallet_address": "0xcCb1"})
    assert req.content.decode("utf-8") == expected
    assert req.headers["Signature"] == sign(expected, "secret")

    assert out.type == "static"
    assert out.address == STATIC_WALLET["address"]
    assert out.chain_family == "EVM"
    assert out.frozen is False
    assert out.master_wallet_address == STATIC_WALLET["master_wallet_address"]
    assert out.callback_url == STATIC_WALLET["callback_url"]
    # Every response that describes a wallet reports its name, this one included.
    assert out.label == "EU shop - order 4471"
    await client.aclose()


async def test_set_callback_url_posts_the_documented_body():
    captured: dict = {}
    client = _client(captured, STATIC_WALLET)

    out = await client.wallets.set_callback_url(
        "0x4Afb", "https://your-shop.example/webhooks/deposits"
    )

    req = captured["request"]
    assert str(req.url) == "https://api-processing.crypto-chief.com/v1/wallets/callback-url"
    expected = canonical_json(
        {"address": "0x4Afb", "callback_url": "https://your-shop.example/webhooks/deposits"}
    )
    assert req.content.decode("utf-8") == expected
    assert req.headers["Signature"] == sign(expected, "secret")
    assert out.callback_url == "https://your-shop.example/webhooks/deposits"
    await client.aclose()


async def test_an_empty_callback_url_is_sent_rather_than_omitted():
    captured: dict = {}
    client = _client(captured, {**STATIC_WALLET, "callback_url": None})

    out = await client.wallets.set_callback_url("0x4Afb", "")

    body = captured["request"].content.decode("utf-8")
    # "" is the instruction "stop announcing deposits for this address", not an
    # unset field. Dropping it the way unset optionals are dropped would leave
    # the callback in place and answer INVALID_PARAMS.
    assert body == '{"address":"0x4Afb","callback_url":""}'
    assert _body(captured)["callback_url"] == ""
    assert captured["request"].headers["Signature"] == sign(body, "secret")
    # Cleared reads back as null, never as an empty string.
    assert out.callback_url is None
    await client.aclose()


async def test_set_callback_url_refuses_none_instead_of_dropping_the_field():
    captured: dict = {}
    client = _client(captured, STATIC_WALLET)

    with pytest.raises(CryptoChiefError):
        await client.wallets.set_callback_url("0x4Afb", None)  # type: ignore[arg-type]

    # Nothing was sent: None would have been serialized away, and a body without
    # callback_url is a different request than the caller wrote.
    assert "request" not in captured
    await client.aclose()


async def test_null_master_callback_and_label_decode_as_none():
    captured: dict = {}
    client = _client(
        captured,
        {
            "type": "transit",
            "address": "0x8a2F",
            "chain_family": "EVM",
            "frozen": False,
            "master_wallet_address": None,
            "callback_url": None,
            "label": None,
        },
    )

    out = await client.wallets.rebind_master("0x8a2F", "0xcCb1")

    # All three keys are always present and null when the wallet has no such
    # value - a transit wallet never has a per-deposit callback, and an unnamed
    # wallet reports null rather than "". The null must decode, not throw.
    assert out.type == "transit"
    assert out.frozen is False
    assert out.master_wallet_address is None
    assert out.callback_url is None
    assert out.label is None
    await client.aclose()


async def test_set_label_posts_the_documented_body():
    captured: dict = {}
    client = _client(captured, STATIC_WALLET)

    out = await client.wallets.set_label("0x4Afb", "EU shop - order 4471")

    req = captured["request"]
    assert str(req.url) == "https://api-processing.crypto-chief.com/v1/wallets/label"
    assert req.method == "POST"
    assert req.headers["Merchant"] == "M1"
    expected = canonical_json({"address": "0x4Afb", "label": "EU shop - order 4471"})
    assert req.content.decode("utf-8") == expected
    assert _body(captured).keys() == {"address", "label"}
    assert req.headers["Signature"] == sign(expected, "secret")
    assert out.label == "EU shop - order 4471"
    await client.aclose()


async def test_an_empty_label_is_sent_rather_than_omitted():
    captured: dict = {}
    client = _client(captured, {**STATIC_WALLET, "label": None})

    out = await client.wallets.set_label("0x4Afb", "")

    body = captured["request"].content.decode("utf-8")
    # "" is the instruction "this wallet has no name", not an unset field.
    # Dropping it the way unset optionals are dropped would leave the old name
    # in place and answer INVALID_PARAMS.
    assert body == '{"address":"0x4Afb","label":""}'
    assert _body(captured)["label"] == ""
    assert captured["request"].headers["Signature"] == sign(body, "secret")
    # Cleared reads back as null, never as an empty string.
    assert out.label is None
    await client.aclose()


async def test_set_label_refuses_none_instead_of_dropping_the_field():
    captured: dict = {}
    client = _client(captured, STATIC_WALLET)

    with pytest.raises(CryptoChiefError):
        await client.wallets.set_label("0x4Afb", None)  # type: ignore[arg-type]

    # Nothing was sent: None would have been serialized away, and a body without
    # label is a different request than the caller wrote.
    assert "request" not in captured
    await client.aclose()


async def test_set_label_renames_a_master_wallet_too():
    captured: dict = {}
    client = _client(
        captured,
        {
            "type": "master",
            "address": "0xcCb1",
            "chain_family": "EVM",
            "frozen": False,
            "master_wallet_address": None,
            "callback_url": None,
            "label": "treasury (EVM)",
        },
    )

    out = await client.wallets.set_label("0xcCb1", "treasury (EVM)")

    # A label names the wallet, so unlike the deposit callback it is not
    # static-only: nothing here narrows the endpoint to one wallet type.
    assert _body(captured) == {"address": "0xcCb1", "label": "treasury (EVM)"}
    assert out.type == "master"
    assert out.label == "treasury (EVM)"
    assert out.master_wallet_address is None
    await client.aclose()


async def test_generated_wallets_and_the_list_report_the_label():
    captured: dict = {}
    client = _client(
        captured,
        {
            "address": "0x4Afb",
            "chain_family": "EVM",
            "wallet_type": "static",
            "label": "EU shop - order 4471",
        },
    )
    generated = await client.wallets.generate(
        GenerateWalletRequest(
            wallet_type=WalletType.STATIC,
            chain_family=ChainFamily.EVM,
            label="EU shop - order 4471",
        )
    )
    assert generated.label == "EU shop - order 4471"
    await client.aclose()

    captured2: dict = {}
    client2 = _client(
        captured2,
        {"items": [STATIC_WALLET, {**STATIC_WALLET, "address": "0x8a2F", "label": None}]},
    )
    listed = await client2.wallets.list()

    # The list is where a name earns its keep, and an unnamed wallet in it is a
    # null rather than a missing key or an empty string.
    assert [w.label for w in listed.items or []] == ["EU shop - order 4471", None]
    await client2.aclose()


async def test_set_callback_url_response_still_carries_the_label():
    captured: dict = {}
    client = _client(captured, STATIC_WALLET)

    out = await client.wallets.set_callback_url("0x4Afb", "https://your-shop.example/hook")

    # The neighbouring updates answer with the same wallet shape, name included:
    # changing the webhook does not blank the name out of the response.
    assert out.label == "EU shop - order 4471"
    await client.aclose()


async def test_pay_in_history_decodes_into_the_payin_history_types():
    captured: dict = {}
    client = _client(captured, PAYIN_HISTORY_RESPONSE)

    out = await client.wallets.pay_in_history("TQrY8bYc2yQ8sM8nJ1sZ9c2Zx7L2wq7pQb")

    assert str(captured["request"].url).endswith("/v1/wallets/history")
    assert isinstance(out, PayInHistoryResponse)
    assert out.items is not None
    order = out.items[0]
    assert isinstance(order, PayIn)
    assert order.order_id == "invoice-1002"
    assert order.status == "paid"
    assert order.payment_network == "TRON_MAINNET"
    assert out.meta is not None
    assert (out.meta.page, out.meta.page_size, out.meta.total) == (1, 20, 1)
    await client.aclose()


async def test_pay_in_history_sends_the_address_and_omits_unset_filters():
    captured: dict = {}
    client = _client(captured, PAYIN_HISTORY_RESPONSE)

    await client.wallets.pay_in_history("0xAbCdEf")

    # The address is the only required field; the dates and paging are the
    # server's defaults until the caller says otherwise, so they stay off the
    # wire rather than going out as empty strings.
    assert _body(captured) == {"address": "0xAbCdEf"}
    await client.aclose()


async def test_pay_in_history_passes_the_date_window_and_paging_through():
    captured: dict = {}
    client = _client(captured, PAYIN_HISTORY_RESPONSE)

    await client.wallets.pay_in_history(
        "0xAbCdEf",
        date_from="2026-01-01T00:00:00+00:00",
        date_to="2026-02-01T00:00:00+00:00",
        page=2,
        page_size=100,
    )

    assert _body(captured) == {
        "address": "0xAbCdEf",
        "date_from": "2026-01-01T00:00:00+00:00",
        "date_to": "2026-02-01T00:00:00+00:00",
        "page": 2,
        "page_size": 100,
    }
    await client.aclose()


async def test_pay_in_history_of_a_foreign_address_is_an_empty_page():
    captured: dict = {}
    # Not an error: an address the project does not own simply has no orders of
    # yours on it, which is a 200 with nothing in it.
    client = _client(captured, {"items": [], "meta": {"page": 1, "page_size": 20, "total": 0}})

    out = await client.wallets.pay_in_history("0xSomeoneElses")

    assert out.items == []
    assert out.meta is not None
    assert out.meta.total == 0
    await client.aclose()
