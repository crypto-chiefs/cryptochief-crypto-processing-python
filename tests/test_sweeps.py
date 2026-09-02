"""Auto-sweep settings, the gas source, and the honest broadcast/confirm status.

Covers the wire shapes of ``/v1/sweeps/settings`` and
``/v1/sweeps/settings/update`` - in particular the difference between leaving a
field alone, writing it, and clearing it, and the difference between a ``null``
``gas_source`` on an override layer (this layer does not decide) and the
concrete one on the effective layer (what will actually happen) - plus the
history filters and that a sweep still in flight is distinguishable from one the
chain has confirmed.
"""

import json

import httpx

from cryptochief import (
    CLEAR,
    CreatePayInRequest,
    CryptoChiefClient,
    Environment,
    SweepGasSource,
    SweepHistoryQuery,
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
        "gas_source": "native",
        "source": "wallet",
    },
    "override": {
        "network_code": "",
        "type_work": "threshold",
        "threshold_amount_usd": "250",
        "fee_mode": None,
        "gas_source": None,
        "source": "merchant",
        "locked": False,
    },
    "project_default": {"type_work": "momentum", "fee_mode": "client", "gas_source": "native"},
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


async def test_a_null_gas_source_on_the_override_is_not_a_value():
    captured: dict = {}
    client = _client(captured, SETTINGS_RESPONSE)

    out = await client.sweeps.settings(address="0xabc")

    assert out.override is not None
    # "This layer does not decide" - inherited, NOT switched off. Reading it as
    # a value would say the wallet chose to burn its own TRX, which it did not.
    assert out.override.gas_source is None
    # What will actually happen is only knowable from the effective layer, and
    # there it is always concrete.
    assert out.effective is not None
    assert out.effective.gas_source == SweepGasSource.NATIVE.value
    assert out.project_default is not None
    assert out.project_default.gas_source == "native"


async def test_an_unset_gas_source_resolves_to_the_rented_default():
    captured: dict = {}
    # Nobody ever chose one: the override says nothing and the effective layer
    # reports the platform default, which supplies energy and bills credits.
    client = _client(
        captured,
        {
            "wallet_address": "TQrY",
            "network_code": "TRON_MAINNET",
            "effective": {
                "type_work": "momentum",
                "fee_mode": "mix",
                "gas_source": "rented",
                "source": "default",
            },
            "override": None,
            "project_default": {"type_work": "momentum", "fee_mode": "mix", "gas_source": "rented"},
        },
    )

    out = await client.sweeps.settings(address="TQrY")

    assert out.override is None
    assert out.effective is not None
    assert out.effective.gas_source == SweepGasSource.RENTED.value
    assert out.effective.source == "default"


async def test_update_sends_gas_source_only_when_it_is_given():
    captured: dict = {}
    client = _client(captured, SETTINGS_RESPONSE)

    await client.sweeps.update_settings("TQrY", gas_source=SweepGasSource.NATIVE)

    body = _body(captured)
    assert body["gas_source"] == "native"
    assert body["fields"] == ["gas_source"]

    # Not naming it leaves the stored value alone - which is not the same as
    # writing "native": a wallet with nothing stored keeps the rented default.
    captured2: dict = {}
    client2 = _client(captured2, SETTINGS_RESPONSE)
    await client2.sweeps.update_settings("TQrY", type_work=SweepPolicyMode.MOMENTUM)
    body2 = _body(captured2)
    assert "gas_source" not in body2
    assert body2["fields"] == ["type_work"]


async def test_clearing_gas_source_names_it_in_the_fields_mask_with_no_value():
    captured: dict = {}
    client = _client(captured, SETTINGS_RESPONSE)

    await client.sweeps.update_settings("TQrY", fee_mode="mix", gas_source=CLEAR)

    body = _body(captured)
    # Naming it in the mask with no value is the only way to drop this one
    # override and keep the others; fee_mode goes out with its value intact.
    assert body["fields"] == ["fee_mode", "gas_source"]
    assert "gas_source" not in body
    assert body["fee_mode"] == "mix"


async def test_history_filters_reach_the_wire():
    captured: dict = {}
    client = _client(captured, {"items": [], "meta": {"page": 1, "page_size": 20, "total": 0}})

    await client.sweeps.history(
        SweepHistoryQuery(mode="force", status=SweepStatus.SKIPPED.value, search="0x6269")
    )

    body = _body(captured)
    assert str(captured["request"].url).endswith("/v1/sweeps/history")
    assert body["mode"] == "force"
    # An explicit status is the only way to see just the skipped sweeps; unset
    # includes every status, those among them.
    assert body["status"] == "skipped"
    assert body["search"] == "0x6269"

    captured2: dict = {}
    client2 = _client(captured2, {"items": [], "meta": {"page": 1, "page_size": 20, "total": 0}})
    await client2.sweeps.history()
    # Unfiltered means absent, not an empty string the server has to reject.
    assert _body(captured2) == {}


async def test_wallet_history_filters_reach_the_wire_alongside_the_address():
    captured: dict = {}
    client = _client(captured, {"items": [], "meta": {"page": 1, "page_size": 20, "total": 0}})

    await client.sweeps.wallet_history(
        "0xabc",
        SweepHistoryQuery(
            status=SweepStatus.COMPLETED.value, search="898cdbd0", page=2, page_size=50
        ),
    )

    body = _body(captured)
    assert str(captured["request"].url).endswith("/v1/sweeps/wallet/history")
    assert body == {
        "address": "0xabc",
        "status": "completed",
        "search": "898cdbd0",
        "page": 2,
        "page_size": 50,
    }


async def test_history_tells_a_broadcast_a_settled_and_a_failed_sweep_apart():
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
                {
                    "task_id": "t3",
                    "status": "failed",
                    "wallet_address": "0xc",
                    "chain": "ETH_MAINNET",
                    "sweep_confirmations": 0,
                    "completed_at": "2026-08-28T10:05:00Z",
                },
            ],
            "meta": {"total": 3, "page": 1, "page_size": 50},
        },
    )

    out = await client.sweeps.history()

    assert out.items is not None
    in_flight, settled, failed = out.items
    assert in_flight.status == SweepStatus.BROADCASTED.value
    assert in_flight.sweep_confirmations == 2
    # Absent only because the task has not ended yet.
    assert in_flight.completed_at is None
    assert in_flight.type_work == "threshold"
    assert in_flight.total_fee_usd == "1.20"
    assert settled.status == SweepStatus.COMPLETED.value
    assert settled.completed_at == "2026-08-28T10:00:00Z"
    assert settled.real_sweep_fee_usd == "0.98"

    # completed_at is stamped at every terminal outcome, failures included, so
    # a failed sweep carries one exactly like the settled one - reading its
    # presence as "settled" books this as money received. sweep_confirmations
    # is what separates them.
    assert failed.status == SweepStatus.FAILED.value
    assert failed.completed_at == "2026-08-28T10:05:00Z"
    assert failed.sweep_confirmations == 0
    assert (settled.sweep_confirmations or 0) > 0


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
