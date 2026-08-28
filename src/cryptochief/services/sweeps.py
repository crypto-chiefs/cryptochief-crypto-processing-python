"""Treasury sweeps (transit -> master)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, List, Optional, Union

from .._models import from_dict
from ..sentinels import Clear
from ..pagination import HistoryMeta
from .base import BaseService


class SweepMode(str, Enum):
    AUTO = "auto"
    FORCE = "force"


@dataclass(kw_only=True)
class SweepHistoryQuery:
    mode: Optional[str] = None
    page: Optional[int] = None
    page_size: Optional[int] = None


class SweepStatus(str, Enum):
    """A sweep is broadcast first and confirmed after.

    ``BROADCASTED`` means the transaction is out and not yet confirmed;
    ``COMPLETED`` means the chain confirmed it. The platform used to report
    ``completed`` at broadcast, so a sweep could read as settled while its
    transaction was still unconfirmed or had been dropped.

    ``SKIPPED`` is a sweep the platform decided against - almost always a
    balance below the wallet's threshold. A normal outcome, not a failure.
    """

    PENDING = "pending"
    WAITING_GAS = "waiting_gas"
    BROADCASTED = "broadcasted"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class SweepPolicyMode(str, Enum):
    """Auto-sweep modes.

    ``OFF`` is never swept on its own (:meth:`SweepsService.force` still works),
    ``MOMENTUM`` sweeps as soon as funds arrive, and ``THRESHOLD`` sweeps once
    the balance reaches ``threshold_amount_usd``. A held balance is re-checked
    periodically, so a wallet that crosses the threshold through price movement
    alone is still swept.
    """

    OFF = "turned_off"
    MOMENTUM = "momentum"
    THRESHOLD = "threshold"


class SweepFeeMode(str, Enum):
    """Who pays the gas for a sweep.

    ``CLIENT`` takes it from the swept wallet, ``SERVICE`` from the platform's
    service wallet, and ``MIX`` funds the gas from the service wallet and
    reclaims the cost from the sweep.
    """

    CLIENT = "client"
    SERVICE = "service"
    MIX = "mix"


@dataclass(kw_only=True)
class Sweep:
    task_id: str = ""
    status: str = ""
    sweep_tx_hash: Optional[str] = None
    gas_pump_tx_hash: Optional[str] = None
    wallet_address: Optional[str] = None
    chain: Optional[str] = None
    chain_family: Optional[str] = None
    asset_symbol: Optional[str] = None
    asset_type: Optional[str] = None
    amount_human: Optional[str] = None
    #: What triggered this sweep: momentum, threshold or force.
    type_work: Optional[str] = None

    #: Confirmations seen on the sweep transaction, and when it reached the
    #: network's confirmation target. Read them with ``status``:
    #: ``completed_at`` is absent while the sweep is still in flight.
    sweep_confirmations: Optional[int] = None
    completed_at: Optional[str] = None

    #: Fees. ``total_fee_usd`` is the whole cost of the sweep; the gas-pump half
    #: is the funding transfer that pays for it on chains needing one. The
    #: ``real_*`` figures are what the chain actually charged, filled in once the
    #: transaction settles; the others are the estimate made up front.
    total_fee_usd: Optional[str] = None
    gas_pump_source: Optional[str] = None
    gas_pump_fee_human: Optional[str] = None
    gas_pump_fee_usd: Optional[str] = None
    sweep_fee_human: Optional[str] = None
    sweep_fee_usd: Optional[str] = None
    real_gas_pump_fee_human: Optional[str] = None
    real_gas_pump_fee_usd: Optional[str] = None
    real_sweep_fee_human: Optional[str] = None
    real_sweep_fee_usd: Optional[str] = None

    created_at: Optional[str] = None

    #: Deprecated: never populated. The API reports fees under the names above;
    #: these were guesses at a shape it does not send.
    gas_fee_human: Optional[str] = None
    gas_fee_fiat: Optional[str] = None
    service_fee_fiat: Optional[str] = None
    #: Deprecated: never populated - sweeps carry ``created_at`` and
    #: ``completed_at``.
    updated_at: Optional[str] = None


@dataclass(kw_only=True)
class SweepPolicy:
    """A resolved set of sweep rules."""

    type_work: str = ""
    #: Meaningful only when ``type_work`` is ``threshold``.
    threshold_amount_usd: Optional[str] = None
    fee_mode: str = ""
    #: Which layer the mode came from: ``wallet_network``, ``wallet``,
    #: ``project`` or ``default``. Present on the effective policy, where the
    #: question arises.
    source: Optional[str] = None


@dataclass(kw_only=True)
class SweepOverride:
    """What one wallet decides for itself.

    A field of ``None`` is not overridden - it is inherited, which no ordinary
    value can express.
    """

    #: Empty covers the address on every network it exists on; set, it covers
    #: that one network and takes precedence over the address-wide override.
    network_code: Optional[str] = None
    type_work: Optional[str] = None
    threshold_amount_usd: Optional[str] = None
    fee_mode: Optional[str] = None
    #: Who wrote it: ``merchant`` or ``operator``.
    source: Optional[str] = None
    #: An operator pinned this policy. While it is set, a merchant write answers
    #: ``SWEEP_SETTINGS_LOCKED`` and changes nothing.
    locked: bool = False


@dataclass(kw_only=True)
class SweepSettings:
    """Three layers, on purpose.

    ``effective`` is what will actually happen, ``override`` is what this wallet
    decides for itself (``None`` if it decides nothing), and ``project_default``
    is what it falls back to. Only the three together answer "is this value mine
    or inherited" - the difference between changing it here and changing it on
    the project. Inheritance is per field: a wallet can override the mode and
    keep inheriting the fee mode.
    """

    wallet_address: Optional[str] = None
    network_code: Optional[str] = None
    effective: Optional[SweepPolicy] = None
    override: Optional[SweepOverride] = None
    project_default: Optional[SweepPolicy] = None


@dataclass(kw_only=True)
class SweepHistoryResponse:
    items: Optional[List[Sweep]] = None
    meta: Optional[HistoryMeta] = None


@dataclass(kw_only=True)
class ForceSweepResponse:
    status: str = ""


class SweepsService(BaseService):
    async def force(self, address: str, network: str) -> ForceSweepResponse:
        """Trigger an immediate transit->master sweep for one address.

        The status acknowledges acceptance; the resulting :class:`Sweep` record
        appears via :meth:`wallet_history` once the on-chain tx is built.
        """
        return from_dict(
            ForceSweepResponse,
            await self._post("/v1/sweeps/force", {"address": address, "network_code": network}),
        )

    async def history(self, query: Optional[SweepHistoryQuery] = None) -> SweepHistoryResponse:
        """Recent sweeps across the whole project."""
        return from_dict(
            SweepHistoryResponse, await self._post("/v1/sweeps/history", query or SweepHistoryQuery())
        )

    async def wallet_history(
        self, address: str, query: Optional[SweepHistoryQuery] = None
    ) -> SweepHistoryResponse:
        """Recent sweeps scoped to one wallet."""
        body: dict[str, Any] = {"address": address}
        if query is not None:
            if query.mode is not None:
                body["mode"] = query.mode
            if query.page is not None:
                body["page"] = query.page
            if query.page_size is not None:
                body["page_size"] = query.page_size
        return from_dict(SweepHistoryResponse, await self._post("/v1/sweeps/wallet/history", body))

    async def settings(
        self, address: Optional[str] = None, network_code: Optional[str] = None
    ) -> SweepSettings:
        """The auto-sweep policy in force for one wallet.

        Returns what will happen, what the wallet overrides, and what it
        inherits. Omitting ``address`` asks for the project's own default rather
        than any wallet's policy.

        Scoped to the caller's own wallets: an address that is not the project's
        answers ``WALLET_NOT_FOUND``.
        """
        body: dict[str, Any] = {}
        if address:
            body["address"] = address
        if network_code:
            body["network_code"] = network_code
        return from_dict(SweepSettings, await self._post("/v1/sweeps/settings", body))

    async def update_settings(
        self,
        address: str,
        *,
        network_code: Optional[str] = None,
        type_work: Union[str, Clear, None] = None,
        threshold_amount_usd: Union[str, Clear, None] = None,
        fee_mode: Union[str, Clear, None] = None,
    ) -> SweepSettings:
        """Write a wallet's auto-sweep policy.

        Returns the settings as they stand afterwards, so the caller sees what
        the write resolved to without asking again.

        ``None`` leaves a field alone. :data:`~cryptochief.CLEAR` stops
        overriding it and goes back to inheriting - the only way to drop one
        field while keeping the others. The API expresses that by naming the
        field with no value, which ``None`` cannot say in Python because it
        already means "not supplied".

        Refusals are named: ``TYPE_WORK_INVALID``, ``FEE_MODE_INVALID``,
        ``THRESHOLD_INVALID``, ``THRESHOLD_MUST_BE_POSITIVE``,
        ``THRESHOLD_REQUIRED_FOR_THRESHOLD_MODE``, and
        ``SWEEP_SETTINGS_LOCKED`` when an operator has pinned the policy.
        """
        body: dict[str, Any] = {"address": address}
        if network_code:
            body["network_code"] = network_code

        fields: List[str] = []
        for name, value in (
            ("type_work", type_work),
            ("threshold_amount_usd", threshold_amount_usd),
            ("fee_mode", fee_mode),
        ):
            if value is None:
                continue
            fields.append(name)
            if not isinstance(value, Clear):
                body[name] = value.value if isinstance(value, Enum) else value
        if fields:
            body["fields"] = fields

        return from_dict(SweepSettings, await self._post("/v1/sweeps/settings/update", body))
