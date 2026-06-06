"""Async polling helper used by the ``wait_for`` methods."""

from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable, Generic, Optional, TypeVar

from .errors import CryptoChiefError, is_retryable

T = TypeVar("T")


class PollTimeoutError(CryptoChiefError, Generic[T]):
    """Raised when a ``wait_for`` helper times out before reaching a terminal state."""

    last_state: Optional[T]

    def __init__(self, timeout: float, last_state: Optional[T] = None) -> None:
        super().__init__(
            f"cryptochief: poll did not reach a terminal state within {timeout}s"
        )
        self.last_state = last_state


async def wait_for_terminal(
    fetch_one: Callable[[], Awaitable[T]],
    is_terminal: Callable[[T], bool],
    *,
    interval: float = 5.0,
    timeout: float = 600.0,
) -> T:
    """Poll ``fetch_one`` until ``is_terminal`` holds or ``timeout`` elapses.

    Transient (retryable) fetch errors are tolerated and retried on the next
    tick; other errors propagate immediately. On timeout a
    :class:`PollTimeoutError` carrying the last observed state is raised.
    """
    interval = interval if interval and interval > 0 else 5.0
    timeout = timeout if timeout and timeout > 0 else 600.0
    deadline = time.monotonic() + timeout
    last: Optional[T] = None

    while True:
        try:
            value = await fetch_one()
            last = value
            if is_terminal(value):
                return value
        except Exception as err:  # noqa: BLE001 - re-raised unless retryable
            if not is_retryable(err):
                raise
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise PollTimeoutError(timeout, last)
        await asyncio.sleep(min(interval, remaining))
