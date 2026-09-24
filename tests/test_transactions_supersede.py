"""EVM signature supersede: the ``cancelled`` status, ``superseded_uuids`` on the
sign answer, ``error_reason`` on the transaction, and the new error codes.
"""

import json

import httpx
import pytest

from cryptochief import (
    APIError,
    Chain,
    CryptoChiefClient,
    ErrorCode,
    ExecuteTransactionRequest,
    SignTransactionRequest,
    SignTransactionResponse,
    TransactionInfo,
    TxStatus,
    TxType,
    is_transaction_terminal,
)
from cryptochief._models import from_dict

EVM = "0x4Afb000000000000000000000000000000000001"
EVM2 = "0xcCb1000000000000000000000000000000000002"
OLD = "0c1d9f3e-5a7b-4c2e-9f1a-3b6d8e2f4a10"
NEW = "b4ee6a7a-f7c2-474d-b002-e83ebe3e78db"


def _client(handler) -> CryptoChiefClient:
    return CryptoChiefClient(
        merchant_id="M1",
        api_key="secret",
        transport=httpx.MockTransport(handler),
        retry_backoff={"base_ms": 1, "max_ms": 2},
    )


def test_cancelled_is_a_final_status():
    assert TxStatus.CANCELLED.value == "cancelled"
    assert is_transaction_terminal("cancelled")
    for live in ("signed", "broadcasting", "broadcasted"):
        assert not is_transaction_terminal(live)


async def test_wait_for_returns_a_superseded_signature():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            200,
            json={
                "uuid": OLD,
                "status": "cancelled",
                "error_reason": "SUPERSEDED_BY:" + NEW,
            },
        )

    client = _client(handler)
    # A status the helper does not treat as final would spin until the
    # timeout and raise.
    tx = await client.transactions.wait_for(OLD, interval=0.01, timeout=0.2)
    await client.aclose()

    assert tx.status == "cancelled"
    assert tx.error_reason == "SUPERSEDED_BY:" + NEW
    assert calls["n"] == 1


async def test_sign_reports_the_signatures_it_replaced():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "uuid": NEW,
                "status": "signed",
                "network": "ETH_MAINNET",
                "chain_family": "EVM",
                "signed_tx_hex": "0x02",
                "tx_hash": "0xabc",
                "expires_at": "2026-06-01T12:10:00Z",
                "superseded_uuids": [OLD],
            },
        )

    client = _client(handler)
    res = await client.transactions.sign(
        SignTransactionRequest(
            network=Chain.ETH_MAINNET,
            from_address=EVM,
            type=TxType.NATIVE.value,
            to_address=EVM2,
            value="1",
        )
    )
    await client.aclose()
    assert res.superseded_uuids == [OLD]


def test_superseded_uuids_absent_reads_as_empty():
    res = from_dict(SignTransactionResponse, {"uuid": NEW, "status": "signed"})
    assert res.superseded_uuids == []


def test_info_carries_error_reason():
    tx = from_dict(
        TransactionInfo,
        {
            "uuid": NEW,
            "status": "signed",
            "error_reason": "NONCE_GAP: missing_nonce=7 blocking_uuid=" + OLD,
        },
    )
    assert tx.error_reason == "NONCE_GAP: missing_nonce=7 blocking_uuid=" + OLD


@pytest.mark.parametrize(
    "msg, member",
    [
        ("NONCE_GAP", ErrorCode.NONCE_GAP),
        ("NONCE_ALREADY_USED", ErrorCode.NONCE_ALREADY_USED),
    ],
)
async def test_execute_nonce_codes(msg, member):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "SERVICE_ERROR", "msg": msg, "ok": False})

    client = _client(handler)
    with pytest.raises(APIError) as ei:
        await client.transactions.execute(ExecuteTransactionRequest(uuid=NEW))
    await client.aclose()
    assert ei.value.code == member
    assert ei.value.http_status == 400


async def test_sign_refused_while_an_execute_is_unresolved():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": "SERVICE_ERROR",
                "msg": "PREVIOUS_EXECUTE_UNRESOLVED: uuid=" + OLD,
                "ok": False,
            },
        )

    client = _client(handler)
    with pytest.raises(APIError) as ei:
        await client.transactions.sign(
            SignTransactionRequest(
                network=Chain.ETH_MAINNET,
                from_address=EVM,
                type=TxType.NATIVE.value,
                to_address=EVM2,
                value="1",
            )
        )
    await client.aclose()
    assert ei.value.code.startswith(ErrorCode.PREVIOUS_EXECUTE_UNRESOLVED.value)
    assert ei.value.code.endswith(OLD)
    assert json.loads(ei.value.raw or "{}")["msg"].endswith(OLD)
