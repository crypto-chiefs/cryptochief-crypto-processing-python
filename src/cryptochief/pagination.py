"""Shared pagination shapes for the history endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(kw_only=True)
class HistoryQuery:
    """Common filter for history endpoints with simple pagination.

    Omitted (``None``) fields are not sent.
    """

    page: Optional[int] = None
    page_size: Optional[int] = None
    status: Optional[str] = None
    coin: Optional[str] = None
    network: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None


@dataclass(kw_only=True)
class HistoryMeta:
    """Pagination envelope returned by every history endpoint."""

    page: int = 0
    page_size: int = 0
    total: int = 0
    total_pages: Optional[int] = None
