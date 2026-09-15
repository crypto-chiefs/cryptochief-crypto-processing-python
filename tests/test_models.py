"""The dataclass <-> wire helpers: serialization drops None, parsing tolerates extras."""

import inspect

from cryptochief import (
    AssetsPolicy,
    Asset,
    Chain,
    CryptoCurrencies,
    EstimatePayoutRequest,
    EstimatePayoutResponse,
    ExecutePayoutRequest,
    PayoutHistoryResponse,
    PayoutInfo,
    PayoutStatus,
    TransactionHistoryResponse,
    TransactionInfo,
    TxStatus,
    is_payout_terminal,
    is_transaction_terminal,
)
from cryptochief._models import from_dict, to_payload
from cryptochief.services.payouts import PayoutsService


def test_to_payload_drops_none_and_converts_enums():
    req = EstimatePayoutRequest(
        network=Chain.ETH_SEPOLIA, coin="ETH", amount="0.0001", to_address="0x1"
    )
    payload = to_payload(req)
    assert payload == {
        "network": "ETH_SEPOLIA",  # enum -> value
        "coin": "ETH",
        "amount": "0.0001",
        "to_address": "0x1",
    }
    assert "memo" not in payload  # None dropped


def test_to_payload_nested_dataclass_and_list():
    req = EstimatePayoutRequest(
        network="ETH_MAINNET",
        coin="USDT",
        amount="10",
        to_address="0x1",
        auto_convert=True,
        auto_convert_policy=AssetsPolicy(allow=[Asset(network="ETH_MAINNET", coin="USDC")]),
    )
    payload = to_payload(req)
    assert payload["auto_convert"] is True
    assert payload["auto_convert_policy"] == {"allow": [{"network": "ETH_MAINNET", "coin": "USDC"}]}


def test_execute_request_inherits_transfer_fields():
    req = ExecutePayoutRequest(
        network="ETH_SEPOLIA",
        coin="ETH",
        amount="1",
        to_address="0x1",
        order_id="o1",
        user_id="u1",
        url_callback="https://x/cb",
    )
    payload = to_payload(req)
    assert payload["order_id"] == "o1"
    assert payload["network"] == "ETH_SEPOLIA"


def test_from_dict_nested_and_tolerates_unknown_keys():
    res = from_dict(
        EstimatePayoutResponse,
        {
            "network": "ETH_SEPOLIA",
            "amount_to_receive": "0.0099",
            "fee_info": {"fee_mode": "service", "estimated_fiat": "0.10"},
            "sources": [{"address": "0xabc", "amount_crypto": "0.01"}],
            "some_future_field": {"nested": 1},  # unknown -> ignored
        },
    )
    assert res.amount_to_receive == "0.0099"
    assert res.fee_info.fee_mode == "service"
    assert res.sources[0].address == "0xabc"
    assert res.sources[0].amount_crypto == "0.01"
    assert not hasattr(res, "some_future_field")


def test_payout_source_decodes_the_wire_shape():
    payout = from_dict(
        PayoutInfo,
        {
            "uuid": "p-4",
            "status": "paid",
            "sources": [
                {
                    "address": "0xa",
                    "network": "ETH_SEPOLIA",
                    "coin": "ETH",
                    "amount_crypto": "0.0001",
                    "amount_crypto_raw": "100000000000000",
                    "need_refuel": True,
                    "refuel_amount": "0.00002",
                    "estimated_fee": "0.00001",
                    "estimated_fee_fiat": "0.03",
                    "fee_paid": "0.000009",
                    "fee_paid_fiat": "0.027",
                    "txid": "0x01",
                    "confirmations": 32,
                }
            ],
        },
    )

    assert payout.sources is not None
    src = payout.sources[0]
    assert src.amount_crypto == "0.0001"
    assert src.txid == "0x01"
    assert src.network == "ETH_SEPOLIA"
    assert src.need_refuel is True
    assert (src.refuel_amount, src.estimated_fee, src.estimated_fee_fiat) == (
        "0.00002",
        "0.00001",
        "0.03",
    )
    assert (src.fee_paid, src.fee_paid_fiat) == ("0.000009", "0.027")
    assert src.confirmations == 32
    # The platform does not send ``amount``.
    assert src.amount is None


def test_from_dict_of_a_null_body_is_an_all_defaults_instance():
    # A Go service building its answer from a nil value marshals JSON `null`,
    # which has to decode rather than raise: every response model is
    # constructible with no arguments.
    res = from_dict(EstimatePayoutResponse, None)

    assert res.network is None
    assert res.sources is None
    assert list(res.sources or []) == []


def test_from_dict_reads_a_null_inside_a_map_of_lists_as_an_empty_list():
    rates = from_dict(
        CryptoCurrencies,
        {"tickers": None, "by_exchange": {"binance": ["BTC"], "exmo": None}},
    )

    # Optional[List[...]] keeps its None: there the absence is part of the
    # declared shape, and `x or []` is the idiom for it.
    assert rates.tickers is None
    # The map's value type is a plain List[str], so a null arriving as one of
    # its values would be a None sitting in a list slot - it type-checks and
    # then blows up in the caller's loop. It decodes as [] and stays iterable.
    assert rates.by_exchange == {"binance": ["BTC"], "exmo": []}


def test_payout_info_carries_confirmations_per_source_and_the_lowest():
    res = from_dict(
        PayoutHistoryResponse,
        {
            "items": [
                {
                    "uuid": "p-1",
                    "status": "confirm_check",
                    "sources": [
                        {"address": "0xa", "amount_crypto": "1", "txid": "0x01", "confirmations": 12},
                        {"address": "0xb", "amount_crypto": "2", "txid": "0x02", "confirmations": 3},
                        # Broadcast, not seen on chain yet: no count, and the
                        # top-level lowest takes it as 0.
                        {"address": "0xc", "amount_crypto": "3", "txid": "0x03"},
                    ],
                    "service_operations": [
                        {"type": "gas_refuel", "txid": "0x04", "confirmations": 20},
                        {"type": "gas_refuel", "status": "planned"},
                    ],
                    "confirmations": 0,
                    "required_confirmations": 12,
                }
            ]
        },
    )

    assert res.items is not None
    payout = res.items[0]
    assert payout.sources is not None
    assert [s.confirmations for s in payout.sources] == [12, 3, None]
    assert payout.confirmations == 0
    # One source is at the depth, the others are not: still confirm_check, not paid.
    assert payout.required_confirmations == 12
    assert PayoutStatus(payout.status) is PayoutStatus.CONFIRM_CHECK
    assert not is_payout_terminal(payout.status)
    assert payout.service_operations is not None
    assert payout.service_operations[0]["confirmations"] == 20
    assert "confirmations" not in payout.service_operations[1]


def test_payout_info_before_any_transaction_has_no_confirmations_at_all():
    # A queued payout has sent nothing: the platform leaves every count out,
    # but already names the depth the payout will wait for.
    payout = from_dict(
        PayoutInfo,
        {
            "uuid": "p-2",
            "status": "queue",
            "sources": [{"address": "0xa", "amount_crypto": "1"}],
            "service_operations": [{"type": "gas_refuel", "status": "planned"}],
            "required_confirmations": 1,
        },
    )

    assert payout.confirmations is None
    assert payout.sources is not None
    assert payout.sources[0].confirmations is None
    assert payout.service_operations == [{"type": "gas_refuel", "status": "planned"}]
    assert payout.required_confirmations == 1


def test_payout_info_without_required_confirmations_reads_it_as_unknown():
    # A server that predates the field sends no depth; that is unknown, not a
    # zero threshold, and the rest of the payout still decodes.
    payout = from_dict(
        PayoutInfo,
        {
            "uuid": "p-3",
            "status": "paid",
            "sources": [{"address": "0xa", "amount_crypto": "1", "txid": "0x01", "confirmations": 3}],
            "confirmations": 3,
        },
    )

    assert payout.required_confirmations is None
    assert payout.confirmations == 3
    assert payout.status == "paid"


def test_transaction_info_carries_confirmations_and_the_threshold():
    res = from_dict(
        TransactionHistoryResponse,
        {
            "items": [
                {
                    "uuid": "tx-1",
                    "status": "confirmed",
                    "tx_hash": "0xabc",
                    "confirmations": 14,
                    "required_confirmations": 12,
                },
                {
                    # Just executed, not in a block yet.
                    "uuid": "tx-2",
                    "status": "broadcasted",
                    "confirmations": 0,
                    "required_confirmations": 12,
                },
                {
                    # In a block and counting, short of the depth: still
                    # broadcasted, not confirmed.
                    "uuid": "tx-5",
                    "status": "broadcasted",
                    "confirmations": 5,
                    "required_confirmations": 12,
                },
                {
                    "uuid": "tx-3",
                    "status": "expired",
                    "confirmations": 0,
                    "required_confirmations": 1,
                },
            ]
        },
    )

    assert res.items is not None
    confirmed, pending, in_block, expired = res.items
    assert confirmed.status == TxStatus.CONFIRMED.value
    assert (confirmed.confirmations, confirmed.required_confirmations) == (14, 12)
    assert (pending.confirmations, pending.required_confirmations) == (0, 12)
    assert in_block.status == TxStatus.BROADCASTED.value
    assert (in_block.confirmations, in_block.required_confirmations) == (5, 12)
    assert in_block.confirmations is not None and in_block.required_confirmations is not None
    assert 0 < in_block.confirmations < in_block.required_confirmations
    assert not is_transaction_terminal(in_block.status)
    assert (expired.confirmations, expired.required_confirmations) == (0, 1)

    # A server that predates the fields sends neither; that reads as unknown,
    # not as a zero threshold.
    legacy = from_dict(TransactionInfo, {"uuid": "tx-4", "status": "signed"})
    assert legacy.confirmations is None
    assert legacy.required_confirmations is None


def test_payout_statuses_include_the_in_flight_names_the_api_sends():
    for name in (
        "queue",
        "refueling",
        "refuel_confirmed",
        "sending",
        "broadcasting",
        "in_mempool",
        "confirm_check",
    ):
        assert not is_payout_terminal(PayoutStatus(name).value)
    for name in ("paid", "system_fail"):
        assert is_payout_terminal(PayoutStatus(name).value)


def test_payout_wait_defaults_to_90_minutes():
    # paid waits for the network's finality depth: about 60 minutes on BCH alone.
    assert inspect.signature(PayoutsService.wait_for).parameters["timeout"].default == 5400.0
