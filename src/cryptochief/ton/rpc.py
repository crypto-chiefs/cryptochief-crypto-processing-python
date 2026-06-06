"""Internal TON RPC client.

Exists only to feed parameters (the sender's Jetton wallet address; whether a
recipient already has a Jetton wallet) into the high-level TON sign helpers - it
is not part of the public API surface.

URL pattern: ``<base_url>/ton-v3/<merchant_id>/<endpoint>``. The merchant ID is
the same credential used by the processing API; no separate token.
"""

from __future__ import annotations

import base64
from typing import Any, Optional
from urllib.parse import urlencode

import httpx
from pytoniq_core import Cell, begin_cell

from ..errors import CryptoChiefError
from .messages import parse_ton_addr

DEFAULT_TON_RPC_BASE_URL = "https://rpc.crypto-chief.com"


class TonRpc:
    def __init__(
        self,
        *,
        merchant_id: str,
        http: httpx.AsyncClient,
        base_url: Optional[str] = None,
        user_agent: str,
    ) -> None:
        self._merchant_id = merchant_id
        self._http = http
        self._base_url = (base_url or DEFAULT_TON_RPC_BASE_URL).rstrip("/")
        self._user_agent = user_agent
        self._cache: dict[str, str] = {}

    def _url(self, path: str, query: Optional[dict[str, str]] = None) -> str:
        u = f"{self._base_url}/ton-v3/{self._merchant_id}/{path.lstrip('/')}"
        if query:
            u += "?" + urlencode(query)
        return u

    async def _get(self, path: str, query: dict[str, str], timeout: float) -> Any:
        resp = await self._http.get(
            self._url(path, query),
            headers={"Accept": "application/json", "User-Agent": self._user_agent},
            timeout=timeout,
        )
        return self._handle(resp, path)

    async def _post(self, path: str, body: Any, timeout: float) -> Any:
        resp = await self._http.post(
            self._url(path),
            json=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": self._user_agent,
            },
            timeout=timeout,
        )
        return self._handle(resp, path)

    @staticmethod
    def _handle(resp: httpx.Response, path: str) -> Any:
        text = resp.text
        if resp.status_code >= 400:
            raise CryptoChiefError(
                f"cryptochief/ton: {path}: HTTP {resp.status_code}: {text[:256]}"
            )
        if not text:
            return None
        try:
            return resp.json()
        except ValueError as err:
            raise CryptoChiefError(f"cryptochief/ton: decode {path}: {err}") from err

    async def lookup_jetton_wallet(self, jetton_master: str, owner: str) -> str:
        """Resolve the Jetton wallet holding ``owner``'s balance of ``jetton_master``.

        Primary path: the deterministic ``get_wallet_address`` get-method on the
        master (works even for an owner that never received the Jetton). Fallback:
        the indexer. Cached for the client's lifetime.
        """
        if not jetton_master or not owner:
            raise CryptoChiefError("cryptochief/ton: jetton_master and owner are required")
        cache_key = f"{owner}|{jetton_master}"
        cached = self._cache.get(cache_key)
        if cached:
            return cached

        resolved = ""
        try:
            resolved = await self._via_run_method(jetton_master, owner)
        except Exception:  # noqa: BLE001 - fall back to the indexer
            resolved = ""
        if not resolved:
            resolved = await self._via_index(jetton_master, owner)
        self._cache[cache_key] = resolved
        return resolved

    async def _via_run_method(self, jetton_master: str, owner: str) -> str:
        owner_cell = begin_cell().store_address(parse_ton_addr(owner)).end_cell()
        owner_boc = base64.b64encode(bytes(owner_cell.to_boc())).decode("ascii")
        out = await self._post(
            "/runGetMethod",
            {
                "address": jetton_master,
                "method": "get_wallet_address",
                "stack": [{"type": "slice", "value": owner_boc}],
            },
            15.0,
        )
        exit_code = out.get("exit_code") if isinstance(out, dict) else None
        if exit_code not in (0, None):
            raise CryptoChiefError(f"cryptochief/ton: get_wallet_address: exit_code={exit_code}")
        stack = out.get("stack") if isinstance(out, dict) else None
        if not stack:
            raise CryptoChiefError("cryptochief/ton: get_wallet_address: empty stack")
        value = stack[0].get("value")
        result_cell = Cell.one_from_boc(base64.b64decode(value))
        return result_cell.begin_parse().load_address().to_str()

    async def _via_index(self, jetton_master: str, owner: str) -> str:
        out = await self._get(
            "/jetton/wallets",
            {"owner_address": owner, "jetton_address": jetton_master, "limit": "1"},
            15.0,
        )
        wallets = (out or {}).get("jetton_wallets") or []
        if not wallets:
            raise CryptoChiefError(
                f"cryptochief/ton: no Jetton wallet found for owner {owner} on master "
                f"{jetton_master} - owner has never received this Jetton"
            )
        wallet = wallets[0]
        address_book = (out or {}).get("address_book") or {}
        friendly = (address_book.get(wallet["address"]) or {}).get("user_friendly")
        return friendly or wallet["address"]

    async def has_jetton_wallet(self, jetton_master: str, owner: str) -> bool:
        """Whether ``owner`` already holds an initialized Jetton wallet for ``jetton_master``.

        Used to size the attached gas budget on transfers. Returns ``False`` (the
        conservative answer) on any RPC error.
        """
        try:
            out = await self._get(
                "/jetton/wallets",
                {"owner_address": owner, "jetton_address": jetton_master, "limit": "1"},
                5.0,
            )
            return len((out or {}).get("jetton_wallets") or []) > 0
        except Exception:  # noqa: BLE001 - conservative default
            return False
