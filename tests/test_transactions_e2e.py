"""End-to-end exercise of the transactions service through a mocked transport.

Validates that contract-call helpers assemble the right request body and encode
``data`` correctly, without hitting the network.
"""

import base64
import json

import httpx
from pytoniq_core import Cell

from cryptochief import (
    Chain,
    CryptoChiefClient,
    EvmCallRequest,
    JettonTransferRequest,
    human_to_base,
)

ADDR = "EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs"


async def test_jetton_transfer_explicit_wallet_no_rpc():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.content
        return httpx.Response(200, json={"uuid": "tx-1", "status": "signed", "tx_hash": "h"})

    client = CryptoChiefClient(merchant_id="M", api_key="K", transport=httpx.MockTransport(handler))
    resp = await client.transactions.jetton_transfer(
        JettonTransferRequest(
            network=Chain.TON_MAINNET,
            from_address=ADDR,
            jetton_wallet_address=ADDR,  # explicit -> no RPC lookup
            recipient=ADDR,
            amount=human_to_base("5", 6),
            attached_ton=70_000_000,  # explicit -> no RPC has_jetton_wallet call
            memo="Order #1",
        )
    )
    assert resp.uuid == "tx-1"
    assert captured["url"].endswith("/v1/transaction/signature")

    body = json.loads(captured["body"])
    assert body["type"] == "contract"
    assert body["network"] == "TON_MAINNET"
    call = body["calls"][0]
    assert call["to"] == ADDR
    assert call["bounce"] is True
    assert call["value"] == "70000000"
    boc = base64.b64decode(call["data"])
    slice_ = Cell.one_from_boc(boc).begin_parse()
    assert slice_.load_uint(32) == 0x0F8A7EA5  # jetton transfer op
    await client.aclose()


async def test_evm_call_body_shape():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content
        return httpx.Response(200, json={"uuid": "tx-2", "status": "signed"})

    client = CryptoChiefClient(merchant_id="M", api_key="K", transport=httpx.MockTransport(handler))
    await client.transactions.sign_evm_call(
        EvmCallRequest(
            network=Chain.ETH_MAINNET,
            from_address="0x1",
            contract="0xabc",
            method="transfer(address,uint256)",
            args=["0xbcd4042de499d14e55001ccbb24a551f3b954096", 1_000_000],
        )
    )
    body = json.loads(captured["body"])
    assert body["type"] == "contract"
    call = body["calls"][0]
    assert call["to"] == "0xabc"
    assert call["value"] == "0"
    assert call["data"].startswith("0xa9059cbb")
    await client.aclose()
