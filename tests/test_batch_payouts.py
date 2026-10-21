"""Batch payout item HTTP statuses, serialization, and retry decisions."""

import httpx
import pytest

from cryptochief import (
    BatchItemResult,
    BatchPayoutRequest,
    BatchPayoutResponse,
    CryptoChiefClient,
    ExecutePayoutRequest,
    is_batch_item_retryable,
)
from cryptochief._models import to_payload


@pytest.mark.parametrize(
    "method,success_status,success_field",
    [("batch_estimate", "ok", "estimate"), ("batch_execute", "queue", "payout")],
)
async def test_batch_item_http_status(method, success_status, success_field):
    items = [
        {"index": 0, "status": success_status, success_field: {}},
        {"index": 1, "status": "error", "error": "INVALID_PARAMS", "http_status": 400},
        {"index": 2, "status": "error", "error": "RPC_ERROR", "http_status": 502},
        {"index": 3, "status": "error", "error": "RPC_ERROR"},
        {"index": 4, "status": "error", "error": "RPC_ERROR", "http_status": None},
        {"index": 5, "status": "error", "error": "FUTURE_ERROR", "http_status": 599},
    ]
    if method == "batch_execute":
        for item in items:
            item["order_id"] = f"order-{item['index']}"
        items[0]["uuid"] = "payout-0"

    payload = {"total": len(items), "items": items}
    if method == "batch_estimate":
        payload.update(ok=1, failed=5, total_estimated_fee_fiat="0")
    else:
        payload.update(batch_uuid="batch-1", accepted=1, rejected=5)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == f"/v1/payout/{method.replace('_', '/')}"
        return httpx.Response(200, json=payload)

    req = BatchPayoutRequest(
        items=[
            ExecutePayoutRequest(
                network="ETH_SEPOLIA",
                coin="ETH",
                amount="0.01",
                to_address="0x1",
                order_id=f"order-{index}",
                user_id="user-1",
                url_callback="https://example.test/callback",
            )
            for index in range(len(items))
        ]
    )
    async with CryptoChiefClient(
        merchant_id="M1", api_key="secret", transport=httpx.MockTransport(handler)
    ) as client:
        result = await getattr(client.payouts, method)(req)

    assert isinstance(result, BatchPayoutResponse)
    assert result.items is not None
    assert all(isinstance(item, BatchItemResult) for item in result.items)
    assert [item.index for item in result.items] == list(range(6))
    assert [item.status for item in result.items] == [success_status] + ["error"] * 5
    assert [item.error for item in result.items] == [item.get("error") for item in items]
    assert [item.http_status for item in result.items] == [None, 400, 502, None, None, 599]
    assert [is_batch_item_retryable(item) for item in result.items] == [
        False, False, True, False, False, False
    ]
    if method == "batch_execute":
        assert [item.order_id for item in result.items] == [f"order-{index}" for index in range(6)]
        assert result.items[0].uuid == "payout-0"

    serialized = to_payload(result)["items"]
    for index in (0, 3, 4):
        assert "http_status" not in serialized[index]
    for index, status in ((1, 400), (2, 502), (5, 599)):
        assert serialized[index]["http_status"] == status


@pytest.mark.parametrize("error", [None, "RPC_ERROR", "FUTURE_ERROR"])
@pytest.mark.parametrize(
    "http_status,expected",
    [
        (None, False),
        (0, False),
        (400, False),
        (408, False),
        (500, False),
        (502, True),
        (503, False),
        (504, False),
        (599, False),
    ],
)
def test_batch_item_retryable_only_for_http_502(http_status, expected, error):
    item = BatchItemResult(status="error", error=error, http_status=http_status)
    assert is_batch_item_retryable(item) is expected
