"""The asynchronous Crypto Chief client and its low-level signed transport."""

from __future__ import annotations

import asyncio
import json
import re
import secrets
import string
import time
from typing import Any, Callable, Dict, Mapping, Optional, Union

import httpx

from ._models import request_body
from ._version import __version__
from .errors import CryptoChiefError, ErrorCode, is_retryable
from .idempotency import checked_idempotency_key, current_idempotency_key
from .rsa import RsaKeyNotConfiguredError, decrypt_rsa_oaep, load_rsa_private_key_pem
from .services.blockchain import BlockchainService
from .services.credits import CreditsService
from .services.currencies import CurrenciesService
from .services.energy import EnergyService
from .services.native import NativeService
from .services.payins import PayInsService
from .services.payouts import PayoutsService
from .services.static_deposits import StaticDepositsService
from .services.webhooks import WebhooksService
from .services.sweeps import SweepsService
from .services.transactions import TransactionsService
from .services.wallets import WalletsService
from .services.withdrawals import WithdrawalsService
from .sign import (
    HEADER_HMAC_SIGNATURE,
    HEADER_IDEMPOTENCY_KEY,
    HEADER_NONCE,
    HEADER_TIMESTAMP,
    hmac_v1_sign,
)
from .ton.rpc import TonRpc
from .transport import backoff_delay, network_error, parse_api_error

#: SDK version, reported in the default ``User-Agent``.
VERSION = __version__

#: Production processing API endpoint. Test-mode projects share this host.
DEFAULT_BASE_URL = "https://api-processing.crypto-chief.com"

_MAX_RAW_IN_ERROR = 512

# An HTTP method is a token (RFC 9110). Restricted to one here so that upper-casing
# it in ASCII, as the string to sign does, is the method that goes on the wire.
_METHOD_RE = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+")
_ASCII_UPPER = str.maketrans(string.ascii_lowercase, string.ascii_uppercase)


def _checked_method(method: str) -> str:
    if _METHOD_RE.fullmatch(method) is None:
        raise CryptoChiefError("cryptochief: method must be an HTTP token (RFC 9110)")
    return method.translate(_ASCII_UPPER)


class CryptoChiefClient:
    """Entry point to the Crypto Chief processing API.

    Construct once and reuse - the client is stateless beyond its configuration.
    It owns an :class:`httpx.AsyncClient`, so close it when done (or use it as an
    async context manager)::

        async with CryptoChiefClient(merchant_id="M", api_key="K") as client:
            est = await client.payouts.estimate(EstimatePayoutRequest(
                network=Chain.ETH_SEPOLIA, coin="ETH", amount="0.0001",
                to_address="0x...",
            ))
    """

    def __init__(
        self,
        *,
        merchant_id: str,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 60.0,
        retries: int = 3,
        retry_backoff: Optional[Mapping[str, float]] = None,
        user_agent: Optional[str] = None,
        http_client: Optional[httpx.AsyncClient] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        rsa_private_key: Optional[Union[str, bytes, Any]] = None,
        ton_rpc_base_url: Optional[str] = None,
    ) -> None:
        if not merchant_id:
            raise CryptoChiefError("cryptochief: merchant_id is required")
        if not api_key or not api_key.strip(" \t"):
            raise CryptoChiefError("cryptochief: api_key is required")

        self.merchant_id = merchant_id
        self._api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._retries = retries
        backoff = retry_backoff or {}
        self._base_ms = backoff.get("base_ms", 200)
        self._max_ms = backoff.get("max_ms", 5000)
        self._user_agent = user_agent or f"cryptochief-python/{VERSION}"
        self._clock: Callable[[], float] = time.time
        self._clock_offset = 0  # seconds added to the local clock

        self._owns_http = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=timeout, transport=transport)

        self._rsa_input = rsa_private_key
        self._rsa_key: Any = None
        self._rsa_error: Optional[CryptoChiefError] = None

        self._ton_rpc_base_url = ton_rpc_base_url
        self._ton_rpc: Optional[TonRpc] = None

        self.payouts = PayoutsService(self)
        self.transactions = TransactionsService(self)
        self.pay_ins = PayInsService(self)
        self.wallets = WalletsService(self)
        self.sweeps = SweepsService(self)
        self.withdrawals = WithdrawalsService(self)
        self.static_deposits = StaticDepositsService(self)
        self.blockchain = BlockchainService(self)
        self.currencies = CurrenciesService(self)
        self.credits = CreditsService(self)
        self.energy = EnergyService(self)
        self.native = NativeService(self)
        self.webhooks = WebhooksService(self)

    async def request(
        self,
        path: str,
        body: Any = None,
        *,
        method: str = "POST",
        idempotency_key: Optional[str] = None,
    ) -> Any:
        """Low-level signed request to an API path (e.g. ``/v1/payout/estimate``).

        Serializes the body to JSON, signs the sent bytes with HMAC v1, retries
        transient failures, and returns the parsed JSON. Service methods are thin
        wrappers over this; reach for it directly only to hit an endpoint the SDK
        doesn't model yet, including one that takes another ``method`` - a signed
        ``GET`` with a query string, say. Dict members whose value is ``None`` are
        not sent, at any depth; a ``None`` body is an empty body. Integers are
        sent exactly; a float with an integral value is sent as an integer. The
        path is signed percent-decoded, as the server reads it, and the query
        raw, as sent. ``method`` must be an HTTP token and is upper-cased.
        ``idempotency_key`` is sent as ``Idempotency-Key`` and covered by the
        signature - :func:`~cryptochief.idempotency_key` sets it for service
        calls; it must be printable ASCII without leading or trailing spaces or
        tabs, and an empty one sends no header.
        """
        verb = _checked_method(method)
        body_bytes = request_body(body)
        url = httpx.URL(self.base_url + path)
        # The route the server reads: percent-decoded, without the base URL.
        route = httpx.URL(path).path
        query = url.query.decode("ascii")
        key = current_idempotency_key() if idempotency_key is None else idempotency_key
        base_headers = {
            "Accept": "application/json",
            "Merchant": self.merchant_id,
            "User-Agent": self._user_agent,
        }
        if body_bytes:
            base_headers["Content-Type"] = "application/json"
        if key:
            base_headers[HEADER_IDEMPOTENCY_KEY] = checked_idempotency_key(key)
        attempts = self._retries + 1
        attempt = 0
        sleep_first = False
        clock_corrected = False
        last_err: Optional[Exception] = None

        while attempt < attempts:
            if sleep_first:
                await asyncio.sleep(backoff_delay(attempt, self._base_ms, self._max_ms))
            headers = {
                **base_headers,
                **self._hmac_v1_headers(verb, route, query, key or "", body_bytes),
            }
            try:
                resp = await self._http.request(verb, url, content=body_bytes, headers=headers)
            except httpx.HTTPError as err:
                last_err = network_error(str(err))
                if not is_retryable(last_err):
                    raise last_err
                attempt += 1
                sleep_first = True
                continue

            text = resp.text
            status = resp.status_code
            if 200 <= status < 300:
                if not text:
                    return None
                try:
                    return json.loads(text)
                except ValueError as err:
                    raise CryptoChiefError(
                        f"cryptochief: decode {path} response: {err} "
                        f"(raw={text[:_MAX_RAW_IN_ERROR]})"
                    ) from err

            api_err = parse_api_error(status, text)
            if status >= 500:
                last_err = api_err
                attempt += 1
                sleep_first = True
                continue
            if (
                api_err.code == ErrorCode.SIGNATURE_TIMESTAMP_OUT_OF_RANGE
                and api_err.server_time is not None
                and not clock_corrected
            ):
                self._clock_offset = api_err.server_time - int(self._clock())
                clock_corrected = True
                sleep_first = False
                continue
            raise api_err

        raise last_err or CryptoChiefError("cryptochief: retry budget exhausted")

    def _hmac_v1_headers(
        self, method: str, route: str, query: str, idempotency_key: str, body: bytes
    ) -> Dict[str, str]:
        timestamp = str(int(self._clock()) + self._clock_offset)
        nonce = secrets.token_hex(16)
        signature = hmac_v1_sign(
            self._api_key,
            timestamp=timestamp,
            nonce=nonce,
            method=method,
            path=route,
            merchant=self.merchant_id,
            query=query,
            idempotency_key=idempotency_key,
            body=body,
        )
        return {
            HEADER_TIMESTAMP: timestamp,
            HEADER_NONCE: nonce,
            HEADER_HMAC_SIGNATURE: signature,
        }

    async def aclose(self) -> None:
        """Close the underlying HTTP client (only if this client created it)."""
        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self) -> "CryptoChiefClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    def rsa_decrypt(self, encrypted: str) -> str:
        """Decrypt a wallet ``private_key_encrypted`` field. Used by ``wallets``."""
        if self._rsa_error:
            raise self._rsa_error
        if self._rsa_key is None:
            if self._rsa_input is None:
                raise RsaKeyNotConfiguredError()
            try:
                if isinstance(self._rsa_input, (str, bytes, bytearray)):
                    self._rsa_key = load_rsa_private_key_pem(self._rsa_input)
                else:
                    self._rsa_key = self._rsa_input  # already a private-key object
            except CryptoChiefError as err:
                self._rsa_error = err
                raise
        return decrypt_rsa_oaep(self._rsa_key, encrypted)

    def ton_rpc(self) -> TonRpc:
        """Lazily built TON RPC helper, sharing the merchant credential + HTTP client."""
        if self._ton_rpc is None:
            self._ton_rpc = TonRpc(
                merchant_id=self.merchant_id,
                http=self._http,
                base_url=self._ton_rpc_base_url,
                user_agent=self._user_agent,
            )
        return self._ton_rpc
