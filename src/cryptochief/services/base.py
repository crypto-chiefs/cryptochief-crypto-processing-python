"""Shared base for the domain services."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Optional, Type, TypeVar

from .._models import from_dict, to_payload
from ..errors import APIError

if TYPE_CHECKING:
    from ..client import CryptoChiefClient

T = TypeVar("T")

#: HTTP statuses an order can arrive on: refused is 502 - or 402 when the
#: reason is insufficient credits - and unresolved is 409.
_ORDER_BODY_STATUSES = (402, 409, 502)


class BaseService:
    """Holds the client reference and a signed-POST helper.

    Request bodies are serialized with :func:`to_payload` (drops ``None``); the
    field names already match the wire, so there is no case conversion.
    """

    def __init__(self, client: "CryptoChiefClient") -> None:
        self._client = client

    async def _post(
        self, path: str, body: Any = None, *, idempotency_key: Optional[str] = None
    ) -> Any:
        return await self._client.request(path, to_payload(body), idempotency_key=idempotency_key)

    @staticmethod
    def _order_from_error(err: APIError, cls: Type[T]) -> Optional[T]:
        """Recover an order carried as the body of a non-2xx answer.

        A refused or unresolved order is a business outcome, not a transport
        failure, so the API answers 402/502/409 with the order itself as the
        body; the ``id`` + ``status`` guard is what keeps an error envelope
        (``ok: false``) from being mistaken for one. Anything else - a gateway
        error page, a ``QUOTE_EXPIRED`` envelope - returns ``None`` so the
        caller re-raises.
        """
        if err.http_status not in _ORDER_BODY_STATUSES or not err.raw:
            return None
        try:
            data = json.loads(err.raw)
        except ValueError:
            return None
        if not isinstance(data, dict) or "id" not in data or "status" not in data:
            return None
        return from_dict(cls, data)
