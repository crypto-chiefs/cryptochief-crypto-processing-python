"""Native-coin purchase: quote a purchase, place an order, read it back.

The platform sells the native coin of a network (TRX, ETH, BNB, SOL, TON, ...)
out of its own liquidity, sending it to any address - the merchant pays, the
recipient can be anyone. The price covers the coins at the current market
rate and the fee of the platform's own transfer, and it is billed in
credits - the same balance
:meth:`cryptochief.CreditsService.balance` reports and
:meth:`~cryptochief.CreditsService.topup` refills. ``quote`` is free of
charge; ``buy`` is synchronous - by the time it answers, the coins are sent or
the refusal reason is known.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .._models import from_dict
from ..errors import APIError, CryptoChiefError
from ..idempotency import current_idempotency_key
from .base import BaseService


class NativeOrderStatus(str, Enum):
    """Native-coin purchase order status."""

    #: Coins sent to ``receive_address``; ``tx_hash`` carries the transfer. Final.
    DELIVERED = "delivered"
    #: Not delivered and nothing charged; ``error`` says why. Final.
    REFUSED = "refused"
    #: Delivery could not be confirmed either way (the buy answer was HTTP 409
    #: with ``needs_attention=true``). Do NOT retry the buy - reconcile with
    #: ``order`` until it settles into ``delivered`` / ``refused``.
    UNRESOLVED = "unresolved"


_NATIVE_ORDER_TERMINAL = frozenset({"delivered", "refused"})


def is_native_order_terminal(status: str) -> bool:
    """Whether a native-coin purchase order status is final (``unresolved`` is not)."""
    return status in _NATIVE_ORDER_TERMINAL


@dataclass(kw_only=True)
class NativeQuoteRequest:
    #: Network whose native coin is bought - a :class:`~cryptochief.Chain` value.
    network: str
    #: Address the coins are sent to - any address; the merchant pays.
    receive_address: str
    #: Amount of native coin in human units (e.g. ``"0.05"``).
    amount: str


@dataclass(kw_only=True)
class NativeQuote:
    """A priced native-coin purchase. Valid until ``expires_at``."""

    #: Quote reference; pass it as ``quote_ref`` to ``buy`` to lock the price.
    ref: str = ""
    network: str = ""
    receive_address: str = ""
    amount: str = ""
    #: Cost of the coins at the quoted rate, in USD.
    coin_price_usd: str = ""
    #: Fee of the platform's own transfer, in the native coin...
    transfer_fee: str = ""
    #: ...and in USD - it is part of the price, the recipient pays nothing.
    transfer_fee_usd: str = ""
    #: ``coin_price_usd + transfer_fee_usd``.
    subtotal_usd: str = ""
    #: Final price in USD.
    total_usd: str = ""
    #: Price in credits (10_000_000 credits = 1 USD) - what ``buy`` charges.
    credits: int = 0
    #: Coin/USD rate the quote used.
    coin_usd: str = ""
    expires_at: str = ""  # RFC3339
    expires_in_sec: int = 0


@dataclass(kw_only=True)
class NativeBuyRequest:
    """The quote's fields for an ad-hoc price, or just ``quote_ref`` to lock one."""

    #: Network whose native coin is bought - a :class:`~cryptochief.Chain` value.
    network: Optional[str] = None
    #: Address the coins are sent to - any address; the merchant pays.
    receive_address: Optional[str] = None
    #: Amount of native coin in human units (e.g. ``"0.05"``).
    amount: Optional[str] = None
    #: ``ref`` of a quote that is still valid; locks its price.
    quote_ref: Optional[str] = None


@dataclass(kw_only=True)
class NativeOrder:
    id: int = 0
    #: The key the order was placed with; ``order`` looks orders up by it.
    idempotency_key: str = ""
    status: str = ""
    network: str = ""
    receive_address: str = ""
    amount: str = ""
    #: Hash of the transfer that delivered the coins.
    tx_hash: Optional[str] = None
    #: Always sent - as ``""`` / ``"0.00"`` on a ``refused`` order, where no
    #: price was kept.
    transfer_fee: Optional[str] = None
    transfer_fee_usd: Optional[str] = None
    coin_price_usd: Optional[str] = None
    #: Omitted on a ``refused`` order - a figure there would read as a charge
    #: that never happened.
    total_usd: Optional[str] = None
    credits: Optional[int] = None
    coin_usd: Optional[str] = None
    #: Whether the credits charge settled.
    settled: bool = False
    #: True on the 409 answer: delivery is unknown - reconcile, do not retry.
    needs_attention: bool = False
    #: Machine code of a failed order (``INSUFFICIENT_CREDITS``,
    #: ``INSUFFICIENT_LIQUIDITY``, ...) - branch on this, not on ``error``.
    error_code: Optional[str] = None
    #: Sanitised human sentence for ``error_code``.
    error: Optional[str] = None
    created_at: str = ""
    delivered_at: Optional[str] = None


class NativeService(BaseService):
    async def quote(self, req: NativeQuoteRequest) -> NativeQuote:
        """Price a native-coin purchase - free of charge.

        The answer breaks the price down: the coins at the current rate
        (``coin_price_usd``), the fee of the platform's own transfer
        (``transfer_fee`` / ``transfer_fee_usd``), their sum (``subtotal_usd``),
        and the final ``total_usd`` / ``credits``.
        Pass ``ref`` as ``quote_ref`` to ``buy`` before ``expires_at`` (about
        90 seconds; a quote is single-use) to lock the price.
        """
        return from_dict(NativeQuote, await self._post("/v1/native/quote", req))

    async def buy(
        self, req: NativeBuyRequest, *, idempotency_key: Optional[str] = None
    ) -> NativeOrder:
        """Buy native coin for ``receive_address``, sent from the platform's
        liquidity. Synchronous: the answer is always the order, one of:

        - ``delivered`` (HTTP 200) - the coins are sent; ``tx_hash`` carries
          the transfer.
        - ``refused`` (HTTP 502, or 402 when the credits balance did not cover
          the order) - nothing was sent or charged; ``error_code`` / ``error``
          say why. Retrying with a NEW idempotency key is safe.
        - ``unresolved`` (HTTP 409, ``needs_attention=true``) - the transfer's
          outcome never arrived, so the coins may already be sent. Do NOT
          retry: re-buying is exactly how the same transfer gets paid for
          twice. Follow the order with :meth:`order` until it settles.

        An ``Idempotency-Key`` is required: pass ``idempotency_key`` or wrap
        the call in :func:`cryptochief.idempotency_key`; without one the SDK
        raises :class:`CryptoChiefError` before sending (the API answers 400
        to one that never arrives). Retrying with the same key returns the
        same order.

        Failures with no order to report - a spent ``quote_ref`` (409
        ``QUOTE_EXPIRED`` / ``QUOTE_ALREADY_USED``), a pre-order balance check
        (402 ``INSUFFICIENT_CREDITS`` envelope), gateway failures - raise
        :class:`APIError` as usual.
        """
        key = idempotency_key if idempotency_key is not None else current_idempotency_key()
        if not key:
            raise CryptoChiefError(
                "cryptochief: native.buy: idempotency_key is required "
                "(pass the kwarg or use the idempotency_key() context manager)"
            )
        try:
            data = await self._post("/v1/native/buy", req, idempotency_key=key)
        except APIError as err:
            order = self._order_from_error(err, NativeOrder)
            if order is not None:
                return order
            raise
        return from_dict(NativeOrder, data)

    async def order(self, key: str) -> NativeOrder:
        """Read a native-coin purchase order back by its idempotency key."""
        return from_dict(NativeOrder, await self._post("/v1/native/order", {"key": key}))
