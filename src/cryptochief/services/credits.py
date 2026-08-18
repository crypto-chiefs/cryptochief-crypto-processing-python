"""Merchant credits (billing): balance check and top-up.

Both calls are billing-exempt (free of charge) - integrations can poll the
balance or open a top-up invoice without spending a paid call. Rate-limited to
60 req/min per project; the balance answers even at zero or negative balance.
"""

from __future__ import annotations

from dataclasses import dataclass

from .._models import from_dict
from .base import BaseService


@dataclass(kw_only=True)
class CreditsBalance:
    #: Current balance in credits (10_000_000 credits = 1 USD).
    credits_balance: int = 0
    #: Pre-formatted USD with 2 decimals - can be negative, e.g. ``"-1.52"``.
    usd_balance: str = ""
    is_postpaid: bool = False
    #: Effective debt limit in credits (postpaid only, 0 for prepaid).
    debt_limit_credits: int = 0
    #: Whether gas-paying ops (``/v1/transaction/execute`` etc.) would pass the gate.
    can_execute_gas_operations: bool = False
    #: Minimum credits required for gas-paying operations.
    gas_ops_min_credits: int = 0
    timestamp: str = ""  # RFC3339


@dataclass(kw_only=True)
class CreditsTopup:
    #: Billing invoice id.
    invoice_id: int = 0
    #: Hosted payment page (QR code, network selection, live status).
    payment_link: str = ""
    amount: str = ""
    currency: str = ""
    status: str = ""  # "pending" on creation
    order_uuid: str = ""
    #: Unix seconds; 0 when the server does not set an expiry.
    expired_at: int = 0


class CreditsService(BaseService):
    async def balance(self) -> CreditsBalance:
        """Current credits balance - free of charge, safe to poll before paid calls."""
        return from_dict(CreditsBalance, await self._post("/v1/credits/balance", {}))

    async def topup(
        self,
        *,
        amount: str,
        currency: str,
        url_success: str | None = None,
        url_error: str | None = None,
    ) -> CreditsTopup:
        """Open a credits top-up invoice - free of charge.

        ``amount`` is a positive decimal up to 100000 (USD-pegged), ``currency``
        is ``"USDT"`` or ``"USDC"``. Send the payer to ``payment_link``; the
        optional urls are absolute http(s) redirects after payment.
        """
        body: dict[str, str] = {"amount": amount, "currency": currency}
        if url_success is not None:
            body["url_success"] = url_success
        if url_error is not None:
            body["url_error"] = url_error
        return from_dict(CreditsTopup, await self._post("/v1/credits/topup", body))
