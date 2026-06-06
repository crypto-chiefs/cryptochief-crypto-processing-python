import json

import pytest

from cryptochief import (
    PayoutWebhookEvent,
    WebhookSignatureError,
    canonical_json,
    parse_webhook_event,
    sign,
    verify_webhook_signature,
)

KEY = "test_api_key_123"

EVENT = {
    "event": "payout.paid",
    "uuid": "p-1",
    "order_id": "o-1",
    "status": "paid",
    "amount_to_receive": "0.0099",
}
CANONICAL_SIG = sign(canonical_json(EVENT), KEY)


def test_accepts_canonical_body():
    assert verify_webhook_signature(KEY, canonical_json(EVENT), CANONICAL_SIG) is True


def test_accepts_unsorted_body_recanonicalized():
    unsorted = json.dumps(
        {
            "status": "paid",
            "amount_to_receive": "0.0099",
            "event": "payout.paid",
            "order_id": "o-1",
            "uuid": "p-1",
        }
    )
    assert verify_webhook_signature(KEY, unsorted, CANONICAL_SIG) is True


def test_rejects_tampered_signature():
    assert verify_webhook_signature(KEY, canonical_json(EVENT), "deadbeef") is False


def test_rejects_tampered_body():
    tampered = json.dumps({**EVENT, "amount_to_receive": "9.9999"})
    assert verify_webhook_signature(KEY, tampered, CANONICAL_SIG) is False


def test_rejects_empty_or_missing():
    assert verify_webhook_signature(KEY, "", CANONICAL_SIG) is False
    assert verify_webhook_signature(KEY, canonical_json(EVENT), None) is False


def test_parse_returns_typed_event():
    evt = parse_webhook_event(KEY, canonical_json(EVENT), CANONICAL_SIG)
    assert isinstance(evt, PayoutWebhookEvent)
    assert evt.event == "payout.paid"
    assert evt.order_id == "o-1"
    assert evt.amount_to_receive == "0.0099"


def test_parse_raises_on_bad_signature():
    with pytest.raises(WebhookSignatureError):
        parse_webhook_event(KEY, canonical_json(EVENT), "bad")
