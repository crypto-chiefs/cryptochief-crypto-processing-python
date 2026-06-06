"""Wallet management + local RSA private-key decryption."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

from .._models import from_dict
from .base import BaseService


class WalletType(str, Enum):
    MASTER = "master"
    TRANSIT = "transit"
    STATIC = "static"


@dataclass(kw_only=True)
class GenerateWalletRequest:
    wallet_type: str
    chain_family: str
    master_wallet_address: Optional[str] = None  # transit/static wallets only
    callback_url: Optional[str] = None  # static wallets only - per-deposit webhook URL


@dataclass(kw_only=True)
class WalletCoinBalance:
    address: Optional[str] = None
    chain: Optional[str] = None
    coin: Optional[str] = None
    contract: Optional[str] = None
    decimals: int = 0
    value: Optional[str] = None
    human_value: Optional[str] = None
    amount_usd: Optional[str] = None
    timestamp: Optional[int] = None


@dataclass(kw_only=True)
class Wallet:
    address: str = ""
    chain_family: Optional[str] = None
    type: Optional[str] = None
    wallet_type: Optional[str] = None
    frozen: Optional[bool] = None
    master_wallet_address: Optional[str] = None
    callback_url: Optional[str] = None
    #: Base64 RSA-OAEP/SHA-256 ciphertext - decrypt with ``decrypt_private_key``.
    private_key_encrypted: Optional[str] = None
    created_at: Optional[str] = None
    coins: Optional[List[WalletCoinBalance]] = None
    total_balance_usd: Optional[str] = None


@dataclass(kw_only=True)
class ListWalletsResponse:
    items: Optional[List[Wallet]] = None


class WalletsService(BaseService):
    async def generate(self, req: GenerateWalletRequest) -> Wallet:
        """Provision a new wallet on the requested chain family."""
        return from_dict(Wallet, await self._post("/v1/wallets/generate", req))

    async def list(self) -> ListWalletsResponse:
        """Every wallet on the project."""
        return from_dict(ListWalletsResponse, await self._post("/v1/wallets/list", {}))

    async def info(self, address: str) -> Wallet:
        """Details and current balances of one wallet."""
        return from_dict(Wallet, await self._post("/v1/wallets/info", {"address": address}))

    async def freeze(self, address: str) -> Wallet:
        """Toggle the frozen flag - the response's ``frozen`` field is the new state."""
        return from_dict(Wallet, await self._post("/v1/wallets/freeze", {"address": address}))

    def decrypt_private_key(self, encrypted: str) -> str:
        """Decrypt a generated wallet's ``private_key_encrypted`` field locally.

        Uses the RSA private key configured on the client (``rsa_private_key``
        option) and returns the chain-native hex private key. Raises
        :class:`RsaKeyNotConfiguredError` if no key was configured. Synchronous -
        never touches the network.
        """
        return self._client.rsa_decrypt(encrypted)
