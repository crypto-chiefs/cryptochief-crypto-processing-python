"""Read-only on-chain queries: enabled assets, balances, tx status."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional

from .._models import from_dict
from .base import BaseService


@dataclass(kw_only=True)
class AvailableContract:
    network: Optional[str] = None
    coin: Optional[str] = None
    contract: Optional[str] = None
    type: Optional[str] = None  # "native" or "token"
    decimals: int = 0


@dataclass(kw_only=True)
class AvailableContractsResponse:
    items: Optional[List[AvailableContract]] = None


@dataclass(kw_only=True)
class WalletBalanceRow:
    address: str = ""
    value: Optional[str] = None
    human_value: Optional[str] = None
    decimals: int = 0
    contract: Optional[str] = None


@dataclass(kw_only=True)
class TxStatusRow:
    confirmations: int = 0
    fee: Optional[str] = None
    human_fee: Optional[str] = None
    block_number: Optional[int] = None
    status: Optional[str] = None


class BlockchainService(BaseService):
    async def contracts_available(
        self, network: Optional[str] = None
    ) -> AvailableContractsResponse:
        """Coins/tokens this project may use.

        Pass a ``network`` to scope to one chain, or omit for the full set. Each
        row's ``decimals`` is what ``human_to_base`` / ``base_to_human`` need.
        """
        body = {"network": network} if network else {}
        return from_dict(
            AvailableContractsResponse, await self._post("/v1/blockchain/contracts/available", body)
        )

    async def wallet_balance(
        self,
        chain: str,
        addresses: List[str],
        contracts: Optional[List[str]] = None,
    ) -> List[WalletBalanceRow]:
        """Native + token balances for one or more addresses."""
        body: dict[str, Any] = {"chain": chain, "addresses": addresses}
        if contracts:
            body["contracts"] = contracts
        raw = await self._post("/v1/blockchain/wallet/balance", body)
        return [from_dict(WalletBalanceRow, r) for r in (raw or [])]

    async def transaction_status(self, chain: str, tx_hash: str) -> List[TxStatusRow]:
        """Current on-chain state of a transaction by hash."""
        raw = await self._post(
            "/v1/blockchain/transaction/status", {"chain": chain, "hash": tx_hash}
        )
        return [from_dict(TxStatusRow, r) for r in (raw or [])]
