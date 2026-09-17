"""``Idempotency-Key`` for the calls made inside a block."""

from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

from .errors import CryptoChiefError

# Printable ASCII, no surrounding spaces. The server trims spaces and tabs off the
# header before signing it, so an untrimmed value would be signed here in a form the
# server never sees; a non-ASCII one cannot be put on the wire at all.
_IDEMPOTENCY_KEY_RE = re.compile(r"[\x21-\x7e]+(?: +[\x21-\x7e]+)*")

_CURRENT: ContextVar[str] = ContextVar("cryptochief_idempotency_key", default="")


def checked_idempotency_key(value: str) -> str:
    """The key as it goes on the wire, or :class:`CryptoChiefError`."""
    if _IDEMPOTENCY_KEY_RE.fullmatch(value) is None:
        raise CryptoChiefError(
            "cryptochief: idempotency_key must be printable ASCII "
            "without leading or trailing spaces or tabs"
        )
    return value


def current_idempotency_key() -> str:
    """The key set by :func:`idempotency_key`, or ``""``."""
    return _CURRENT.get()


@contextmanager
def idempotency_key(key: str) -> Iterator[None]:
    """Send ``Idempotency-Key: key`` on every call made inside the block::

        with idempotency_key("payout-2026-09-16-0001"):
            await client.payouts.execute(req)

    The header is covered by the signature. The key must be printable ASCII
    without leading or trailing spaces or tabs, otherwise
    :class:`CryptoChiefError`; an empty key sends no header. Tasks started inside
    the block carry it, tasks started outside do not; a key passed to
    ``client.request`` wins over the one set here.
    """
    token = _CURRENT.set(checked_idempotency_key(key) if key else "")
    try:
        yield
    finally:
        _CURRENT.reset(token)
