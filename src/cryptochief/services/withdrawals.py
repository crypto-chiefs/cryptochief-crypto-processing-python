"""Read-only withdrawal endpoints.

Withdrawals are started from the dashboard; the public API only reads them.
Withdrawals have no webhooks.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

from .._models import from_dict
from ..pagination import HistoryMeta, HistoryQuery
from .base import BaseService


class WithdrawalStatus(str, Enum):
    """Withdrawal status.

    - ``QUEUE`` - waiting to be processed.
    - ``REFUELING`` - gas top-up of the source wallet sent.
    - ``REFUEL_CONFIRMED`` - top-up confirmed or not needed.
    - ``BROADCASTING`` - waiting to reach the network (EVM networks).
    - ``SENDING`` - withdrawal transaction being sent.
    - ``IN_MEMPOOL`` - in the mempool, not in a block (BTC-family networks).
    - ``CONFIRM_CHECK`` - sent; waiting for ``required_confirmations``.
    - ``COMPLETED`` - reached ``required_confirmations``. Final.
    - ``FAILED`` - did not go through; see ``error_reason``. Final.
    - ``CANCELLED`` - deprecated: not produced by the API.
    """

    QUEUE = "queue"
    REFUELING = "refueling"
    REFUEL_CONFIRMED = "refuel_confirmed"
    BROADCASTING = "broadcasting"
    SENDING = "sending"
    IN_MEMPOOL = "in_mempool"
    CONFIRM_CHECK = "confirm_check"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(kw_only=True)
class Withdrawal:
    uuid: str = ""
    #: One :class:`WithdrawalStatus`.
    status: str = ""
    network: Optional[str] = None
    coin: Optional[str] = None
    amount: Optional[str] = None
    from_address: Optional[str] = None
    to_address: Optional[str] = None
    #: Whether the source wallet needed a gas top-up before the withdrawal.
    need_refuel: Optional[bool] = None
    #: Hash of the gas top-up transaction, when there was one.
    refuel_tx_hash: Optional[str] = None
    #: Progress of the gas top-up, when there was one.
    refuel_status: Optional[str] = None
    #: Hash of the withdrawal transaction; absent until sent.
    tx_hash: Optional[str] = None
    #: Why the withdrawal is ``failed``.
    error_reason: Optional[str] = None
    #: Confirmations of the withdrawal transaction; absent until it is in a block.
    confirmations: Optional[int] = None
    #: Confirmations needed to turn ``completed``.
    required_confirmations: Optional[int] = None
    #: Estimated network fee in USD, at creation.
    estimated_fee_fiat: Optional[str] = None
    #: Network fee paid in USD, gas top-up included; set on ``completed``.
    actual_fee_fiat: Optional[str] = None
    #: Who covered the gas: ``client``, ``service`` or ``mix``.
    fee_mode: Optional[str] = None
    created_at: Optional[str] = None
    #: When the withdrawal turned ``completed``.
    completed_at: Optional[str] = None

    # Not sent by the API; always None.
    contract: Optional[str] = None
    amount_fiat: Optional[str] = None
    updated_at: Optional[str] = None
    #: Always ``None``; read ``completed_at``.
    confirmed_at: Optional[str] = None
    #: Always ``None``; read ``error_reason``.
    error: Optional[str] = None


@dataclass(kw_only=True)
class WithdrawalHistoryResponse:
    items: Optional[List[Withdrawal]] = None
    meta: Optional[HistoryMeta] = None


class WithdrawalsService(BaseService):
    async def info(self, uuid: str) -> Withdrawal:
        """Fetch one withdrawal by uuid."""
        return from_dict(Withdrawal, await self._post("/v1/withdrawal/info", {"uuid": uuid}))

    async def history(self, query: Optional[HistoryQuery] = None) -> WithdrawalHistoryResponse:
        """Paged list of withdrawals."""
        return from_dict(
            WithdrawalHistoryResponse,
            await self._post("/v1/withdrawal/history", query or HistoryQuery()),
        )
