"""Webhook verification and typed event parsing.

The signature is ``hex(md5(base64(canonical_json(body)) + api_key))`` - the same
algorithm used for outgoing requests. The body is re-canonicalized before
hashing, so any key-order drift is normalized. Framework-agnostic: feed it the
raw request bytes and the ``Signature`` header.
"""

from __future__ import annotations

import hmac
import json
from dataclasses import dataclass
from typing import Any, Dict, Optional, Union

from ._models import from_dict
from .errors import CryptoChiefError
from .sign import canonical_json, sign

#: Case-insensitive header name carrying the webhook signature.
WEBHOOK_HEADER = "Signature"

#: Header carrying the delivery's uuid on every webhook the platform sends.
#: Constant across every attempt and resend of one delivery - use it as your
#: receiver's idempotency key - and the argument ``client.webhooks.info()`` /
#: ``resend()`` take. Keep it when you log an incoming webhook: there is no
#: other way to name a delivery later.
WEBHOOK_DELIVERY_HEADER = "X-Webhook-Delivery"

#: IP addresses Crypto Chief delivers webhooks from - whitelist for defense in depth.
WEBHOOK_SENDER_IPS = ("164.90.231.203", "104.248.248.64")


class WebhookSignatureError(CryptoChiefError):
    """Raised when a webhook signature does not match the body."""

    def __init__(self) -> None:
        super().__init__("cryptochief: invalid webhook signature")


def _as_bytes(body: Union[str, bytes, bytearray]) -> bytes:
    return body.encode("utf-8") if isinstance(body, str) else bytes(body)


def verify_webhook_signature(
    api_key: str,
    raw_body: Union[str, bytes, bytearray],
    signature: Optional[str],
) -> bool:
    """Verify an incoming webhook against the merchant API key.

    ``raw_body`` MUST be the exact bytes received - do not re-encode it first.
    Returns ``True`` / ``False``; the comparison is constant-time.
    """
    if not api_key:
        raise CryptoChiefError("cryptochief: api_key is required for webhook verification")
    raw = _as_bytes(raw_body)
    if len(raw) == 0 or not signature:
        return False
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except ValueError:
        return False  # not JSON -> fail closed
    expected = sign(canonical_json(parsed), api_key)
    return hmac.compare_digest(expected, signature)


def parse_webhook_event(
    api_key: str,
    raw_body: Union[str, bytes, bytearray],
    signature: Optional[str],
) -> "WebhookEvent":
    """Verify and parse a webhook in one step.

    Raises :class:`WebhookSignatureError` if the signature is invalid; otherwise
    returns the typed event (chosen by the ``event`` name prefix), or the raw
    ``dict`` for an unrecognized prefix.
    """
    if not verify_webhook_signature(api_key, raw_body, signature):
        raise WebhookSignatureError()
    data = json.loads(_as_bytes(raw_body).decode("utf-8"))
    return coerce_webhook_event(data)


def coerce_webhook_event(data: Dict[str, Any]) -> "WebhookEvent":
    """Map a parsed webhook ``dict`` to its typed event by the ``event`` prefix."""
    prefix = str(data.get("event") or "").split(".")[0]
    cls = _EVENT_BY_PREFIX.get(prefix)
    return from_dict(cls, data) if cls is not None else data


# -- Typed event payloads -----------------------------------------------------


@dataclass(kw_only=True)
class PayoutWebhookEvent:
    """Payout webhook. Fires only on terminal status: ``payout.paid`` / ``payout.system_fail``."""

    event: str = ""
    uuid: str = ""
    status: str = ""
    order_id: Optional[str] = None
    user_id: Optional[str] = None
    amount_requested: Optional[str] = None
    amount_to_receive: Optional[str] = None
    to_address: Optional[str] = None
    fee_info: Optional[Dict[str, Any]] = None
    sources: Optional[Any] = None
    service_operations: Optional[Any] = None
    created_at: Optional[str] = None
    completed_at: Optional[str] = None
    error_reason: Optional[str] = None


@dataclass(kw_only=True)
class TransactionWebhookEvent:
    """Transaction webhook. Fires only on terminal status (confirmed / failed / expired)."""

    event: str = ""
    uuid: str = ""
    status: str = ""
    network: Optional[str] = None
    chain_family: Optional[str] = None
    type: Optional[str] = None
    from_address: Optional[str] = None
    to_address: Optional[str] = None
    value: Optional[str] = None
    contract: Optional[str] = None
    tx_hash: Optional[str] = None
    created_at: Optional[str] = None
    completed_at: Optional[str] = None
    error_reason: Optional[str] = None


@dataclass(kw_only=True)
class PayInWebhookEvent:
    """Pay-in webhook. Event names carry the ``invoice.`` prefix (e.g. ``invoice.paid``)."""

    event: str = ""
    uuid: str = ""
    status: str = ""
    order_id: Optional[str] = None
    user_id: Optional[str] = None
    prev_status: Optional[str] = None
    mode: Optional[str] = None
    amount_crypto: Optional[str] = None
    amount_fiat: Optional[str] = None
    fact_amount_crypto: Optional[str] = None
    fact_amount_fiat: Optional[str] = None
    currency: Optional[str] = None
    payment_coin: Optional[str] = None
    payment_network: Optional[str] = None
    to_address: Optional[str] = None
    txid: Optional[str] = None


@dataclass(kw_only=True)
class StaticDepositWebhookEvent:
    """Static-deposit webhook. Event names carry the ``static_deposit.`` prefix."""

    event: str = ""
    uuid: str = ""
    status: str = ""
    network: Optional[str] = None
    chain_family: Optional[str] = None
    coin: Optional[str] = None
    contract: Optional[str] = None
    decimals: Optional[int] = None
    to_address: Optional[str] = None
    from_address: Optional[str] = None
    tx_hash: Optional[str] = None
    amount: Optional[str] = None
    amount_fiat: Optional[str] = None
    confirmations: Optional[int] = None
    required_confirmations: Optional[int] = None
    found_in_mempool: Optional[bool] = None
    log_type: Optional[str] = None
    block_number: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    confirmed_at: Optional[str] = None
    paid_at: Optional[str] = None


#: The only sweep event the platform emits. There is deliberately no
#: ``sweep.broadcasted``: "we sent it" is not something you can act on, and an
#: event that means "maybe" is one more thing to reconcile.
SWEEP_EVENT_CONFIRMED = "sweep.confirmed"


@dataclass(kw_only=True)
class SweepWebhookEvent:
    """Funds swept off a deposit wallet, confirmed on chain.

    A ``static_deposit.paid`` tells you a customer paid you. This tells you the
    money has finished moving into your own custody - until it fires, the
    balance still sits on the deposit address. Reconciliation, treasury
    reporting and "funds available to pay out" all key off this event, not off
    the deposit.

    Sweeps run on static deposit wallets *and* on the transit wallets issued per
    pay-in order; both deliver here, to the callback URL configured for the
    wallet the funds left.
    """

    event: str = ""
    #: The sweeper task. One sweep settles once - use it as your idempotency key.
    task_id: str = ""
    #: Always ``"completed"``. A sweep reaches you in no other state.
    status: str = ""

    #: The wallet the funds left - the address your customer paid into.
    wallet_address: str = ""
    #: The master wallet they landed on.
    to_address: Optional[str] = None

    network: str = ""
    chain_family: Optional[str] = None
    asset_symbol: str = ""
    asset_contract: Optional[str] = None
    #: ``"native"`` or ``"token"``.
    asset_type: Optional[str] = None
    amount_raw: Optional[str] = None
    amount_human: Optional[str] = None

    sweep_tx_hash: str = ""
    #: Set when the platform had to fund gas on the wallet before it could sweep.
    gas_pump_tx_hash: Optional[str] = None

    #: What makes this event true rather than hopeful, and never zero. It
    #: travels with the event rather than being implied by it: "confirmed" is
    #: not the same number on every chain, so if you run your own finality
    #: policy you need the count to apply it.
    sweep_confirmations: int = 0

    #: When the chain was observed to hold the sweep. NOT the task's completion
    #: timestamp, which is stamped on every terminal outcome - failures
    #: included - and so says nothing about settlement.
    confirmed_at: Optional[str] = None

    #: What triggered it: ``"momentum"``, ``"threshold"`` or ``"force"``.
    type_work: Optional[str] = None
    #: What the sweep cost: network fee plus any gas or energy the platform
    #: fronted to make it possible.
    total_fee_usd: Optional[str] = None


WebhookEvent = Union[
    PayoutWebhookEvent,
    TransactionWebhookEvent,
    PayInWebhookEvent,
    StaticDepositWebhookEvent,
    SweepWebhookEvent,
    Dict[str, Any],
]

_EVENT_BY_PREFIX = {
    "payout": PayoutWebhookEvent,
    "transaction": TransactionWebhookEvent,
    "invoice": PayInWebhookEvent,
    "static_deposit": StaticDepositWebhookEvent,
    "sweep": SweepWebhookEvent,
}
