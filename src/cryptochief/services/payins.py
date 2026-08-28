"""Incoming-payment (invoice) endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

from .._models import from_dict
from ..assets import Asset, AssetsPolicy
from ..pagination import HistoryMeta, HistoryQuery
from ..poll import wait_for_terminal
from .base import BaseService


class PayInMode(str, Enum):
    """``fiat`` fixes a stable fiat price; ``crypto`` fixes the crypto amount."""

    FIAT = "fiat"
    CRYPTO = "crypto"


class PayInStatus(str, Enum):
    WAITING_ASSET_SELECT = "waiting_asset_select"
    PENDING = "pending"
    PROCESSING = "processing"
    PROCESS = "process"
    PAID = "paid"
    CANCEL = "cancel"
    EXPIRED = "expired"


_PAYIN_TERMINAL = frozenset({"paid", "cancel", "expired"})


def is_payin_terminal(status: str) -> bool:
    """Whether a pay-in status is final."""
    return status in _PAYIN_TERMINAL


class Environment(str, Enum):
    """The two environments an order can belong to.

    A project may be allowed one or both; asking for testnet on a project that
    does not permit it is refused with ``TESTNET_NOT_ALLOWED`` rather than
    quietly served on mainnet, and a value that is neither is
    ``ENVIRONMENT_INVALID`` rather than a silent fallback.
    """

    MAINNET = "mainnet"
    TESTNET = "testnet"


@dataclass(kw_only=True)
class CreatePayInRequest:
    order_id: str
    user_id: str
    mode: str
    to_address: Optional[str] = None
    #: Pin the transit deposit wallet of THIS order to the given master wallet of
    #: the project - the address the funds are swept to. The order's
    #: asset/network chain family must match the master wallet's; a foreign or
    #: mismatched address is rejected with 400. Omit for the project-default
    #: behaviour.
    master_wallet_address: Optional[str] = None
    #: Constrain the asset the platform PICKS for this order to the real chains
    #: or the test ones - ``Environment.MAINNET`` or ``Environment.TESTNET``.
    #: Omit to use the project's own default.
    #:
    #: It changes nothing when ``asset`` names a concrete network - that is the
    #: caller's choice. It matters in fiat mode and when the network is ``ANY``,
    #: where the platform selects the asset and an unconstrained pick could put
    #: a real payment on a test network.
    environment: Optional[str] = None
    lifetime_sec: Optional[int] = None
    url_callback: Optional[str] = None
    url_success: Optional[str] = None
    url_error: Optional[str] = None
    additional_data: Optional[str] = None
    accuracy_payment_percent: Optional[int] = None
    # FIAT mode.
    amount_fiat: Optional[str] = None
    currency: Optional[str] = None
    course_source: Optional[str] = None
    assets: Optional[AssetsPolicy] = None
    # CRYPTO mode.
    amount_crypto: Optional[str] = None
    asset: Optional[Asset] = None


@dataclass(kw_only=True)
class CoinOption:
    coin: Optional[str] = None
    network: Optional[str] = None
    chain_family: Optional[str] = None
    contract: Optional[str] = None


@dataclass(kw_only=True)
class PayIn:
    uuid: str = ""
    status: str = ""
    type: Optional[str] = None
    order_id: Optional[str] = None
    user_id: Optional[str] = None
    mode: Optional[str] = None
    amount_crypto: Optional[str] = None
    amount_fiat: Optional[str] = None
    currency: Optional[str] = None
    payment_coin: Optional[str] = None
    payment_network: Optional[str] = None
    to_address: Optional[str] = None
    coins: Optional[List[CoinOption]] = None
    payment_link: Optional[str] = None
    url_callback: Optional[str] = None
    url_success: Optional[str] = None
    url_error: Optional[str] = None
    additional_data: Optional[str] = None
    can_cancel: Optional[bool] = None
    expired_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass(kw_only=True)
class PayInHistoryResponse:
    items: Optional[List[PayIn]] = None
    meta: Optional[HistoryMeta] = None


@dataclass(kw_only=True)
class SelectAssetRequest:
    uuid: str
    coin: str
    network: str
    #: Pin the order's transit deposit wallet to the given project master
    #: wallet; see :class:`CreatePayInRequest`. A value here overrides one
    #: supplied at order create.
    master_wallet_address: Optional[str] = None


class PayInsService(BaseService):
    async def create(self, req: CreatePayInRequest) -> PayIn:
        """Open a new pay-in order."""
        return from_dict(PayIn, await self._post("/v1/payments/order/create", req))

    async def select_asset(self, req: SelectAssetRequest) -> PayIn:
        """Commit the customer's coin/network choice on a ``waiting_asset_select`` order."""
        return from_dict(PayIn, await self._post("/v1/payments/asset/select", req))

    async def reset_asset(self, uuid: str) -> PayIn:
        """Revert a pending order to ``waiting_asset_select`` (H2H only)."""
        return from_dict(PayIn, await self._post("/v1/payments/asset/reset", {"uuid": uuid}))

    async def cancel(self, uuid: str) -> PayIn:
        """Cancel an open order."""
        return from_dict(PayIn, await self._post("/v1/payments/order/cancel", {"uuid": uuid}))

    async def info(self, uuid: str) -> PayIn:
        """Fetch the current state of one pay-in by uuid."""
        return from_dict(PayIn, await self._post("/v1/payments/order/info", {"uuid": uuid}))

    async def history(self, query: Optional[HistoryQuery] = None) -> PayInHistoryResponse:
        """Paged list of pay-ins."""
        return from_dict(
            PayInHistoryResponse, await self._post("/v1/payments/history", query or HistoryQuery())
        )

    async def wait_for(self, uuid: str, *, interval: float = 5.0, timeout: float = 600.0) -> PayIn:
        """Poll ``info`` until the pay-in reaches a terminal state (or timeout)."""

        async def fetch() -> PayIn:
            return await self.info(uuid)

        return await wait_for_terminal(
            fetch, lambda p: is_payin_terminal(p.status), interval=interval, timeout=timeout
        )
