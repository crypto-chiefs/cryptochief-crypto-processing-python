"""Read-only on-chain queries: supported chains, assets, balances, tx status."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional

from .._models import from_dict
from .base import BaseService


@dataclass(kw_only=True)
class SupportedChain:
    """One chain the platform's scanner is currently connected to.

    Infrastructure-level information - which chains the platform can read blocks
    from right now - and not the project's asset catalogue. For what a project
    can be paid in, use :meth:`BlockchainService.contracts_available`.
    """

    #: The chain key, a :class:`~cryptochief.Chain` value (``"ETH_MAINNET"``).
    name: str = ""
    #: The protocol family the scanner reads the chain with, in the scanner's
    #: own lowercase vocabulary (``"evm"``, ``"tron"``, ``"solana"``). It is not
    #: the uppercase :class:`~cryptochief.ChainFamily` that ``chain_family``
    #: fields carry elsewhere in the API - use
    #: :func:`~cryptochief.chain_family` on ``name`` for that.
    type: str = ""


@dataclass(kw_only=True)
class AvailableContract:
    """One coin or token on one network.

    The same row shape on both asset endpoints - the project's enabled assets
    (:meth:`BlockchainService.contracts_available`) and the platform-wide
    catalogue (:meth:`BlockchainService.contracts_list`).
    """

    network: Optional[str] = None
    coin: Optional[str] = None
    #: The token contract address, and an **empty string** for a native coin -
    #: the API sends ``""`` rather than ``null``, so ``if row.contract:`` is the
    #: test for "this is a token".
    contract: Optional[str] = None
    #: The protocol family of ``network`` - a :class:`~cryptochief.ChainFamily`
    #: value (``"EVM"``, ``"TRON"``).
    chain_family: Optional[str] = None
    type: Optional[str] = None  # "native" or "token"
    #: The asset lives on a test network. See the project's environments - a
    #: project may be allowed mainnet, testnet or both.
    is_test: bool = False
    decimals: int = 0


@dataclass(kw_only=True)
class AvailableContractsResponse:
    """An ``items`` list of :class:`AvailableContract`.

    Returned by both asset endpoints, which differ in *which* assets they list
    rather than in the shape of a row.
    """

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
    async def supported_chains(self) -> List[SupportedChain]:
        """The chains the platform's scanner is connected to right now.

        ``/v1/blockchains/list``. Infrastructure, not entitlement: a chain here
        is one the platform can read blocks from, which is not the same as one
        this project may be paid in - that is
        :meth:`contracts_available`.

        The API answers with a bare JSON array rather than an ``items``
        envelope, so this returns a plain list. The order is not stable; sort it
        if you display it.

        An empty answer is an empty list. The service builds its result from a
        nil slice, so "no chains" reaches the wire as a literal ``null`` rather
        than ``[]`` - this returns ``[]`` for both, never ``None``, so the
        result is always safe to iterate.
        """
        raw = await self._post("/v1/blockchains/list", {})
        return [from_dict(SupportedChain, r) for r in (raw or [])]

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

    async def contracts_list(self) -> AvailableContractsResponse:
        """Every coin and token the platform supports, on every network.

        ``/v1/blockchain/contracts/list``. Platform-wide, so there is nothing to
        filter by project - use it to build a "which assets could we turn on"
        picker. What the project can actually be paid in *right now* is
        :meth:`contracts_available`, and that is the list governing orders,
        sweeps and payouts.

        Rows are :class:`AvailableContract`, the same shape both asset
        endpoints return.
        """
        return from_dict(
            AvailableContractsResponse, await self._post("/v1/blockchain/contracts/list", {})
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
