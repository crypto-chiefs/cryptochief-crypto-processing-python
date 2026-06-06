"""Treasury sweeps (transit -> master)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, List, Optional

from .._models import from_dict
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


@dataclass(kw_only=True)
class Sweep:
    task_id: str = ""
    status: str = ""
    sweep_tx_hash: Optional[str] = None
    wallet_address: Optional[str] = None
    chain: Optional[str] = None
    chain_family: Optional[str] = None
    asset_symbol: Optional[str] = None
    asset_type: Optional[str] = None
    amount_human: Optional[str] = None
    gas_fee_human: Optional[str] = None
    gas_fee_fiat: Optional[str] = None
    service_fee_fiat: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


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
