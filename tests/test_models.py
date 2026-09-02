"""The dataclass <-> wire helpers: serialization drops None, parsing tolerates extras."""

from cryptochief import (
    AssetsPolicy,
    Asset,
    Chain,
    CryptoCurrencies,
    EstimatePayoutRequest,
    EstimatePayoutResponse,
    ExecutePayoutRequest,
)
from cryptochief._models import from_dict, to_payload


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
            "sources": [{"address": "0xabc", "amount": "0.01"}],
            "some_future_field": {"nested": 1},  # unknown -> ignored
        },
    )
    assert res.amount_to_receive == "0.0099"
    assert res.fee_info.fee_mode == "service"
    assert res.sources[0].address == "0xabc"
    assert not hasattr(res, "some_future_field")


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
