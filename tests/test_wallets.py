"""Wallet naming, master re-pointing and the deposit-callback endpoint.

Covers the wire shapes of ``/v1/wallets/generate`` (the optional ``label``),
``/v1/wallets/rebind-master`` and ``/v1/wallets/callback-url`` - in particular
that an empty ``callback_url`` is *sent* rather than dropped, because it is how
the API says "stop announcing deposits for this address", and that a ``null``
``master_wallet_address`` / ``callback_url`` decodes to ``None`` instead of
throwing.
"""

import json

import httpx
import pytest

from cryptochief import (
    ChainFamily,
    CryptoChiefClient,
    CryptoChiefError,
    GenerateWalletRequest,
    WalletType,
    canonical_json,
    sign,
)

STATIC_WALLET = {
    "type": "static",
    "address": "0x4Afb4cE0215C53784861D7ABd44F741e17DB306b",
    "chain_family": "EVM",
    "frozen": False,
    "master_wallet_address": "0xcCb1c30b39d461364FC503da0CaA751212183DE2",
    "callback_url": "https://your-shop.example/webhooks/deposits",
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


async def test_null_master_and_callback_decode_as_none():
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
        },
    )

    out = await client.wallets.rebind_master("0x8a2F", "0xcCb1")

    # Both keys are always present and null when the wallet has no such value -
    # a transit wallet never has a per-deposit callback. The null must decode,
    # not throw.
    assert out.type == "transit"
    assert out.frozen is False
    assert out.master_wallet_address is None
    assert out.callback_url is None
    await client.aclose()
