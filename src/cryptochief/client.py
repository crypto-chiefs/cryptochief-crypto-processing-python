"""The asynchronous Crypto Chief client and its low-level signed transport."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Mapping, Optional, Union

import httpx

from ._version import __version__
from .errors import CryptoChiefError, is_retryable
from .rsa import RsaKeyNotConfiguredError, decrypt_rsa_oaep, load_rsa_private_key_pem
from .services.blockchain import BlockchainService
from .services.currencies import CurrenciesService
from .services.payins import PayInsService
from .services.payouts import PayoutsService
from .services.static_deposits import StaticDepositsService
from .services.sweeps import SweepsService
from .services.transactions import TransactionsService
from .services.wallets import WalletsService
from .services.withdrawals import WithdrawalsService
from .sign import sign_value
from .ton.rpc import TonRpc
from .transport import backoff_delay, network_error, parse_api_error

#: SDK version, reported in the default ``User-Agent``.
VERSION = __version__

#: Production processing API endpoint. Test-mode projects share this host.
DEFAULT_BASE_URL = "https://api-processing.crypto-chief.com"

_MAX_RAW_IN_ERROR = 512


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
        if not api_key:
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

    async def request(self, path: str, body: Any = None) -> Any:
        """Low-level signed POST against an API path (e.g. ``/v1/payout/estimate``).

        Canonicalizes + signs the body, sends it, retries transient failures, and
        returns the parsed JSON. Service methods are thin wrappers over this;
        reach for it directly only to hit an endpoint the SDK doesn't model yet.
        """
        canonical, signature = sign_value(body, self._api_key)
        url = self.base_url + path
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Merchant": self.merchant_id,
            "Signature": signature,
            "User-Agent": self._user_agent,
        }
        body_bytes = canonical.encode("utf-8")
        attempts = self._retries + 1
        last_err: Optional[Exception] = None

        for attempt in range(attempts):
            if attempt > 0:
                await asyncio.sleep(backoff_delay(attempt, self._base_ms, self._max_ms))
            try:
                resp = await self._http.post(url, content=body_bytes, headers=headers)
            except httpx.HTTPError as err:
                last_err = network_error(str(err))
                if not is_retryable(last_err):
                    raise last_err
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
                continue
            raise api_err

        raise last_err or CryptoChiefError("cryptochief: retry budget exhausted")

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
