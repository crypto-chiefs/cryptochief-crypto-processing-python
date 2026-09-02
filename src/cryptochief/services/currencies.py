"""Fiat <-> crypto rate calculator, and the two lists of what it can price.

These quote rates only - they do NOT move funds (a swap is a payout with
``auto_convert=True``).

The same goes for the catalogues here: :meth:`CurrenciesService.fiats` and
:meth:`CurrenciesService.cryptos` say what the platform can put a *number* on,
which is a much longer list than what a project can be paid in. That one is
:meth:`~cryptochief.BlockchainService.contracts_available`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from .._models import from_dict
from .base import BaseService


@dataclass(kw_only=True)
class ConvertRequest:
    from_: str  # source ticker (`from` is a Python keyword - serialized below)
    to: str
    amount: str
    provider: Optional[str] = None


@dataclass(kw_only=True)
class ConvertResponse:
    amount_crypto: float = 0.0
    amount_fiat: float = 0.0
    crypto: Optional[str] = None
    crypto_to_usdt: float = 0.0
    exchange: Optional[str] = None
    fiat: Optional[str] = None
    fiat_to_usd: float = 0.0
    timestamp_crypto: int = 0
    timestamp_fiat: int = 0


@dataclass(kw_only=True)
class FiatCurrency:
    """One fiat currency the platform can price an order in.

    :attr:`code` is what a fiat-mode pay-in's ``currency`` takes and what the
    fiat side of :meth:`CurrenciesService.fiat_to_crypto` /
    :meth:`CurrenciesService.crypto_to_fiat` takes.
    """

    #: ISO 4217 code, e.g. ``"SEK"``.
    code: str = ""
    #: Display name, e.g. ``"Swedish Krona"``.
    name: str = ""


@dataclass(kw_only=True)
class CryptoCurrencies:
    """The crypto tickers the platform has a rate for, against :attr:`quote`.

    Rate availability only: a ticker here is one the platform can quote, which
    does not mean it takes deposits, sweeps or payouts in it. What a project can
    actually be paid in is
    :meth:`~cryptochief.BlockchainService.contracts_available`, and that is the
    list to build an asset picker from.
    """

    #: Every ticker, deduplicated across the exchanges.
    tickers: Optional[List[str]] = None
    #: The tickers each exchange carries, keyed by exchange name (``"binance"``,
    #: ``"bybit"``, ``"exmo"``, ``"kucoin"``).
    by_exchange: Optional[Dict[str, List[str]]] = None
    #: How many tickers :attr:`tickers` holds.
    count: int = 0
    #: The asset the rates are quoted against - ``"USDT"``.
    quote: str = ""


def _body(req: ConvertRequest) -> dict:
    body = {"from": req.from_, "to": req.to, "amount": req.amount}
    if req.provider is not None:
        body["provider"] = req.provider
    return body


class CurrenciesService(BaseService):
    async def fiat_to_crypto(self, req: ConvertRequest) -> ConvertResponse:
        """Quote how much crypto the given fiat amount is worth."""
        return from_dict(
            ConvertResponse, await self._post("/v1/currencies/convert/fiat-crypto", _body(req))
        )

    async def crypto_to_fiat(self, req: ConvertRequest) -> ConvertResponse:
        """Quote how much fiat the given crypto amount is worth."""
        return from_dict(
            ConvertResponse, await self._post("/v1/currencies/convert/crypto-fiat", _body(req))
        )

    async def fiats(self) -> List[FiatCurrency]:
        """Every fiat currency the platform can price an order in.

        ``/v1/currencies/fiats``. These are the codes a fiat-mode pay-in's
        ``currency`` accepts and the codes the fiat side of a rate quote
        accepts - populate a currency dropdown from this rather than shipping a
        hard-coded list that drifts. Platform-wide, so there is nothing to
        filter by project and nothing to pass.

        The API answers with a bare JSON array rather than an ``items``
        envelope, so this returns a plain list - the same shape as
        :meth:`~cryptochief.BlockchainService.supported_chains`, and the only
        other endpoint written that way.

        An empty answer is an empty list. The service builds its result from a
        nil slice, so "no currencies" reaches the wire as a literal ``null``
        rather than ``[]`` - this returns ``[]`` for both, never ``None``, so
        the result is always safe to iterate.
        """
        raw = await self._post("/v1/currencies/fiats", {})
        return [from_dict(FiatCurrency, r) for r in (raw or [])]

    async def cryptos(self) -> CryptoCurrencies:
        """Every crypto ticker the platform has a rate for, and where it comes from.

        ``/v1/currencies/cryptos``. ``tickers`` is the union across exchanges,
        ``by_exchange`` says which exchange carries which, ``count`` is the size
        of ``tickers`` and ``quote`` is what the rates are quoted against
        (``USDT``). Platform-wide; nothing to pass.

        **Rate availability only.** A ticker here can be *quoted*, which is not
        the same as being an asset this project can be paid in: the platform
        prices thousands of tickers and takes deposits, sweeps and payouts in
        far fewer. Build a customer-facing asset picker from
        :meth:`~cryptochief.BlockchainService.contracts_available` - that is the
        list governing orders, sweeps and payouts - and use this one for rates
        and price displays.

        Nothing here throws on a thin answer: a literal ``null`` body decodes to
        an all-defaults :class:`CryptoCurrencies`, and ``tickers`` /
        ``by_exchange`` read ``None`` when the server omits or nulls them - walk
        them as ``rates.tickers or []``. An exchange whose ticker list comes
        back ``null`` inside ``by_exchange`` reads as an empty list, so the map's
        values are always iterable.
        """
        return from_dict(CryptoCurrencies, await self._post("/v1/currencies/cryptos", {}))
