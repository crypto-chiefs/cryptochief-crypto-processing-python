"""Asset selection policies used by payouts and FIAT-mode pay-ins."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass(kw_only=True)
class Asset:
    """A specific coin on a specific network.

    ``network`` takes a chain code (e.g. ``Chain.ETH_MAINNET``) or the wildcard
    ``"ANY"``; ``coin`` is the symbol (e.g. ``"USDT"``). Either field may be
    omitted to mean "any".
    """

    network: Optional[str] = None
    coin: Optional[str] = None


@dataclass(kw_only=True)
class AssetsPolicy:
    """An allow / exclude filter over :class:`Asset` entries.

    Omitting both lists means "no restriction". Used for payout auto-convert
    source selection and to restrict which coins a FIAT-mode pay-in customer may
    pick.
    """

    allow: Optional[List[Asset]] = None
    exclude: Optional[List[Asset]] = None
