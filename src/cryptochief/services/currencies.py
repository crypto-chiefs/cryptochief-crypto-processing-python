"""Fiat <-> crypto rate calculator.

These quote rates only - they do NOT move funds (a swap is a payout with
``auto_convert=True``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

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
