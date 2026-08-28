"""Auto-sweep settings and the honest broadcast/confirm status.

Covers the wire shapes of ``/v1/sweeps/settings`` and
``/v1/sweeps/settings/update`` - in particular the difference between leaving a
field alone, writing it, and clearing it - and that a sweep still in flight is
distinguishable from one the chain has confirmed.
"""

import json

import httpx

from cryptochief import (
    CLEAR,
    CreatePayInRequest,
    CryptoChiefClient,
    Environment,
    SweepPolicyMode,
    SweepStatus,
)

SETTINGS_RESPONSE = {
    "wallet_address": "0xabc",
    "network_code": "ETH_MAINNET",
    "effective": {
        "type_work": "threshold",
        "threshold_amount_usd": "250",
        "fee_mode": "mix",
        "source": "wallet",
    },
    "override": {
        "network_code": "",
        "type_work": "threshold",
        "threshold_amount_usd": "250",
        "fee_mode": None,
        "source": "merchant",
        "locked": False,
    },
    "project_default": {"type_work": "momentum", "fee_mode": "client"},
}


def _client(captured: dict, payload: dict) -> CryptoChiefClient:
    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json=payload)

    return CryptoChiefClient(
        merchant_id="M1", api_key="secret", transport=httpx.MockTransport(handler)
    )


def _body(captured: dict) -> dict:
    return json.loads(captured["request"].content.decode())


async def test_settings_returns_three_distinguishable_layers():
    captured: dict = {}
    client = _client(captured, SETTINGS_RESPONSE)

    out = await client.sweeps.settings(address="0xabc")

    assert str(captured["request"].url).endswith("/v1/sweeps/settings")
    assert out.effective is not None
    assert out.effective.type_work == SweepPolicyMode.THRESHOLD.value
    assert out.effective.threshold_amount_usd == "250"
    assert out.effective.source == "wallet"
    # An inherited field reads as None on the override while the effective
    # policy still has a value. That difference is the point of the shape.
    assert out.override is not None
    assert out.override.fee_mode is None
    assert out.override.type_work == "threshold"
    assert out.project_default is not None
    assert out.project_default.type_work == SweepPolicyMode.MOMENTUM.value


async def test_update_writes_only_the_fields_it_was_given():
    captured: dict = {}
    client = _client(captured, SETTINGS_RESPONSE)

    await client.sweeps.update_settings(
        "0xabc", type_work=SweepPolicyMode.THRESHOLD, threshold_amount_usd="250"
    )

    body = _body(captured)
    assert str(captured["request"].url).endswith("/v1/sweeps/settings/update")
    assert body["type_work"] == "threshold"
    assert body["threshold_amount_usd"] == "250"
    # Sending fee_mode at all would rewrite it; untouched means absent.
    assert "fee_mode" not in body
    assert body["fields"] == ["type_work", "threshold_amount_usd"]


async def test_clear_names_the_field_and_sends_no_value():
    captured: dict = {}
    client = _client(captured, SETTINGS_RESPONSE)

    await client.sweeps.update_settings("0xabc", type_work=CLEAR)

    body = _body(captured)
    # The API's way of saying "inherit this again": named, with no value. None
    # cannot express it because it already means "not supplied".
    assert body["fields"] == ["type_work"]
    assert "type_work" not in body


async def test_history_tells_a_broadcast_sweep_from_a_settled_one():
    captured: dict = {}
    client = _client(
        captured,
        {
            "items": [
                {
                    "task_id": "t1",
                    "status": "broadcasted",
                    "wallet_address": "0xa",
                    "chain": "ETH_MAINNET",
                    "sweep_confirmations": 2,
                    "type_work": "threshold",
                    "total_fee_usd": "1.20",
                },
                {
                    "task_id": "t2",
                    "status": "completed",
                    "wallet_address": "0xb",
                    "chain": "ETH_MAINNET",
                    "sweep_confirmations": 12,
                    "completed_at": "2026-08-28T10:00:00Z",
                    "real_sweep_fee_usd": "0.98",
                },
            ],
            "meta": {"total": 2, "page": 1, "page_size": 50},
        },
    )

    out = await client.sweeps.history()

    assert out.items is not None
    in_flight, settled = out.items
    assert in_flight.status == SweepStatus.BROADCASTED.value
    assert in_flight.sweep_confirmations == 2
    # Still in flight: there is no settlement moment to report yet.
    assert in_flight.completed_at is None
    assert in_flight.type_work == "threshold"
    assert in_flight.total_fee_usd == "1.20"
    assert settled.status == SweepStatus.COMPLETED.value
    assert settled.completed_at == "2026-08-28T10:00:00Z"
    assert settled.real_sweep_fee_usd == "0.98"


async def test_environment_reaches_the_wire_and_is_omitted_when_unset():
    captured: dict = {}
    client = _client(captured, {"uuid": "u1", "status": "pending"})

    await client.pay_ins.create(
        CreatePayInRequest(
            order_id="o1",
            user_id="u",
            mode="fiat",
            amount_fiat="10",
            currency="USD",
            environment=Environment.TESTNET.value,
        )
    )
    assert _body(captured)["environment"] == "testnet"

    captured2: dict = {}
    client2 = _client(captured2, {"uuid": "u2", "status": "pending"})
    await client2.pay_ins.create(
        CreatePayInRequest(
            order_id="o2", user_id="u", mode="fiat", amount_fiat="10", currency="USD"
        )
    )
    # Unset must stay off the wire: an empty string is a value the platform has
    # to reject, not the "use the project default" the caller meant.
    assert "environment" not in _body(captured2)
