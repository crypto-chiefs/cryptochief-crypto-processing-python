import json

import pytest

from cryptochief import (
    PayoutWebhookEvent,
    SweepWebhookEvent,
    TransactionWebhookEvent,
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


def _signed(body: dict) -> tuple[str, str]:
    raw = canonical_json(body)
    return raw, sign(raw, KEY)


def test_payout_webhook_carries_confirmations_and_leaves_them_out_before_a_transaction():
    # payout.paid goes out once every source has reached the depth, so the
    # lowest count is at least required_confirmations.
    paid = {
        **EVENT,
        "sources": [
            {"address": "0xa", "txid": "0x01", "confirmations": 12},
            {"address": "0xb", "txid": "0x02", "confirmations": 5},
        ],
        "service_operations": [{"type": "gas_refuel", "txid": "0x03", "confirmations": 30}],
        "confirmations": 5,
        "required_confirmations": 5,
    }
    evt = parse_webhook_event(KEY, *_signed(paid))
    assert isinstance(evt, PayoutWebhookEvent)
    assert evt.confirmations == 5
    assert evt.required_confirmations == 5
    assert [s["confirmations"] for s in evt.sources] == [12, 5]
    assert evt.service_operations[0]["confirmations"] == 30

    failed = {
        "event": "payout.system_fail",
        "uuid": "p-2",
        "status": "system_fail",
        "sources": [{"address": "0xa"}],
        "service_operations": [],
    }
    evt = parse_webhook_event(KEY, *_signed(failed))
    assert isinstance(evt, PayoutWebhookEvent)
    assert evt.confirmations is None
    assert "confirmations" not in evt.sources[0]
    # A payout handled before the platform recorded the depth carries none:
    # unknown, not a zero threshold.
    assert evt.required_confirmations is None


def test_transaction_webhook_carries_confirmations_and_the_threshold():
    confirmed = {
        "event": "transaction.confirmed",
        "uuid": "tx-1",
        "status": "confirmed",
        "tx_hash": "0xabc",
        "confirmations": 13,
        "required_confirmations": 12,
    }
    evt = parse_webhook_event(KEY, *_signed(confirmed))
    assert isinstance(evt, TransactionWebhookEvent)
    assert (evt.confirmations, evt.required_confirmations) == (13, 12)

    expired = {
        "event": "transaction.expired",
        "uuid": "tx-2",
        "status": "expired",
        "confirmations": 0,
        "required_confirmations": 1,
    }
    evt = parse_webhook_event(KEY, *_signed(expired))
    assert isinstance(evt, TransactionWebhookEvent)
    assert (evt.confirmations, evt.required_confirmations) == (0, 1)


SWEEP_CONFIRMED = {
    "event": "sweep.confirmed",
    "task_id": "t-1",
    "status": "completed",
    "wallet_address": "0xdeposit",
    "network": "ETH_MAINNET",
    "asset_symbol": "USDT",
    "sweep_tx_hash": "0xsweep",
}


def test_sweep_webhook_carries_the_finality_depth_it_was_held_to():
    body = {**SWEEP_CONFIRMED, "sweep_confirmations": 12, "required_confirmations": 12}
    evt = parse_webhook_event(KEY, *_signed(body))
    assert isinstance(evt, SweepWebhookEvent)
    assert evt.status == "completed"
    assert (evt.sweep_confirmations, evt.required_confirmations) == (12, 12)
    assert evt.sweep_confirmations >= evt.required_confirmations


def test_sweep_webhook_from_an_older_sweep_service_has_no_depth():
    # A sweep service built before sweeps waited for finality reports no depth,
    # and the platform leaves the key out rather than sending 0.
    body = {**SWEEP_CONFIRMED, "sweep_confirmations": 1}
    evt = parse_webhook_event(KEY, *_signed(body))
    assert isinstance(evt, SweepWebhookEvent)
    assert evt.sweep_confirmations == 1
    assert evt.required_confirmations is None
