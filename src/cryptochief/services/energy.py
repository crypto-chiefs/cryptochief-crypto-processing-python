"""TRON energy rental: quote a rental, place an order, read it back.

Delegating rented energy to the sender of a TRON transfer replaces the TRX the
network would burn for energy; the rental is billed in credits - the same
balance :meth:`cryptochief.CreditsService.balance` reports and
:meth:`~cryptochief.CreditsService.topup` refills. ``quote`` is free of
charge; ``rent`` is synchronous - by the time it answers, the energy is
delegated or the refusal reason is known.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .._models import from_dict
from ..errors import APIError, CryptoChiefError
from ..idempotency import current_idempotency_key
from .base import BaseService


class EnergyOrderStatus(str, Enum):
    """Energy-rental order status."""

    #: Energy delegated to ``receive_address``. Final.
    DELIVERED = "delivered"
    #: Not delivered and nothing charged; ``error`` says why. Final.
    REFUSED = "refused"
    #: Delivery could not be confirmed either way (the rent answer was HTTP 409
    #: with ``needs_attention=true``). Do NOT retry the rent - reconcile with
    #: ``order`` until it settles into ``delivered`` / ``refused``.
    UNRESOLVED = "unresolved"
    #: The charge went back to the credits balance. Final.
    REFUNDED = "refunded"


_ENERGY_ORDER_TERMINAL = frozenset({"delivered", "refused", "refunded"})


def is_energy_order_terminal(status: str) -> bool:
    """Whether an energy-rental order status is final (``unresolved`` is not)."""
    return status in _ENERGY_ORDER_TERMINAL


@dataclass(kw_only=True)
class EnergyQuoteRequest:
    #: Address the energy is delegated to - the sender of the planned transfer.
    receive_address: str
    #: Energy units to rent; the platform's default amount when omitted.
    energy: Optional[int] = None
    #: Rental length in seconds; the platform's default when omitted.
    duration_sec: Optional[int] = None


@dataclass(kw_only=True)
class EnergyQuote:
    """A priced energy rental. Valid until ``expires_at``."""

    #: Quote reference; pass it as ``quote_ref`` to ``rent`` to lock the price.
    ref: str = ""
    receive_address: str = ""
    energy: int = 0
    duration_sec: int = 0
    #: Rental price in sun (1 TRX = 1_000_000 sun).
    price_sun: int = 0
    #: Rental price in TRX, human-readable.
    price_trx: str = ""
    #: The fields below depend on a TRX/USD rate; when the platform has none
    #: they are omitted rather than guessed, and decode as ``None``.
    #: Rental price in USD.
    price_usd: Optional[str] = None
    #: Rental price in credits (10_000_000 credits = 1 USD) - what ``rent`` charges.
    credits: Optional[int] = None
    #: TRX/USD rate the quote used.
    trx_usd: Optional[str] = None
    #: On-chain state of ``receive_address``; a fresh address costs an
    #: activation fee on a native transfer, priced into the burn comparison.
    recipient_state: str = ""
    #: What the same transfer would cost burning TRX instead of renting.
    burn_price_sun: int = 0
    burn_price_trx: str = ""
    burn_price_usd: Optional[str] = None
    burn_price_credits: Optional[int] = None
    #: Renting minus burning - the saving this rental gives.
    saving_trx: str = ""
    saving_usd: Optional[str] = None
    saving_credits: Optional[int] = None
    expires_at: str = ""  # RFC3339
    expires_in_sec: int = 0


@dataclass(kw_only=True)
class EnergyRentRequest:
    """Same fields as the quote, plus ``quote_ref`` to lock a quoted price."""

    #: Address the energy is delegated to - the sender of the planned transfer.
    #: Not needed with ``quote_ref``: the quote's terms win.
    receive_address: Optional[str] = None
    #: Energy units to rent; the platform's default amount when omitted.
    energy: Optional[int] = None
    #: Rental length in seconds; the platform's default when omitted.
    duration_sec: Optional[int] = None
    #: ``ref`` of a quote that is still valid; locks its price.
    quote_ref: Optional[str] = None


@dataclass(kw_only=True)
class EnergyOrder:
    id: int = 0
    #: The key the order was placed with; ``order`` looks orders up by it.
    idempotency_key: str = ""
    status: str = ""
    receive_address: str = ""
    energy: int = 0
    duration_sec: int = 0
    price_sun: int = 0
    price_trx: str = ""
    #: Absent when nothing was charged (a ``refused`` order).
    price_usd: Optional[str] = None
    credits: Optional[int] = None
    trx_usd: Optional[str] = None
    #: Energy actually delegated; can differ from ``energy``.
    delivered_energy: int = 0
    #: Whether the credits charge settled.
    settled: bool = False
    #: True on the 409 answer: delivery is unknown - reconcile, do not retry.
    needs_attention: bool = False
    #: Machine code of a failed order (``INSUFFICIENT_CREDITS``,
    #: ``SUPPLIER_REFUSED``, ``SUPPLIER_UNKNOWN``) - branch on this, not on
    #: ``error``.
    error_code: Optional[str] = None
    #: Sanitised human sentence for ``error_code``.
    error: Optional[str] = None
    created_at: str = ""
    delivered_at: Optional[str] = None


class EnergyService(BaseService):
    async def quote(self, req: EnergyQuoteRequest) -> EnergyQuote:
        """Price an energy rental - free of charge.

        The answer carries both the rental price and what the same transfer
        would cost burning TRX (``burn_price_*``), so ``saving_*`` shows what
        renting saves. Pass ``ref`` as ``quote_ref`` to ``rent`` before
        ``expires_at`` to lock the price.
        """
        return from_dict(EnergyQuote, await self._post("/v1/energy/quote", req))

    async def rent(
        self, req: EnergyRentRequest, *, idempotency_key: Optional[str] = None
    ) -> EnergyOrder:
        """Rent energy for ``receive_address`` and delegate it. Synchronous:
        the answer is always the order, one of:

        - ``delivered`` (HTTP 200) - the energy is delegated.
        - ``refused`` (HTTP 502, or 402 when the credits balance did not cover
          the order) - nothing was delegated or charged (``price_usd`` /
          ``credits`` / ``trx_usd`` are absent); ``error_code`` / ``error``
          say why. Retrying with a NEW idempotency key is safe.
        - ``unresolved`` (HTTP 409, ``needs_attention=true``) - the supplier's
          answer never arrived, so the energy may already be delegated. Do NOT
          retry: re-renting is exactly how the same energy gets paid for
          twice. Follow the order with :meth:`order` until it settles.

        An ``Idempotency-Key`` is required: pass ``idempotency_key`` or wrap
        the call in :func:`cryptochief.idempotency_key`; without one the SDK
        raises :class:`CryptoChiefError` before sending (the API answers 400
        to one that never arrives). Retrying with the same key returns the
        same order.

        Failures with no order to report - a spent ``quote_ref`` (409
        ``QUOTE_EXPIRED`` / ``QUOTE_ALREADY_USED``), gateway failures - raise
        :class:`APIError` as usual.
        """
        key = idempotency_key if idempotency_key is not None else current_idempotency_key()
        if not key:
            raise CryptoChiefError(
                "cryptochief: energy.rent: idempotency_key is required "
                "(pass the kwarg or use the idempotency_key() context manager)"
            )
        try:
            data = await self._post("/v1/energy/rent", req, idempotency_key=key)
        except APIError as err:
            order = self._order_from_error(err, EnergyOrder)
            if order is not None:
                return order
            raise
        return from_dict(EnergyOrder, data)

    async def order(self, key: str) -> EnergyOrder:
        """Read an energy-rental order back by its idempotency key."""
        return from_dict(EnergyOrder, await self._post("/v1/energy/order", {"key": key}))
