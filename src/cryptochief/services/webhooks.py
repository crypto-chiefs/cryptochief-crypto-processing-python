"""Read and re-fire the platform's OUTBOUND webhooks - the deliveries it made to
your endpoint. (Verifying INCOMING webhooks is :mod:`cryptochief.webhook`.)

A delivery is named by the uuid the platform put on it in the
``X-Webhook-Delivery`` header (:data:`cryptochief.webhook.WEBHOOK_DELIVERY_HEADER`).
It is the same across every attempt and resend of that delivery - the natural
idempotency key for your receiver - and it is the only handle there is: the API
has no listing of deliveries, and the payload names the order, not the
delivery. Keep it when you log an incoming webhook.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from .._models import from_dict
from .base import BaseService


class WebhookDeliveryStatus(str, Enum):
    PENDING = "pending"  # queued, not yet attempted (or waiting for a retry)
    IN_PROGRESS = "in_progress"  # a worker holds it right now
    DELIVERED = "delivered"  # your endpoint answered 2xx
    FAILED = "failed"  # every attempt so far was refused or timed out
    CANCELLED = "cancelled"  # superseded by a newer event before it was ever sent


@dataclass(kw_only=True)
class WebhookAttempt:
    """One POST the platform made to your endpoint. Newest first in
    :attr:`WebhookDelivery.attempt_history`."""

    attempt: int = 0
    #: ``None`` when nothing answered (DNS, connect, TLS, timeout); ``error``
    #: then holds the transport error.
    http_status: Optional[int] = None
    error: Optional[str] = None
    duration_ms: Optional[int] = None
    target_url: Optional[str] = None
    #: ``None`` for attempts recorded before the platform kept the time.
    created_at: Optional[str] = None
    #: What your endpoint answered, as the platform saw it. Capped; see
    #: ``response_truncated``.
    response_body: Optional[str] = None
    response_content_type: Optional[str] = None
    response_truncated: bool = False


@dataclass(kw_only=True)
class WebhookPayload:
    """The body the platform sent. ``bytes`` is the whole size even when
    ``body`` was cut."""

    body: str = ""
    bytes: int = 0
    truncated: bool = False


@dataclass(kw_only=True)
class WebhookDelivery:
    """One outbound webhook, with every attempt the platform made and the body
    it sent. ``None`` means "not recorded", distinct from zero or empty."""

    uuid: str = ""
    event_type: str = ""
    #: The object the event was about - the order or static deposit uuid you
    #: already hold.
    reference: str = ""
    target_url: str = ""
    status: str = ""
    attempts: int = 0
    max_attempts: int = 0
    #: How many times a resend was asked for, by API or from the dashboard.
    resend_count: int = 0
    last_error: Optional[str] = None
    last_http_status: Optional[int] = None
    next_attempt_at: Optional[str] = None
    delivered_at: Optional[str] = None
    created_at: Optional[str] = None
    #: The NEWER event for the same object, when there is one. A superseded
    #: delivery cannot be resent - resend the latest event instead.
    superseded_by: Optional[str] = None
    attempt_history: List[WebhookAttempt] = field(default_factory=list)
    payload: Optional[WebhookPayload] = None


@dataclass(kw_only=True)
class WebhookResendResult:
    """What a resend did. On this platform a resend is synchronous: the POST to
    your endpoint happens before the answer comes back, so ``queued=True``
    arrives with ``status`` already ``delivered`` or ``failed`` for that
    attempt."""

    uuid: str = ""
    event_type: str = ""
    reference: str = ""
    status: str = ""
    queued: bool = False
    attempts: int = 0
    resend_count: int = 0
    #: Set when ``queued`` is false: one of the ``DELIVERY_*`` / ``RESEND_TOO_SOON``
    #: codes in :class:`cryptochief.ErrorCode`.
    reason: Optional[str] = None
    superseded_by: Optional[str] = None
    retry_after_seconds: Optional[int] = None


@dataclass(kw_only=True)
class StaticDepositResendResult:
    """The resend of a static deposit's webhook. ``deliveries`` has one entry -
    the newest delivery for the deposit - kept as a list so the shape matches
    the white-label platform, which may requeue several."""

    uuid: str = ""
    deliveries: List[WebhookResendResult] = field(default_factory=list)
    queued: int = 0
    total: int = 0


class WebhooksService(BaseService):
    async def info(self, delivery_uuid: str) -> WebhookDelivery:
        """One delivery by the uuid from its ``X-Webhook-Delivery`` header.

        A delivery that is not this project's is ``NOT_FOUND``, the same as one
        that does not exist.
        """
        return from_dict(WebhookDelivery, await self._post("/v1/webhooks/info", {"uuid": delivery_uuid}))

    async def resend(self, delivery_uuid: str) -> WebhookResendResult:
        """Send one delivery to your endpoint again, right now.

        Refused with :class:`cryptochief.APIError` whose ``code`` is:

        - ``DELIVERY_SUPERSEDED`` (409) - a newer event exists for the same
          object. Re-sending ``invoice.in_mempool`` after ``invoice.paid`` would
          tell your system the order went backwards, so only the latest event
          may be resent. Permanent; the newer event's name is in the message.
        - ``DELIVERY_IN_FLIGHT`` (409) - a worker is delivering it right now, or
          it is already scheduled for an automatic retry. Try again in a moment.
        - ``RESEND_TOO_SOON`` (429) - resent under a minute ago; ``Retry-After``
          is set.

        A successful manual delivery is billed as ``/v1/webhook/resend``; a
        refused one is not.
        """
        return from_dict(WebhookResendResult, await self._post("/v1/webhooks/resend", {"uuid": delivery_uuid}))

    async def resend_static_deposit(self, deposit_uuid: str) -> StaticDepositResendResult:
        """Re-fire the NEWEST webhook of one static deposit, named by the
        deposit's own uuid - for when you have the deposit and not the
        delivery. Older events of the deposit are superseded and are not resent.

        Refused with ``NO_DELIVERIES`` (409) when the deposit is yours but no
        webhook was ever queued for it: it arrived on a static wallet with no
        ``callback_url``. The per-delivery refusals of :meth:`resend` apply too.
        """
        return from_dict(
            StaticDepositResendResult,
            await self._post("/v1/static-deposits/resend", {"uuid": deposit_uuid}),
        )
