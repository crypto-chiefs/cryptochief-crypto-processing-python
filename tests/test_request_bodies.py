"""Request bodies of methods with optional fields: unset and ``None`` fields are not sent.

Expected bodies are the JSON values 0.9.0 sent for the same calls.
"""

import json
import math

import httpx
import pytest

from cryptochief import (
    CLEAR,
    Asset,
    AssetsPolicy,
    BatchPayoutRequest,
    ContractCall,
    ConvertRequest,
    CreatePayInRequest,
    CryptoChiefClient,
    CryptoChiefError,
    EnergyQuoteRequest,
    EstimatePayoutRequest,
    EstimateTransactionRequest,
    EvmCallRequest,
    ExecutePayoutRequest,
    ExecuteTransactionRequest,
    GenerateWalletRequest,
    HistoryQuery,
    NativeQuoteRequest,
    SelectAssetRequest,
    SignTransactionRequest,
    StaticDepositHistoryQuery,
    SweepHistoryQuery,
    TonCallRequest,
)
from signed_request import assert_signed

EVM = "0x4Afb000000000000000000000000000000000001"
EVM2 = "0xcCb1000000000000000000000000000000000002"
TON = "EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs"
TRON = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"


def execute_payout(**opt):
    return ExecutePayoutRequest(
        network="ETH_SEPOLIA", coin="ETH", amount="0.0001", to_address=EVM,
        order_id="o-1", user_id="usr-1", url_callback="https://shop.example/cb", **opt,
    )


PAYOUT_NONE = dict(
    from_addresses=None, allow_multiple_sources=None, auto_convert=None,
    auto_convert_policy=None, max_fee_amount_fiat=None, memo=None,
)

CASES = [
    (
        "payouts.estimate none",
        lambda c: c.payouts.estimate(EstimatePayoutRequest(
            network="ETH_SEPOLIA", coin="ETH", amount="0.0001", to_address=EVM, **PAYOUT_NONE)),
        "/v1/payout/estimate",
        '{"amount":"0.0001","coin":"ETH","network":"ETH_SEPOLIA",'
        '"to_address":"0x4Afb000000000000000000000000000000000001"}',
    ),
    (
        "payouts.estimate nested none",
        lambda c: c.payouts.estimate(EstimatePayoutRequest(
            network="ETH_SEPOLIA", coin="ETH", amount="0.0001", to_address=EVM, from_addresses=[],
            auto_convert_policy=AssetsPolicy(allow=[Asset(network=None, coin=None)], exclude=None),
            memo="")),
        "/v1/payout/estimate",
        '{"amount":"0.0001","auto_convert_policy":{"allow":[{}]},"coin":"ETH","from_addresses":[],'
        '"memo":"","network":"ETH_SEPOLIA","to_address":"0x4Afb000000000000000000000000000000000001"}',
    ),
    (
        "payouts.execute none",
        lambda c: c.payouts.execute(execute_payout(**PAYOUT_NONE)),
        "/v1/payout/execute",
        '{"amount":"0.0001","coin":"ETH","network":"ETH_SEPOLIA","order_id":"o-1",'
        '"to_address":"0x4Afb000000000000000000000000000000000001",'
        '"url_callback":"https://shop.example/cb","user_id":"usr-1"}',
    ),
    (
        "payouts.batch_execute none",
        lambda c: c.payouts.batch_execute(
            BatchPayoutRequest(items=[execute_payout(**PAYOUT_NONE)], url_callback=None)),
        "/v1/payout/batch/execute",
        '{"items":[{"amount":"0.0001","coin":"ETH","network":"ETH_SEPOLIA","order_id":"o-1",'
        '"to_address":"0x4Afb000000000000000000000000000000000001",'
        '"url_callback":"https://shop.example/cb","user_id":"usr-1"}]}',
    ),
    (
        "payouts.history none",
        lambda c: c.payouts.history(HistoryQuery(
            page=None, page_size=None, status=None, coin=None, network=None,
            date_from=None, date_to=None)),
        "/v1/payout/history",
        "{}",
    ),
    (
        "transactions.sign none",
        lambda c: c.transactions.sign(SignTransactionRequest(
            network="ETH_SEPOLIA", from_address=EVM, type="native", to_address=None, value=None,
            contract=None, calls=None, url_callback=None)),
        "/v1/transaction/signature",
        '{"from_address":"0x4Afb000000000000000000000000000000000001","network":"ETH_SEPOLIA",'
        '"type":"native"}',
    ),
    (
        "transactions.sign call none",
        lambda c: c.transactions.sign(SignTransactionRequest(
            network="TON_TESTNET", from_address=TON, type="contract",
            calls=[ContractCall(to=TON, data="AA==", value=None, accounts=None, bounce=None)])),
        "/v1/transaction/signature",
        '{"calls":[{"data":"AA==","to":"EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs"}],'
        '"from_address":"EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs",'
        '"network":"TON_TESTNET","type":"contract"}',
    ),
    (
        "transactions.estimate none",
        lambda c: c.transactions.estimate(EstimateTransactionRequest(
            network="ETH_SEPOLIA", from_address=EVM, type="token", to_address=EVM2,
            value=None, contract=None)),
        "/v1/transaction/estimate",
        '{"from_address":"0x4Afb000000000000000000000000000000000001","network":"ETH_SEPOLIA",'
        '"to_address":"0xcCb1000000000000000000000000000000000002","type":"token"}',
    ),
    (
        "transactions.execute none",
        lambda c: c.transactions.execute(ExecuteTransactionRequest(uuid="u1", signed_tx_hex=None)),
        "/v1/transaction/execute",
        '{"uuid":"u1"}',
    ),
    (
        "transactions.sign_evm_call none",
        lambda c: c.transactions.sign_evm_call(EvmCallRequest(
            network="ETH_SEPOLIA", from_address=EVM, contract=EVM2, method="pause()",
            value=None, url_callback=None)),
        "/v1/transaction/signature",
        '{"calls":[{"data":"0x8456cb59","to":"0xcCb1000000000000000000000000000000000002",'
        '"value":"0"}],"from_address":"0x4Afb000000000000000000000000000000000001",'
        '"network":"ETH_SEPOLIA","type":"contract"}',
    ),
    (
        "transactions.sign_ton_call none",
        lambda c: c.transactions.sign_ton_call(TonCallRequest(
            network="TON_TESTNET", from_address=TON, contract=TON, body_cell=b"\x00",
            value=None, bounce=None, url_callback=None)),
        "/v1/transaction/signature",
        '{"calls":[{"data":"AA==","to":"EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs",'
        '"value":"0"}],"from_address":"EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs",'
        '"network":"TON_TESTNET","type":"contract"}',
    ),
    (
        "pay_ins.create none",
        lambda c: c.pay_ins.create(CreatePayInRequest(
            order_id="o-1", user_id="u-1", mode="fiat", to_address=None,
            master_wallet_address=None, environment=None, lifetime_sec=None, url_callback=None,
            url_success=None, url_error=None, additional_data=None,
            accuracy_payment_percent=None, amount_fiat=None, currency=None, course_source=None,
            assets=None, amount_crypto=None, asset=None)),
        "/v1/payments/order/create",
        '{"mode":"fiat","order_id":"o-1","user_id":"u-1"}',
    ),
    (
        "pay_ins.create nested none",
        lambda c: c.pay_ins.create(CreatePayInRequest(
            order_id="o-1", user_id="u-1", mode="crypto", lifetime_sec=0, additional_data="",
            assets=AssetsPolicy(allow=None, exclude=[Asset(network="ANY", coin=None)]),
            asset=Asset(network=None, coin="ETH"))),
        "/v1/payments/order/create",
        '{"additional_data":"","asset":{"coin":"ETH"},"assets":{"exclude":[{"network":"ANY"}]},'
        '"lifetime_sec":0,"mode":"crypto","order_id":"o-1","user_id":"u-1"}',
    ),
    (
        "pay_ins.select_asset none",
        lambda c: c.pay_ins.select_asset(SelectAssetRequest(
            uuid="u1", coin="USDT", network="TRON_MAINNET", master_wallet_address=None)),
        "/v1/payments/asset/select",
        '{"coin":"USDT","network":"TRON_MAINNET","uuid":"u1"}',
    ),
    (
        "wallets.generate none",
        lambda c: c.wallets.generate(GenerateWalletRequest(
            wallet_type="transit", chain_family="EVM", master_wallet_address=None,
            callback_url=None, label=None)),
        "/v1/wallets/generate",
        '{"chain_family":"EVM","wallet_type":"transit"}',
    ),
    (
        "wallets.generate empty strings",
        lambda c: c.wallets.generate(GenerateWalletRequest(
            wallet_type="static", chain_family="EVM", master_wallet_address="", callback_url="",
            label="")),
        "/v1/wallets/generate",
        '{"callback_url":"","chain_family":"EVM","label":"","master_wallet_address":"",'
        '"wallet_type":"static"}',
    ),
    (
        "wallets.pay_in_history none",
        lambda c: c.wallets.pay_in_history(
            EVM, date_from=None, date_to=None, page=None, page_size=None),
        "/v1/wallets/history",
        '{"address":"0x4Afb000000000000000000000000000000000001"}',
    ),
    (
        "wallets.set_label clear",
        lambda c: c.wallets.set_label(EVM, ""),
        "/v1/wallets/label",
        '{"address":"0x4Afb000000000000000000000000000000000001","label":""}',
    ),
    (
        "wallets.set_callback_url clear",
        lambda c: c.wallets.set_callback_url(EVM, ""),
        "/v1/wallets/callback-url",
        '{"address":"0x4Afb000000000000000000000000000000000001","callback_url":""}',
    ),
    (
        "sweeps.history none",
        lambda c: c.sweeps.history(
            SweepHistoryQuery(mode=None, status=None, search=None, page=None, page_size=None)),
        "/v1/sweeps/history",
        "{}",
    ),
    (
        "sweeps.wallet_history none",
        lambda c: c.sweeps.wallet_history(EVM, SweepHistoryQuery()),
        "/v1/sweeps/wallet/history",
        '{"address":"0x4Afb000000000000000000000000000000000001"}',
    ),
    (
        "sweeps.settings none",
        lambda c: c.sweeps.settings(None, None),
        "/v1/sweeps/settings",
        "{}",
    ),
    (
        "sweeps.update_settings none",
        lambda c: c.sweeps.update_settings(
            EVM, network_code=None, type_work=None, threshold_amount_usd=None, fee_mode=None,
            gas_source=None),
        "/v1/sweeps/settings/update",
        '{"address":"0x4Afb000000000000000000000000000000000001"}',
    ),
    (
        "sweeps.update_settings clear all",
        lambda c: c.sweeps.update_settings(
            EVM, network_code="TRON_MAINNET", type_work=CLEAR, threshold_amount_usd=CLEAR,
            fee_mode=CLEAR, gas_source=CLEAR),
        "/v1/sweeps/settings/update",
        '{"address":"0x4Afb000000000000000000000000000000000001",'
        '"fields":["type_work","threshold_amount_usd","fee_mode","gas_source"],'
        '"network_code":"TRON_MAINNET"}',
    ),
    (
        "sweeps.update_settings set one clear one",
        lambda c: c.sweeps.update_settings(EVM, type_work="momentum", threshold_amount_usd=CLEAR),
        "/v1/sweeps/settings/update",
        '{"address":"0x4Afb000000000000000000000000000000000001",'
        '"fields":["type_work","threshold_amount_usd"],"type_work":"momentum"}',
    ),
    (
        "static_deposits.history none",
        lambda c: c.static_deposits.history(StaticDepositHistoryQuery(
            address=None, status=None, coin=None, network=None, date_from=None, date_to=None,
            page=None, page_size=None)),
        "/v1/static-deposit/history",
        "{}",
    ),
    (
        "blockchain.contracts_available none",
        lambda c: c.blockchain.contracts_available(None),
        "/v1/blockchain/contracts/available",
        "{}",
    ),
    (
        "blockchain.wallet_balance none",
        lambda c: c.blockchain.wallet_balance("ETH_SEPOLIA", [EVM], None),
        "/v1/blockchain/wallet/balance",
        '{"addresses":["0x4Afb000000000000000000000000000000000001"],"chain":"ETH_SEPOLIA"}',
    ),
    (
        "currencies.fiat_to_crypto none",
        lambda c: c.currencies.fiat_to_crypto(
            ConvertRequest(from_="USD", to="BTC", amount="10", provider=None)),
        "/v1/currencies/convert/fiat-crypto",
        '{"amount":"10","from":"USD","to":"BTC"}',
    ),
    (
        "credits.topup none",
        lambda c: c.credits.topup(amount="25", currency="USDC", url_success=None, url_error=None),
        "/v1/credits/topup",
        '{"amount":"25","currency":"USDC"}',
    ),
    (
        "energy.quote none",
        lambda c: c.energy.quote(
            EnergyQuoteRequest(receive_address=TRON, energy=None, duration_sec=None)),
        "/v1/energy/quote",
        '{"receive_address":"TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"}',
    ),
    (
        "energy.order",
        lambda c: c.energy.order("k-1"),
        "/v1/energy/order",
        '{"key":"k-1"}',
    ),
    (
        "native.quote",
        lambda c: c.native.quote(
            NativeQuoteRequest(network="TRON_MAINNET", receive_address=TRON, amount="25")),
        "/v1/native/quote",
        '{"network":"TRON_MAINNET","receive_address":"TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t","amount":"25"}',
    ),
    (
        "native.order",
        lambda c: c.native.order("k-1"),
        "/v1/native/order",
        '{"key":"k-1"}',
    ),
    (
        "request member none",
        lambda c: c.request("/v1/raw/test", {"uuid": "u1", "label": None}),
        "/v1/raw/test",
        '{"uuid":"u1"}',
    ),
    (
        "request nested none",
        lambda c: c.request(
            "/v1/raw/test",
            {"a": {"b": None, "c": 1}, "l": [None, {"d": None, "e": "x"}], "t": (None, 1)},
        ),
        "/v1/raw/test",
        '{"a":{"c":1},"l":[null,{"e":"x"}],"t":[null,1]}',
    ),
    (
        "request top-level list",
        lambda c: c.request("/v1/raw/test", [None, {"x": None}]),
        "/v1/raw/test",
        "[null,{}]",
    ),
    (
        "request none",
        lambda c: c.request("/v1/raw/test", None),
        "/v1/raw/test",
        "",
    ),
]


@pytest.mark.parametrize(
    ("call", "path", "expected"), [c[1:] for c in CASES], ids=[c[0] for c in CASES]
)
async def test_body_matches_0_9_0(call, path, expected):
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={"uuid": "u1", "status": "paid"})

    client = CryptoChiefClient(
        merchant_id="M1", api_key="secret", transport=httpx.MockTransport(handler)
    )
    await call(client)
    await client.aclose()

    assert len(sent) == 1
    req = sent[0]
    assert req.url.path == path
    if expected:
        assert json_value(json.loads(req.content)) == json_value(json.loads(expected))
    else:
        assert req.content == b""
    assert_signed(req)


def json_value(value):
    """A JSON value in a form where equality is JSON equality: ``true != 1``, ``1 == 1.0``."""
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return (type(value).__name__, value)
    if isinstance(value, (int, float)):
        return ("number", value)
    if isinstance(value, list):
        return ("array", [json_value(v) for v in value])
    return ("object", {k: json_value(v) for k, v in value.items()})


def test_json_value_distinguishes_types():
    assert json_value({"a": 1}) == json_value({"a": 1.0})
    assert json_value({"a": 1}) != json_value({"a": True})
    assert json_value([0]) != json_value([False])
    assert json_value([None]) != json_value([""])


def _null_members(value, at="$"):
    if isinstance(value, dict):
        for k, v in value.items():
            if v is None:
                yield f"{at}.{k}"
            else:
                yield from _null_members(v, f"{at}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _null_members(v, f"{at}[{i}]")


def test_expected_bodies_have_no_null_members():
    for name, _, _, expected in CASES:
        if expected:
            assert list(_null_members(json.loads(expected))) == [], name


def _capturing_client(sent):
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={})

    return CryptoChiefClient(
        merchant_id="M1", api_key="secret", transport=httpx.MockTransport(handler)
    )


async def test_integers_are_sent_exactly():
    sent: list = []
    client = _capturing_client(sent)
    values = [2**53, 2**53 + 1, -(2**53) - 1, 2**64, 12345678901234567891, 10**30, 0, -1]
    await client.request("/v1/raw", {"v": values})
    await client.aclose()
    assert sent[0].content == (
        b'{"v":[9007199254740992,9007199254740993,-9007199254740993,18446744073709551616,'
        b"12345678901234567891,1000000000000000000000000000000,0,-1]}"
    )
    assert json.loads(sent[0].content)["v"] == values
    assert_signed(sent[0])


async def test_integral_floats_are_sent_as_integers():
    sent: list = []
    client = _capturing_client(sent)
    await client.payouts.history(HistoryQuery(page=2.0, page_size=50.0))
    await client.request(
        "/v1/raw",
        {
            "f": 1.0, "g": 2.5, "h": 1e21, "i": -0.0, "j": 1e-7, "k": 123456789.0,
            "l": 1e20, "m": -3.0, "n": [4.0, {"o": 5.0}], "t": True, "z": 0,
        },
    )
    await client.aclose()
    assert sent[0].content == b'{"page":2,"page_size":50}'
    assert sent[1].content == (
        b'{"f":1,"g":2.5,"h":1e+21,"i":0,"j":1e-07,"k":123456789,'
        b'"l":100000000000000000000,"m":-3,"n":[4,{"o":5}],"t":true,"z":0}'
    )
    for req in sent:
        assert_signed(req)


async def test_signature_covers_the_sent_bytes():
    sent: list = []
    client = _capturing_client(sent)
    await client.pay_ins.create(
        CreatePayInRequest(
            order_id="o-1",
            user_id="u-1",
            mode="crypto",
            lifetime_sec=3600,
            accuracy_payment_percent=5,
            additional_data='<b>\u041a\u043e\u0444\u0435</b> & "q" \u2028 \U0001f600',
            url_callback="https://shop.example/cb?a=1&b=2",
        )
    )
    await client.request("/v1/raw", {"memo": None, "n": 1.5, "tiny": 1e-7, "t": True})
    await client.aclose()

    for req in sent:
        assert_signed(req)
    body = json.loads(sent[0].content)
    assert body["additional_data"] == '<b>\u041a\u043e\u0444\u0435</b> & "q" \u2028 \U0001f600'
    assert body["url_callback"] == "https://shop.example/cb?a=1&b=2"
    assert "\u041a\u043e\u0444\u0435".encode("utf-8") in sent[0].content
    assert sent[1].content == b'{"n":1.5,"tiny":1e-07,"t":true}'


@pytest.mark.parametrize(
    "body",
    [
        {"n": math.nan},
        {"n": math.inf},
        [-math.inf],
        {"b": b"bytes"},
        {"s": {1, 2}},
        {"s": "\ud800"},
    ],
    ids=["nan", "inf", "-inf", "bytes", "set", "lone-surrogate"],
)
async def test_unencodable_body_is_rejected_before_sending(body):
    sent: list = []
    client = _capturing_client(sent)
    with pytest.raises(CryptoChiefError, match="cannot encode request body"):
        await client.request("/v1/raw", body)
    await client.aclose()
    assert sent == []


async def test_body_is_serialized_once_across_retries():
    sent: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        if len(sent) == 1:
            return httpx.Response(503, text="upstream")
        return httpx.Response(200, json={})

    client = CryptoChiefClient(
        merchant_id="M1",
        api_key="secret",
        transport=httpx.MockTransport(handler),
        retry_backoff={"base_ms": 1, "max_ms": 2},
    )
    await client.request("/v1/raw", {"z": 1, "a": [None, {"x": None}]})
    await client.aclose()
    assert [r.content for r in sent] == [b'{"z":1,"a":[null,{}]}'] * 2
    for req in sent:
        assert_signed(req)
