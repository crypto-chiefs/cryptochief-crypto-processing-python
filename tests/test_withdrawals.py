"""Withdrawal info and history: the confirmation count, the finality depth, and
the status names the API actually sends.

A withdrawal used to turn ``completed`` at the first block. It now stays
``confirm_check`` - counting ``confirmations`` - until the network's finality
depth, ``required_confirmations``, is reached; ``confirmations`` is absent until
the transaction has been seen in a block at all.
"""

import json

import httpx

from cryptochief import (
    CryptoChiefClient,
    HistoryQuery,
    PayoutStatus,
    Withdrawal,
    WithdrawalStatus,
)
from cryptochief._models import from_dict

COMPLETED = {
    "uuid": "wd-1",
    "status": "completed",
    "from_address": "0xF9e8d7c6b5a43210fedcba9876543210fedcba98",
    "to_address": "0xA1b2C3d4E5f6789012345678901234567890abcd",
    "amount": "100.500000",
    "network": "ETH_MAINNET",
    "coin": "USDT",
    "need_refuel": True,
    "refuel_tx_hash": "0xrefuel",
    "refuel_status": "done",
    "tx_hash": "0xbbb",
    "confirmations": 12,
    "required_confirmations": 12,
    "estimated_fee_fiat": "1.20",
    "actual_fee_fiat": "1.18",
    "fee_mode": "service",
    "created_at": "2026-02-10T12:00:00Z",
    "completed_at": "2026-02-10T12:04:30Z",
}


def _client(captured: dict, payload: dict) -> CryptoChiefClient:
    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json=payload)

    return CryptoChiefClient(
        merchant_id="M1", api_key="secret", transport=httpx.MockTransport(handler)
    )


async def test_info_reads_a_completed_withdrawal_at_the_finality_depth():
    captured: dict = {}
    client = _client(captured, COMPLETED)

    wd = await client.withdrawals.info("wd-1")

    assert str(captured["request"].url).endswith("/v1/withdrawal/info")
    assert json.loads(captured["request"].content.decode()) == {"uuid": "wd-1"}
    assert wd.status == WithdrawalStatus.COMPLETED.value
    assert (wd.confirmations, wd.required_confirmations) == (12, 12)
    assert wd.tx_hash == "0xbbb"
    assert wd.need_refuel is True
    assert wd.refuel_tx_hash == "0xrefuel"
    assert wd.actual_fee_fiat == "1.18"
    assert wd.fee_mode == "service"
    assert wd.completed_at == "2026-02-10T12:04:30Z"
    assert wd.error_reason is None


async def test_history_items_carry_the_count_only_once_seen_in_a_block():
    captured: dict = {}
    client = _client(
        captured,
        {
            "items": [
                # In a block, short of the depth: still confirm_check, counting.
                {
                    "uuid": "wd-2",
                    "status": "confirm_check",
                    "tx_hash": "0x02",
                    "confirmations": 3,
                    "required_confirmations": 12,
                },
                # Sent, not in a block yet: no count at all, the depth already
                # known.
                {
                    "uuid": "wd-3",
                    "status": "confirm_check",
                    "tx_hash": "0x03",
                    "required_confirmations": 12,
                },
                # BTC family, in the mempool: no count either.
                {
                    "uuid": "wd-4",
                    "status": "in_mempool",
                    "network": "BTC_MAINNET",
                    "tx_hash": "abcd",
                    "required_confirmations": 2,
                },
                {
                    "uuid": "wd-5",
                    "status": "queue",
                    "required_confirmations": 1,
                },
            ],
            "meta": {"page": 1, "page_size": 20, "total": 4, "total_pages": 1},
        },
    )

    res = await client.withdrawals.history(HistoryQuery(page=1, page_size=20))

    assert str(captured["request"].url).endswith("/v1/withdrawal/history")
    assert res.items is not None
    in_block, sent, mempool, queued = res.items
    assert (in_block.status, in_block.confirmations, in_block.required_confirmations) == (
        WithdrawalStatus.CONFIRM_CHECK.value,
        3,
        12,
    )
    assert (sent.status, sent.confirmations, sent.required_confirmations) == (
        "confirm_check",
        None,
        12,
    )
    assert (mempool.status, mempool.confirmations) == (WithdrawalStatus.IN_MEMPOOL.value, None)
    assert (queued.confirmations, queued.required_confirmations) == (None, 1)
    # A count above zero is not settlement; only completed is.
    assert in_block.status != WithdrawalStatus.COMPLETED.value
    assert in_block.completed_at is None


def test_a_zero_count_is_a_count_not_an_absence():
    wd = from_dict(
        Withdrawal,
        {
            "uuid": "wd-6",
            "status": "confirm_check",
            "confirmations": 0,
            "required_confirmations": 6,
        },
    )

    assert wd.confirmations == 0
    assert wd.required_confirmations == 6


def test_a_failed_withdrawal_reads_its_reason():
    failed = from_dict(
        Withdrawal,
        {
            "uuid": "wd-7",
            "status": "failed",
            "tx_hash": "0x07",
            "error_reason": "TX_CONFIRM_TIMEOUT",
            "required_confirmations": 12,
        },
    )

    assert failed.status == WithdrawalStatus.FAILED.value
    assert failed.error_reason == "TX_CONFIRM_TIMEOUT"
    assert failed.confirmations is None
    assert failed.completed_at is None


def test_the_deprecated_cancelled_status_still_parses():
    # Not produced by the API; kept so an old value still decodes.
    wd = from_dict(Withdrawal, {"uuid": "wd-8", "status": "cancelled"})

    assert wd.status == WithdrawalStatus.CANCELLED.value


def test_a_server_without_the_depth_reads_it_as_unknown():
    # A server that predates the fields sends neither; that is unknown, not a
    # zero threshold, and the rest still decodes.
    wd = from_dict(Withdrawal, {"uuid": "wd-9", "status": "completed", "tx_hash": "0x09"})

    assert wd.confirmations is None
    assert wd.required_confirmations is None
    assert wd.status == "completed"


def test_withdrawal_statuses_are_the_names_the_api_sends():
    assert {s.value for s in WithdrawalStatus} == {
        "queue",
        "refueling",
        "refuel_confirmed",
        "broadcasting",
        "sending",
        "in_mempool",
        "confirm_check",
        "completed",
        "failed",
        "cancelled",  # deprecated: not produced by the API
    }
    # paid and system_fail belong to payouts, not withdrawals.
    assert PayoutStatus.PAID.value not in {s.value for s in WithdrawalStatus}
    assert PayoutStatus.SYSTEM_FAIL.value not in {s.value for s in WithdrawalStatus}
