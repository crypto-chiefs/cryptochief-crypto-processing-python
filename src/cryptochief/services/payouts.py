"""Single and mass payout endpoints (including auto-convert swaps)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from .._models import from_dict
from ..assets import AssetsPolicy
from ..pagination import HistoryMeta, HistoryQuery
from ..poll import wait_for_terminal
from .base import BaseService


class PayoutStatus(str, Enum):
    QUEUE = "queue"
    PROCESS = "process"
    PAID = "paid"
    FAILED = "failed"
    SYSTEM_FAIL = "system_fail"
    EXPIRED = "expired"
    CANCEL = "cancel"


_PAYOUT_TERMINAL = frozenset({"paid", "failed", "system_fail", "expired", "cancel"})


def is_payout_terminal(status: str) -> bool:
    """Whether a payout status is final (no further transitions)."""
    return status in _PAYOUT_TERMINAL


@dataclass(kw_only=True)
class EstimatePayoutRequest:
    network: str
    coin: str
    amount: str
    to_address: str
    from_addresses: Optional[List[str]] = None
    allow_multiple_sources: Optional[bool] = None
    auto_convert: Optional[bool] = None
    auto_convert_policy: Optional[AssetsPolicy] = None
    max_fee_amount_fiat: Optional[str] = None
    memo: Optional[str] = None


@dataclass(kw_only=True)
class ExecutePayoutRequest(EstimatePayoutRequest):
    """``order_id`` is the idempotency key - resubmitting returns the same ``uuid``."""

    order_id: str
    user_id: str
    url_callback: str


@dataclass(kw_only=True)
class PayoutFeeInfo:
    fee_mode: Optional[str] = None
    estimated_fiat: Optional[str] = None
    estimated_coin: Optional[str] = None
    estimated_asset: Optional[str] = None


@dataclass(kw_only=True)
class PayoutSource:
    address: Optional[str] = None
    amount: Optional[str] = None
    coin: Optional[str] = None


@dataclass(kw_only=True)
class EstimatePayoutResponse:
    network: Optional[str] = None
    coin: Optional[str] = None
    amount: Optional[str] = None
    amount_to_receive: Optional[str] = None
    to_address: Optional[str] = None
    fee_info: Optional[PayoutFeeInfo] = None
    sources: Optional[List[PayoutSource]] = None
    service_operations: Optional[List[Dict[str, Any]]] = None
    auto_convert_applied: Optional[bool] = None


@dataclass(kw_only=True)
class PayoutInfo:
    uuid: str = ""
    status: str = ""
    order_id: Optional[str] = None
    network: Optional[str] = None
    coin: Optional[str] = None
    amount: Optional[str] = None
    to_address: Optional[str] = None
    txid: Optional[str] = None
    sources: Optional[List[PayoutSource]] = None
    url_callback: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    error: Optional[str] = None


@dataclass(kw_only=True)
class BatchPayoutRequest:
    """Batch body for ``/payout/batch/{estimate,execute}``. Up to 50 items per call."""

    items: List[ExecutePayoutRequest]
    url_callback: Optional[str] = None


@dataclass(kw_only=True)
class BatchItemResult:
    index: int = 0
    order_id: Optional[str] = None
    status: Optional[str] = None
    uuid: Optional[str] = None
    error: Optional[str] = None


@dataclass(kw_only=True)
class BatchPayoutResponse:
    total: int = 0
    accepted: int = 0
    rejected: int = 0
    items: Optional[List[BatchItemResult]] = None
    batch_uuid: Optional[str] = None


@dataclass(kw_only=True)
class PayoutHistoryResponse:
    items: Optional[List[PayoutInfo]] = None
    meta: Optional[HistoryMeta] = None


class PayoutsService(BaseService):
    async def estimate(self, req: EstimatePayoutRequest) -> EstimatePayoutResponse:
        """Preview fees and selected source(s) without locking funds."""
        return from_dict(EstimatePayoutResponse, await self._post("/v1/payout/estimate", req))

    async def execute(self, req: ExecutePayoutRequest) -> PayoutInfo:
        """Create and dispatch a payout. Funds lock immediately; idempotent on ``order_id``."""
        return from_dict(PayoutInfo, await self._post("/v1/payout/execute", req))

    async def info(self, uuid: str) -> PayoutInfo:
        """Fetch the current state of one payout by uuid."""
        return from_dict(PayoutInfo, await self._post("/v1/payout/info", {"uuid": uuid}))

    async def history(self, query: Optional[HistoryQuery] = None) -> PayoutHistoryResponse:
        """Paged list of payouts matching the filter."""
        return from_dict(
            PayoutHistoryResponse, await self._post("/v1/payout/history", query or HistoryQuery())
        )

    async def batch_estimate(self, req: BatchPayoutRequest) -> BatchPayoutResponse:
        """Preview fees for up to 50 payouts in one call."""
        return from_dict(BatchPayoutResponse, await self._post("/v1/payout/batch/estimate", req))

    async def batch_execute(self, req: BatchPayoutRequest) -> BatchPayoutResponse:
        """Create up to 50 payouts in one call.

        Bad items return their code in ``items[].error`` without blocking the
        rest; funds lock sequentially so an intra-batch double-spend cannot occur.
        """
        return from_dict(BatchPayoutResponse, await self._post("/v1/payout/batch/execute", req))

    async def wait_for(
        self, uuid: str, *, interval: float = 5.0, timeout: float = 600.0
    ) -> PayoutInfo:
        """Poll ``info`` until the payout reaches a terminal state (or timeout)."""

        async def fetch() -> PayoutInfo:
            return await self.info(uuid)

        return await wait_for_terminal(
            fetch, lambda p: is_payout_terminal(p.status), interval=interval, timeout=timeout
        )
