"""Read endpoints for deposits on per-customer static wallets."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

from .._models import from_dict
from ..pagination import HistoryMeta
from .base import BaseService


class StaticDepositStatus(str, Enum):
    IN_MEMPOOL = "in_mempool"
    CONFIRM_CHECK = "confirm_check"
    PAID = "paid"
    DROPPED = "dropped"
    REORGED = "reorged"


@dataclass(kw_only=True)
class StaticDeposit:
    uuid: str = ""
    status: str = ""
    network: Optional[str] = None
    chain_family: Optional[str] = None
    coin: Optional[str] = None
    contract: Optional[str] = None
    decimals: Optional[int] = None
    to_address: Optional[str] = None
    from_address: Optional[str] = None
    tx_hash: Optional[str] = None
    block_number: Optional[int] = None
    amount: Optional[str] = None
    amount_fiat: Optional[str] = None
    confirmations: Optional[int] = None
    required_confirmations: Optional[int] = None
    found_in_mempool: Optional[bool] = None
    log_type: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    confirmed_at: Optional[str] = None
    paid_at: Optional[str] = None


@dataclass(kw_only=True)
class StaticDepositHistoryQuery:
    address: Optional[str] = None
    status: Optional[str] = None
    coin: Optional[str] = None
    network: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    page: Optional[int] = None
    page_size: Optional[int] = None


@dataclass(kw_only=True)
class StaticDepositHistoryResponse:
    items: Optional[List[StaticDeposit]] = None
    meta: Optional[HistoryMeta] = None


class StaticDepositsService(BaseService):
    async def info(self, uuid: str) -> StaticDeposit:
        """Fetch one deposit by uuid."""
        return from_dict(StaticDeposit, await self._post("/v1/static-deposit/info", {"uuid": uuid}))

    async def history(
        self, query: Optional[StaticDepositHistoryQuery] = None
    ) -> StaticDepositHistoryResponse:
        """Paged list of static deposits."""
        return from_dict(
            StaticDepositHistoryResponse,
            await self._post("/v1/static-deposit/history", query or StaticDepositHistoryQuery()),
        )
