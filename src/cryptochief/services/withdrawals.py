"""Read-only withdrawal endpoints.

The public API does not create withdrawals directly - they are produced by the
sweep/treasury system.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .._models import from_dict
from ..pagination import HistoryMeta, HistoryQuery
from .base import BaseService


@dataclass(kw_only=True)
class Withdrawal:
    uuid: str = ""
    status: str = ""
    network: Optional[str] = None
    coin: Optional[str] = None
    contract: Optional[str] = None
    amount: Optional[str] = None
    amount_fiat: Optional[str] = None
    from_address: Optional[str] = None
    to_address: Optional[str] = None
    tx_hash: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    confirmed_at: Optional[str] = None
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
