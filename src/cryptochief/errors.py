"""Error model for the SDK.

Everything the SDK raises derives from :class:`CryptoChiefError`, so a single
``except CryptoChiefError`` covers the library. API-level failures arrive as
:class:`APIError` with a stable :attr:`APIError.code` string - branch on
:class:`ErrorCode` (or ``error.code``) rather than parsing messages.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional


class CryptoChiefError(Exception):
    """Base class for every error raised by the SDK."""


class APIError(CryptoChiefError):
    """A typed Crypto Chief error response.

    The API returns either ``{"error": "SERVICE_ERROR", "msg": "<CODE>", ...}``
    (then :attr:`code` is ``<CODE>``) or ``{"error": "<CODE>", ...}`` (then
    :attr:`code` is that value). Either way :attr:`code` is the stable
    identifier to branch on::

        try:
            await client.payouts.execute(req)
        except APIError as e:
            if e.code == ErrorCode.INSUFFICIENT_FUNDS:
                ...  # top up and retry
    """

    code: str
    http_status: int
    raw: Optional[str]

    def __init__(
        self,
        code: str,
        *,
        http_status: int = 0,
        message: Optional[str] = None,
        raw: Optional[str] = None,
    ) -> None:
        # Normalize an ErrorCode member to its wire string ("NETWORK_ERROR"),
        # not its enum repr ("ErrorCode.NETWORK_ERROR").
        self.code = code.value if isinstance(code, Enum) else str(code)
        self.http_status = http_status
        self.raw = raw
        super().__init__(self._format(http_status, self.code, message))

    @staticmethod
    def _format(status: int, code: str, message: Optional[str]) -> str:
        if status == 0:
            return f"cryptochief: {code}"
        if message and message != code:
            return f"cryptochief: {status} {code}: {message}"
        return f"cryptochief: {status} {code}"


class ErrorCode(str, Enum):
    """Stable error codes.

    Not exhaustive - the API defines more per endpoint and may add new ones, so
    treat an unknown :attr:`APIError.code` as opaque.
    """

    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    INSUFFICIENT_CREDITS = "INSUFFICIENT_CREDITS"
    DEBT_LIMIT_EXCEEDED = "DEBT_LIMIT_EXCEEDED"
    ASSET_NOT_ENABLED = "ASSET_NOT_ENABLED"
    ORDER_ALREADY_EXIST = "ORDER_ALREADY_EXIST"
    ORDER_CANNOT_CANCEL = "ORDER_CANNOT_CANCEL"
    ORDER_NOT_LIVE = "ORDER_NOT_LIVE"
    ASSET_ALREADY_SELECTED = "ASSET_ALREADY_SELECTED"
    INVALID_PARAMS = "INVALID_PARAMS"
    SERVICE_ERROR = "SERVICE_ERROR"
    UNAUTHORIZED = "UNAUTHORIZED"
    URL_CALLBACK_REQUIRED = "URL_CALLBACK_REQUIRED"
    BATCH_EMPTY = "BATCH_EMPTY"
    BATCH_TOO_LARGE = "BATCH_TOO_LARGE"
    BATCH_DUPLICATE_ORDER_ID = "BATCH_DUPLICATE_ORDER_ID"
    FROM_WALLET_NOT_OWNED = "FROM_WALLET_NOT_OWNED"
    SIGNATURE_EXPIRED = "SIGNATURE_EXPIRED"
    ALREADY_EXECUTED = "ALREADY_EXECUTED"
    PREFLIGHT_FAILED = "PREFLIGHT_FAILED"
    BROADCAST_FAILED = "BROADCAST_FAILED"
    SIGNED_TX_MISMATCH = "SIGNED_TX_MISMATCH"
    CONTRACT_REQUIRED_FOR_TOKEN = "CONTRACT_REQUIRED_FOR_TOKEN"
    TRANSFER_FIELDS_NOT_ALLOWED_FOR_CONTRACT = "TRANSFER_FIELDS_NOT_ALLOWED_FOR_CONTRACT"
    CALLS_REQUIRED = "CALLS_REQUIRED"
    CALLS_NOT_ALLOWED_FOR_TRANSFER = "CALLS_NOT_ALLOWED_FOR_TRANSFER"
    CONTRACT_CALLS_UNSUPPORTED_ON_NETWORK = "CONTRACT_CALLS_UNSUPPORTED_ON_NETWORK"
    NETWORK_ERROR = "NETWORK_ERROR"


def is_api_error(err: object, code: Optional[str] = None) -> bool:
    """``True`` when ``err`` is an :class:`APIError` (optionally with ``code``)."""
    return isinstance(err, APIError) and (code is None or err.code == code)


def is_retryable(err: object) -> bool:
    """Report whether an error is plausibly transient and worth retrying.

    Only 5xx responses and transport ``NETWORK_ERROR`` failures qualify; 4xx is
    the caller's fault and is never retried.
    """
    if isinstance(err, APIError):
        return err.http_status >= 500 or err.code == ErrorCode.NETWORK_ERROR
    return False
