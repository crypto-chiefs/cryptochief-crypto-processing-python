"""The outbound-webhook surface: reading a delivery with its attempts, the three
routes, and that a refusal is an APIError with the machine code rather than a
``queued=False`` result."""

import json

import httpx
import pytest

from cryptochief import (
    APIError,
    CryptoChiefClient,
    ErrorCode,
    WEBHOOK_DELIVERY_HEADER,
    WebhookDeliveryStatus,
)

DELIVERY = {
    "uuid": "44444444-4444-4444-8444-444444444444",
    "event_type": "invoice.paid",
    "reference": "order-1",
    "target_url": "https://m.example/hook",
    "status": "failed",
    "attempts": 3,
    "max_attempts": 10,
    "resend_count": 1,
    "last_error": "HTTP 500",
    "last_http_status": 500,
    "next_attempt_at": None,
    "delivered_at": None,
    "created_at": "2026-09-03T10:00:00Z",
    "superseded_by": None,
    "attempt_history": [
        {
            "attempt": 3,
            "http_status": 500,
            "error": "HTTP 500",
            "duration_ms": 120,
            "target_url": "https://m.example/hook",
            "created_at": "2026-09-03T10:02:00Z",
            "response_body": "<html>oops",
            "response_content_type": "text/html",
            "response_truncated": True,
        },
        {
            "attempt": 2,
            "http_status": None,
            "error": "dial tcp: connection refused",
            "duration_ms": None,
            "target_url": "https://m.example/hook",
            "created_at": None,
            "response_body": None,
            "response_content_type": None,
            "response_truncated": False,
        },
    ],
    "payload": {"body": '{"event":"invoice.paid"}', "bytes": 24, "truncated": False},
}


def _client(captured: dict, status: int, payload: dict) -> CryptoChiefClient:
    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(status, json=payload)

    return CryptoChiefClient(merchant_id="M1", api_key="secret", transport=httpx.MockTransport(handler))


def _body(captured: dict) -> dict:
    return json.loads(captured["request"].content.decode())


async def test_info_reads_attempts_and_keeps_none_as_not_recorded():
    captured: dict = {}
    client = _client(captured, 200, DELIVERY)

    d = await client.webhooks.info(DELIVERY["uuid"])

    assert str(captured["request"].url).endswith("/v1/webhooks/info")
    assert _body(captured) == {"uuid": DELIVERY["uuid"]}
    assert d.status == WebhookDeliveryStatus.FAILED.value
    assert d.last_http_status == 500
    assert d.delivered_at is None and d.superseded_by is None
    assert len(d.attempt_history) == 2
    answered, silent = d.attempt_history
    assert answered.response_truncated is True
    assert answered.response_content_type == "text/html"
    # An attempt nothing answered has no status and no body - only the error.
    assert silent.http_status is None and silent.response_body is None and silent.created_at is None
    assert "connection refused" in (silent.error or "")
    assert d.payload is not None and d.payload.bytes == 24


async def test_resend_static_deposit_is_addressed_by_the_deposit_uuid():
    captured: dict = {}
    client = _client(
        captured,
        200,
        {
            "uuid": "dep-1",
            "deliveries": [
                {
                    "uuid": "d-1",
                    "event_type": "static_deposit.paid",
                    "reference": "dep-1",
                    "status": "delivered",
                    "queued": True,
                    "attempts": 2,
                    "resend_count": 1,
                }
            ],
            "queued": 1,
            "total": 1,
        },
    )

    out = await client.webhooks.resend_static_deposit("dep-1")

    assert str(captured["request"].url).endswith("/v1/static-deposits/resend")
    assert _body(captured) == {"uuid": "dep-1"}
    assert out.queued == 1 and out.total == 1
    assert out.deliveries[0].queued is True and out.deliveries[0].resend_count == 1


async def test_refusal_is_an_api_error_with_the_code():
    captured: dict = {}
    client = _client(
        captured,
        409,
        {
            "ok": False,
            "error": "DELIVERY_SUPERSEDED",
            "msg": "not the latest; resend invoice.paid instead",
            "superseded_by": "invoice.paid",
        },
    )

    with pytest.raises(APIError) as exc:
        await client.webhooks.resend(DELIVERY["uuid"])

    assert exc.value.code == ErrorCode.DELIVERY_SUPERSEDED.value
    assert exc.value.http_status == 409
    assert "invoice.paid" in str(exc.value)


def test_delivery_header_name():
    assert WEBHOOK_DELIVERY_HEADER == "X-Webhook-Delivery"
