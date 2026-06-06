"""Shared base for the domain services."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .._models import to_payload

if TYPE_CHECKING:
    from ..client import CryptoChiefClient


class BaseService:
    """Holds the client reference and a signed-POST helper.

    Request bodies are serialized with :func:`to_payload` (drops ``None``); the
    field names already match the wire, so there is no case conversion.
    """

    def __init__(self, client: "CryptoChiefClient") -> None:
        self._client = client

    async def _post(self, path: str, body: Any = None) -> Any:
        return await self._client.request(path, to_payload(body))
