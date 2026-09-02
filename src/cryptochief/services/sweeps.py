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
    """Filter for the two sweep-history endpoints. Unset fields are not sent.

    Every field narrows the result; none of them is required. Leaving ``status``
    unset includes every status, ``SKIPPED`` ones among them - a wallet whose
    balance never cleared its threshold shows up there rather than nowhere.
    """

    #: ``auto`` or ``force`` (:class:`SweepMode`). All modes when unset.
    mode: Optional[str] = None
    #: One :class:`SweepStatus`. Every status when unset.
    status: Optional[str] = None
    #: Substring match. On :meth:`SweepsService.history` it matches the wallet
    #: address, the sweep or gas-pump transaction hash, and the ``task_id``; on
    #: :meth:`SweepsService.wallet_history`, where the wallet is already fixed,
    #: the hashes and the ``task_id``.
    search: Optional[str] = None
    page: Optional[int] = None
    page_size: Optional[int] = None


class SweepStatus(str, Enum):
    """A sweep is broadcast first and confirmed after.

    ``BROADCASTED`` means the transaction is out and not yet confirmed;
    ``COMPLETED`` means the chain confirmed it. The platform used to report
    ``completed`` at broadcast, so a sweep could read as settled while its
    transaction was still unconfirmed or had been dropped. ``COMPLETED``
    together with a ``sweep_confirmations`` above zero is the settlement signal;
    ``Sweep.completed_at`` is not one, since it is stamped at every terminal
    outcome, ``FAILED`` included.

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
    """Who covers a sweep's gas when the deposit wallet cannot.

    A deposit wallet that already holds enough of the chain's native coin pays
    for its own transfer whatever the mode; these only decide who covers the
    shortfall.

    ``CLIENT`` takes it from your own master wallet, ``SERVICE`` from the
    platform - **and bills the cost to your API credits** - and ``MIX``, the
    platform default, tries ``CLIENT`` first and falls back to ``SERVICE`` when
    the master wallet cannot cover it.
    """

    CLIENT = "client"
    SERVICE = "service"
    MIX = "mix"


class SweepGasSource(str, Enum):
    """What is bought for a TRON sweep's energy. TRON only - carried and
    ignored on every other chain.

    ``NATIVE`` burns the wallet's own TRX for the energy the transfer needs.
    ``RENTED`` has the platform supply the energy instead, so nothing is burnt;
    the energy is billed to your API credits after the transfer is on chain,
    whatever the ``fee_mode``.

    This answers *what is bought* where :class:`SweepFeeMode` answers *who
    covers the network fees*, and the two are independent - energy can be
    supplied under any fee mode.

    **Not setting it is not the same as setting** ``NATIVE``. A wallet that has
    never chosen a gas source gets the platform default, which is ``RENTED`` -
    so energy is supplied, and billed, without anybody having switched it on.
    Send ``NATIVE`` explicitly to have the wallet burn its own TRX, and read
    ``settings().effective.gas_source`` to see what will actually happen.
    """

    NATIVE = "native"
    RENTED = "rented"


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

    #: Confirmations seen on the sweep transaction. **This** is the settlement
    #: signal: above zero means the chain has the sweep.
    sweep_confirmations: Optional[int] = None
    #: When the sweep reached a terminal outcome - **failures included**. The
    #: sweeper stamps it at every ending, not only a successful one, so its
    #: presence says the task finished and nothing about whether the money
    #: moved: a ``failed`` sweep carries one too. Absent while still in flight,
    #: which is why reading it as "present therefore settled" books a failed
    #: sweep as money received.
    #:
    #: To tell settlement apart, check ``sweep_confirmations`` is above zero, or
    #: take ``confirmed_at`` from the sweep webhook
    #: (:class:`~cryptochief.SweepWebhookEvent`) - it carries a separate
    #: timestamp for exactly this reason.
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
    #: Who covers a gas shortfall - a :class:`SweepFeeMode` value. A wallet
    #: holding enough native coin pays for itself regardless; the platform
    #: default here is ``mix``, and ``service`` bills your API credits.
    fee_mode: str = ""
    #: What is bought for a TRON sweep's energy - a :class:`SweepGasSource`.
    #: Always a concrete value on a resolved policy: on ``effective`` it is what
    #: will actually happen, and a wallet that chose nothing reads ``rented``,
    #: the platform default, not "off". A ``null`` belongs to the override layer
    #: (:class:`SweepOverride`), where it means the layer does not decide.
    gas_source: str = ""
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
    #: ``None`` here means this layer does not decide the gas source - the value
    #: is inherited, **not** switched off. The wallet still gets one, and if
    #: nothing anywhere chose it that one is ``rented``: energy supplied and
    #: billed to your credits. ``effective.gas_source`` is where you read what
    #: will actually happen.
    gas_source: Optional[str] = None
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
        """Recent sweeps across the whole project.

        Filter with :class:`SweepHistoryQuery` - by ``mode``, by a single
        ``status``, or by a ``search`` substring that matches the wallet
        address, the sweep or gas-pump transaction hash, or the ``task_id``.
        Unset means unfiltered, so an unset ``status`` includes the ``skipped``
        sweeps too.
        """
        return from_dict(
            SweepHistoryResponse, await self._post("/v1/sweeps/history", query or SweepHistoryQuery())
        )

    async def wallet_history(
        self, address: str, query: Optional[SweepHistoryQuery] = None
    ) -> SweepHistoryResponse:
        """Recent sweeps scoped to one wallet.

        Takes the same :class:`SweepHistoryQuery` as :meth:`history`, except
        that ``search`` has no address to match here - the wallet is already
        fixed - so it matches the sweep or gas-pump transaction hash and the
        ``task_id``.
        """
        body: dict[str, Any] = {"address": address}
        if query is not None:
            if query.mode is not None:
                body["mode"] = query.mode
            if query.status is not None:
                body["status"] = query.status
            if query.search is not None:
                body["search"] = query.search
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

        ``effective.gas_source`` is the one to read for TRON: it is always a
        concrete value, where a ``None`` on ``override.gas_source`` says only
        that the wallet does not decide it. A wallet nobody set it on resolves
        to ``rented`` - the platform supplies the energy and bills your credits.

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
        gas_source: Union[str, Clear, None] = None,
    ) -> SweepSettings:
        """Write a wallet's auto-sweep policy.

        Returns the settings as they stand afterwards, so the caller sees what
        the write resolved to without asking again.

        ``None`` leaves a field alone. :data:`~cryptochief.CLEAR` stops
        overriding it and goes back to inheriting - the only way to drop one
        field while keeping the others. The API expresses that by naming the
        field in ``fields`` with no value, which ``None`` cannot say in Python
        because it already means "not supplied". ``type_work``,
        ``threshold_amount_usd``, ``fee_mode`` and ``gas_source`` all accept it.

        ``gas_source`` is TRON-only (:class:`SweepGasSource`) and worth being
        deliberate about: leaving it ``None`` here is **not** the same as
        writing ``"native"``. It leaves whatever is stored, and a wallet with
        nothing stored falls back to the platform default ``"rented"`` - the
        platform supplies the energy and bills it to your API credits, with
        nobody having switched it on. Send ``SweepGasSource.NATIVE`` explicitly
        to have the wallet burn its own TRX instead, and pass ``CLEAR`` to drop
        the override and inherit again (which lands back on the default, not on
        ``native``).

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
            ("gas_source", gas_source),
        ):
            if value is None:
                continue
            fields.append(name)
            if not isinstance(value, Clear):
                body[name] = value.value if isinstance(value, Enum) else value
        if fields:
            body["fields"] = fields

        return from_dict(SweepSettings, await self._post("/v1/sweeps/settings/update", body))
