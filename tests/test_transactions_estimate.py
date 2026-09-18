"""Fee estimation for transactions: POST /v1/transaction/estimate.

Mirrors the sign/execute mocked-transport tests: the request body must carry
the transfer fields (and no ``url_callback``), the response decodes into
``EstimateTransactionResponse``, and an API refusal (e.g. ``type="contract"``)
propagates as a typed ``APIError``.
"""

import json
from decimal import Decimal

import httpx
import pytest

from cryptochief import (
    APIError,
    Chain,
    CryptoChiefClient,
    ErrorCode,
    EstimateTransactionRequest,
    EstimateTransactionResponse,
    TxType,
    is_api_error,
)

EVM = "0x4Afb000000000000000000000000000000000001"
EVM2 = "0xcCb1000000000000000000000000000000000002"
USDT = "0xdAC17F958D2ee523a2206206994597C13D831ec7"

NATIVE_BODY = {
    "network": "ETH_MAINNET",
    "chain_family": "EVM",
    "type": "native",
    "from_address": EVM,
    "to_address": EVM2,
    "estimated_fee": "0.00042",
    "estimated_fee_fiat": "1.35",
    "required": "0.01042",
    "required_fiat": "33.49",
}

TOKEN_BODY = {
    "network": "ETH_MAINNET",
    "chain_family": "EVM",
    "type": "token",
    "from_address": EVM,
    "to_address": EVM2,
    "estimated_fee": "0.00063",
    "estimated_fee_fiat": "",
    "required": "0.00063",
    "required_fiat": "",
}

TRON = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
TRON2 = "TLyqzVGLV1srkB7dToTAEqgDSfPtXRJZYH"

# TRON answers carry the fee breakdown the other networks omit:
# energy_fee + bandwidth_fee + activation_fee = estimated_fee (gross).
TRON_TOKEN_BODY = {
    "network": "TRON_MAINNET",
    "chain_family": "TRON",
    "type": "token",
    "from_address": TRON,
    "to_address": TRON2,
    "estimated_fee": "13.585900",
    "estimated_fee_fiat": "3.89",
    "required": "13.585900",
    "required_fiat": "3.89",
    "fee_expected": "0.0",
    "fee_limit": "150.0",
    "energy": 65000,
    "energy_fee": "13.000000",
    "bandwidth_fee": "0.585900",
    "activation_fee": "0.0",
}

TRON_NATIVE_BODY = {
    "network": "TRON_MAINNET",
    "chain_family": "TRON",
    "type": "native",
    "from_address": TRON,
    "to_address": TRON2,
    "estimated_fee": "1.100000",
    "estimated_fee_fiat": "0.32",
    "required": "2.100000",
    "required_fiat": "0.61",
    "fee_expected": "1.100000",
    "fee_limit": "2.0",
    # no "energy": a native transfer burns no energy, and the field is omitempty
    "energy_fee": "0.0",
    "bandwidth_fee": "0.300000",
    "activation_fee": "0.800000",
}


def _client(handler) -> CryptoChiefClient:
    return CryptoChiefClient(
        merchant_id="M1",
        api_key="secret",
        transport=httpx.MockTransport(handler),
        retry_backoff={"base_ms": 1, "max_ms": 2},
    )


async def test_estimate_native_transfer():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.content
        return httpx.Response(200, json=NATIVE_BODY)

    client = _client(handler)
    est = await client.transactions.estimate(
        EstimateTransactionRequest(
            network=Chain.ETH_MAINNET,
            from_address=EVM,
            type=TxType.NATIVE.value,
            to_address=EVM2,
            value="10000000000000000",
        )
    )
    await client.aclose()

    assert captured["url"].endswith("/v1/transaction/estimate")
    body = json.loads(captured["body"])
    assert body == {
        "network": "ETH_MAINNET",
        "from_address": EVM,
        "type": "native",
        "to_address": EVM2,
        "value": "10000000000000000",
    }

    assert est.estimated_fee == "0.00042"
    assert est.estimated_fee_fiat == "1.35"
    assert est.required == "0.01042"  # fee + value for a native transfer
    assert est.required_fiat == "33.49"
    assert est.network == "ETH_MAINNET"
    assert est.chain_family == "EVM"
    assert est.type == "native"
    assert est.from_address == EVM
    assert est.to_address == EVM2


async def test_estimate_token_transfer():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content
        return httpx.Response(200, json=TOKEN_BODY)

    client = _client(handler)
    est = await client.transactions.estimate(
        EstimateTransactionRequest(
            network=Chain.ETH_MAINNET,
            from_address=EVM,
            type=TxType.TOKEN.value,
            to_address=EVM2,
            value="12500000",
            contract=USDT,
        )
    )
    await client.aclose()

    body = json.loads(captured["body"])
    assert body["type"] == "token"
    assert body["contract"] == USDT

    # required is the fee alone - the token value is not native coin
    assert est.required == est.estimated_fee == "0.00063"
    # no rate available: the fiat fields arrive as empty strings, not None
    assert est.estimated_fee_fiat == ""
    assert est.required_fiat == ""
    # not TRON: no fee breakdown on the wire, no breakdown in the model
    assert est.fee_expected is None
    assert est.fee_limit is None
    assert est.energy is None
    assert est.energy_fee is None
    assert est.bandwidth_fee is None
    assert est.activation_fee is None


async def test_estimate_tron_token_maps_fee_breakdown():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=TRON_TOKEN_BODY)

    client = _client(handler)
    est = await client.transactions.estimate(
        EstimateTransactionRequest(
            network=Chain.TRON_MAINNET,
            from_address=TRON,
            type=TxType.TOKEN.value,
            to_address=TRON2,
            value="12500000",
            contract=TRON,  # TRC-20 contract, base58
        )
    )
    await client.aclose()

    assert est.chain_family == "TRON"
    # the wallet's energy pool covers the burn: expected fee is zero, gross is not
    assert est.fee_expected == "0.0"
    assert est.fee_limit == "150.0"
    assert est.energy == 65000
    assert est.energy_fee == "13.000000"
    assert est.bandwidth_fee == "0.585900"
    assert est.activation_fee == "0.0"
    # energy_fee + bandwidth_fee + activation_fee = estimated_fee
    assert Decimal(est.energy_fee) + Decimal(est.bandwidth_fee) + Decimal(
        est.activation_fee
    ) == Decimal(est.estimated_fee)


async def test_estimate_tron_native_to_new_address_has_activation_fee():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=TRON_NATIVE_BODY)

    client = _client(handler)
    est = await client.transactions.estimate(
        EstimateTransactionRequest(
            network=Chain.TRON_MAINNET,
            from_address=TRON,
            type=TxType.NATIVE.value,
            to_address=TRON2,
            value="1000000",
        )
    )
    await client.aclose()

    assert est.type == "native"
    assert est.activation_fee == "0.800000"  # fresh recipient address
    assert est.energy is None  # a native transfer burns no energy - omitted
    assert est.energy_fee == "0.0"
    assert est.bandwidth_fee == "0.300000"
    assert est.fee_expected == "1.100000"


async def test_estimate_contract_type_is_refused():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "ok": False,
                "error": "CONTRACT_ESTIMATE_UNSUPPORTED",
                "msg": "contract calls cannot be estimated",
            },
        )

    client = _client(handler)
    with pytest.raises(APIError) as ei:
        await client.transactions.estimate(
            EstimateTransactionRequest(
                network=Chain.ETH_MAINNET,
                from_address=EVM,
                type=TxType.CONTRACT.value,
            )
        )
    await client.aclose()

    assert is_api_error(ei.value, ErrorCode.CONTRACT_ESTIMATE_UNSUPPORTED)
    assert ei.value.code == "CONTRACT_ESTIMATE_UNSUPPORTED"
    assert ei.value.message == "contract calls cannot be estimated"
    assert ei.value.http_status == 400


def test_estimate_response_decodes_empty_body():
    """A ``null`` data payload still decodes - every response model has defaults."""
    est = EstimateTransactionResponse()
    assert est.estimated_fee == ""
    assert est.estimated_fee_fiat is None
    assert est.network is None
    assert est.fee_expected is None
    assert est.fee_limit is None
    assert est.energy is None
    assert est.energy_fee is None
    assert est.bandwidth_fee is None
    assert est.activation_fee is None
