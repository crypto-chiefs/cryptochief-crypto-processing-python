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


WebhookEvent = Union[
    PayoutWebhookEvent,
    TransactionWebhookEvent,
    PayInWebhookEvent,
    StaticDepositWebhookEvent,
    Dict[str, Any],
]

_EVENT_BY_PREFIX = {
    "payout": PayoutWebhookEvent,
    "transaction": TransactionWebhookEvent,
    "invoice": PayInWebhookEvent,
    "static_deposit": StaticDepositWebhookEvent,
}
