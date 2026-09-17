"""Webhook verification (HMAC-SHA256 v1) and typed event parsing.

Headers of a webhook:

* ``X-Webhook-Delivery`` - delivery id, 1-128 characters ``[A-Za-z0-9_-]``;
* ``X-CC-Timestamp`` - Unix time of the attempt in seconds, decimal digits
  without a leading zero;
* ``X-CC-Signature`` - ``v1=`` + 64 hex.

String to sign::

    CC-HMAC-SHA256-WEBHOOK-V1\n<X-CC-Timestamp>\n<X-Webhook-Delivery>\n<hex(sha256(body))>

``X-CC-Signature = "v1=" + hex(HMAC-SHA256(key=api_key, msg=string_to_sign))``.
The body is the raw request bytes, read before any JSON parsing.
"""

from __future__ import annotations

import hmac
import json
import math
import re
import string
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Protocol, Tuple, Union, cast

from ._models import from_dict
from .errors import CryptoChiefError
from .sign import (
    _DELIVERY_ID_RE,
    _MAX_TIMESTAMP,
    HMAC_V1_SIGNATURE_PREFIX,
    Body,
    _body_bytes,
    _mac,
    webhook_v1_string_to_sign,
)

#: Header carrying the delivery id. The same on every attempt and resend of
#: one delivery; the argument ``client.webhooks.info()`` and ``resend()`` take.
WEBHOOK_DELIVERY_HEADER = "X-Webhook-Delivery"

#: Header carrying the Unix time of the attempt, in seconds.
WEBHOOK_TIMESTAMP_HEADER = "X-CC-Timestamp"

#: Header carrying ``v1=`` + 64 hex.
WEBHOOK_SIGNATURE_HEADER = "X-CC-Signature"

#: Default allowed difference between ``X-CC-Timestamp`` and the local clock, seconds.
DEFAULT_WEBHOOK_TOLERANCE = 300

#: IP addresses Crypto Chief delivers webhooks from - whitelist for defense in depth.
WEBHOOK_SENDER_IPS = ("164.90.231.203", "104.248.248.64")


class _HeaderItems(Protocol):
    def items(self) -> Iterable[Tuple[Any, Any]]: ...


#: Headers as an object with ``items()`` (``dict``, Starlette, Werkzeug, httpx or
#: ``http.server`` headers) or an iterable of ``(name, value)`` pairs. A value
#: is ``str``, ``bytes`` or a list of them.
WebhookHeaders = Union[_HeaderItems, Iterable[Tuple[Any, Any]]]

_ASCII_LOWER = str.maketrans(string.ascii_uppercase, string.ascii_lowercase)
_DECIMAL_RE = re.compile(r"0|[1-9][0-9]*")
_HEX64_RE = re.compile(r"[0-9a-fA-F]{64}")


class WebhookVerificationError(CryptoChiefError):
    """A webhook failed verification; answer the sender with 401.

    :attr:`reason` is ``"headers"``, ``"timestamp"`` or ``"signature"``.
    """

    reason: str = ""


class WebhookHeadersError(WebhookVerificationError):
    """``X-CC-Timestamp``, ``X-Webhook-Delivery`` or ``X-CC-Signature`` is missing,
    repeated or malformed."""

    reason = "headers"

    def __init__(self) -> None:
        super().__init__("cryptochief: webhook signature headers are missing or malformed")


class WebhookTimestampError(WebhookVerificationError):
    """``X-CC-Timestamp`` differs from the local clock by more than the tolerance."""

    reason = "timestamp"

    def __init__(self) -> None:
        super().__init__("cryptochief: webhook timestamp is out of range")


class WebhookSignatureError(WebhookVerificationError):
    """``X-CC-Signature`` does not match the body, timestamp and delivery id."""

    reason = "signature"

    def __init__(self) -> None:
        super().__init__("cryptochief: invalid webhook signature")


def _text(value: Any) -> str:
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("latin-1")
    return value if isinstance(value, str) else str(value)


def _header_pairs(headers: WebhookHeaders) -> List[Tuple[str, Any]]:
    """Every ``(name, value)`` pair, read once, so that a one-shot iterable
    (a generator, ``iter(pairs)``) carries as many headers as a mapping."""
    pairs: Iterable[Tuple[Any, Any]] = cast(Iterable[Tuple[Any, Any]], headers)
    for method in ("multi_items", "items"):
        get_pairs = getattr(headers, method, None)
        if callable(get_pairs):
            pairs = cast(Iterable[Tuple[Any, Any]], get_pairs())
            break
    return [(_text(key), value) for key, value in pairs]


def _single_header(pairs: List[Tuple[str, Any]], name: str) -> Optional[str]:
    """The only value of a header without surrounding spaces and tabs; ``None``
    when the header is absent, repeated or contains CR or LF. A ``None`` value
    is an empty value, not an absent header. Names match ignoring ASCII case
    only."""
    wanted = name.translate(_ASCII_LOWER)
    values: List[str] = []
    for key, value in pairs:
        if key.translate(_ASCII_LOWER) != wanted:
            continue
        if value is None:
            values.append("")
        elif isinstance(value, (list, tuple)):
            values.extend("" if v is None else _text(v) for v in value)
        else:
            values.append(_text(value))
    if len(values) != 1:
        return None
    v = values[0].strip(" \t")
    if "\r" in v or "\n" in v:
        return None
    return v


def _parse_timestamp(value: Optional[str]) -> Optional[int]:
    """The header as a number, or ``None`` when it is not decimal digits without
    a leading zero, or does not fit int64."""
    if value is None or _DECIMAL_RE.fullmatch(value) is None:
        return None
    if len(value) > 19:
        return None
    ts = int(value)
    return ts if ts <= _MAX_TIMESTAMP else None


def _whole_seconds(value: Any, name: str) -> int:
    """``math.floor`` of a finite number of seconds."""
    try:
        if value != value:
            raise ValueError(name)
        return math.floor(value)
    except (TypeError, ValueError, ArithmeticError):
        raise CryptoChiefError(
            f"cryptochief: webhook {name} must be a finite number of seconds"
        ) from None


def verify_webhook(
    api_key: str,
    raw_body: Body,
    headers: WebhookHeaders,
    *,
    tolerance: float = DEFAULT_WEBHOOK_TOLERANCE,
    now: Optional[float] = None,
) -> None:
    """Verify a webhook by its raw body and headers.

    ``raw_body`` is the request body as received (a ``str`` is UTF-8 encoded).
    Header names match ignoring ASCII case; one header under two spellings is a
    repeat. ``tolerance`` is in seconds, a value <= 0 means
    :data:`DEFAULT_WEBHOOK_TOLERANCE`; ``now`` is Unix time in seconds, by
    default :func:`time.time`.

    Checks, in order: headers (:class:`WebhookHeadersError`), timestamp window
    (:class:`WebhookTimestampError`), signature (:class:`WebhookSignatureError`;
    constant-time, hex in any case). An ``api_key`` that is empty or only spaces
    and tabs, and a ``tolerance`` or ``now`` that is not a finite number, raise
    :class:`CryptoChiefError` before the headers are read.
    """
    if not api_key or not api_key.strip(" \t"):
        raise CryptoChiefError("cryptochief: api_key is required for webhook verification")
    whole_tolerance = _whole_seconds(tolerance, "tolerance")
    now_sec = math.floor(time.time()) if now is None else _whole_seconds(now, "now")

    pairs = _header_pairs(headers)
    timestamp = _parse_timestamp(_single_header(pairs, WEBHOOK_TIMESTAMP_HEADER))
    if timestamp is None:
        raise WebhookHeadersError()
    delivery_id = _single_header(pairs, WEBHOOK_DELIVERY_HEADER)
    if delivery_id is None or _DELIVERY_ID_RE.fullmatch(delivery_id) is None:
        raise WebhookHeadersError()
    signature = _single_header(pairs, WEBHOOK_SIGNATURE_HEADER)
    if signature is None or not signature.startswith(HMAC_V1_SIGNATURE_PREFIX):
        raise WebhookHeadersError()
    hex_signature = signature[len(HMAC_V1_SIGNATURE_PREFIX) :]
    if _HEX64_RE.fullmatch(hex_signature) is None:
        raise WebhookHeadersError()

    window = whole_tolerance if tolerance > 0 else DEFAULT_WEBHOOK_TOLERANCE
    if abs(now_sec - timestamp) > window:
        raise WebhookTimestampError()
    if timestamp == 0:
        raise WebhookHeadersError()

    string_to_sign = webhook_v1_string_to_sign(timestamp, delivery_id, raw_body)
    if not hmac.compare_digest(_mac(api_key, string_to_sign), bytes.fromhex(hex_signature)):
        raise WebhookSignatureError()


def parse_webhook_event(
    api_key: str,
    raw_body: Body,
    headers: WebhookHeaders,
    *,
    tolerance: float = DEFAULT_WEBHOOK_TOLERANCE,
    now: Optional[float] = None,
) -> "WebhookEvent":
    """Verify a webhook with :func:`verify_webhook`, then parse its raw body.

    Returns the typed event chosen by the ``event`` name prefix, or the ``dict``
    for an unrecognized prefix. Verification failures raise the
    :class:`WebhookVerificationError` subclasses; a verified body that is not a
    JSON object raises :class:`CryptoChiefError`.
    """
    verify_webhook(api_key, raw_body, headers, tolerance=tolerance, now=now)
    try:
        data = json.loads(_body_bytes(raw_body).decode("utf-8", "replace"))
    except (ValueError, RecursionError) as err:
        raise CryptoChiefError(f"cryptochief: webhook body is not JSON: {err}") from None
    if not isinstance(data, dict):
        raise CryptoChiefError("cryptochief: webhook body is not a JSON object")
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
    #: Each source carries ``confirmations`` once its transaction is on chain.
    sources: Optional[Any] = None
    #: Each service transaction carries ``confirmations`` once it is on chain.
    service_operations: Optional[Any] = None
    #: The lowest ``confirmations`` among sources that have a ``txid``; a source
    #: without a count counts as 0. ``None`` while no source has a transaction.
    confirmations: Optional[int] = None
    #: Confirmations each source needed before ``paid``. Optional.
    required_confirmations: Optional[int] = None
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
    #: Confirmations at the final status.
    confirmations: Optional[int] = None
    #: Confirmations needed to turn ``confirmed``.
    required_confirmations: Optional[int] = None
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

    Sent once ``sweep_confirmations`` reaches ``required_confirmations``.

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
    #: Confirmations the sweep needed before this event. Optional.
    required_confirmations: Optional[int] = None

    #: When the chain was observed to hold the sweep. Not the history's
    #: ``completed_at``, which is the broadcast time.
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
