"""Wallet management + local RSA private-key decryption."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

from .._models import from_dict
from ..errors import CryptoChiefError
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
    #: A name for the wallet, for people reading a list of them. Applies to
    #: every wallet type - it names the wallet, it is not a property of its
    #: role - and is yours alone: nothing on chain and nothing in routing
    #: depends on it. Up to 255 characters, longer answers ``LABEL_TOO_LONG``.
    #: Leave it ``None`` to omit it; the endpoint rejects unknown fields, and an
    #: empty string is a name rather than the absence of one.
    #: :meth:`WalletsService.set_label` renames the wallet afterwards.
    label: Optional[str] = None


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
    #: The master this wallet sweeps into, ``None`` when it has none - a master
    #: wallet has no master of its own. The API always sends the key and sends
    #: ``null`` rather than an empty string, so ``None`` here means "no master",
    #: not "not reported". :meth:`WalletsService.rebind_master` changes it.
    master_wallet_address: Optional[str] = None
    #: Where deposits to this address are announced, ``None`` when nowhere. Only
    #: a static wallet has one: a master or transit always reads ``None``.
    #: :meth:`WalletsService.set_callback_url` changes it.
    callback_url: Optional[str] = None
    #: The wallet's name, ``None`` when it has none. Every wallet type can carry
    #: one, and every response that describes a wallet reports it. The API
    #: always sends the key and sends ``null`` rather than an empty string, so
    #: ``None`` here means "unnamed" - a cleared label reads back as ``None``,
    #: never as ``""``. :meth:`WalletsService.set_label` changes it.
    label: Optional[str] = None
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

    async def rebind_master(self, address: str, master_wallet_address: str) -> Wallet:
        """Re-point a transit or static wallet at another master of the project.

        The master link is decided when the wallet is created - at the master
        named on that request, or, when none was named, at the project's *oldest*
        master of that chain family, which on a project with more than one master
        is rarely the one you meant. This is the way back.

        It moves no money. It changes where the *next* sweep settles, including
        sweeps already queued, because the destination is resolved when the sweep
        runs; anything already swept sits on the previous master and has to be
        sent from there as an ordinary payout.

        Idempotent - a wallet already bound to that master answers 200 unchanged,
        so re-running the same list is safe. A master wallet cannot be
        re-pointed at all (``only transit and static wallets have a master``);
        naming something that is not a master as the TARGET is a different
        refusal (``not_a_master_wallet``). The target master must be the same
        chain family (``chain_family_mismatch``) and not frozen
        (``master_wallet_frozen``), since sweeping into a frozen master would
        strand the funds there.

        The gateway relays every upstream refusal as
        ``{"error": "SERVICE_ERROR", "msg": "<token>"}``, and the SDK reports
        that token as ``APIError.code`` - so branch on the code, not on the
        message text. These tokens are per-endpoint and are not
        :class:`~cryptochief.ErrorCode` members. Memo/tag-based families share one deposit
        account across orders and are excluded
        (``shared_transit_cannot_be_rebound``). Both addresses resolve against
        the authenticated project, so one that is not yours answers
        ``wallet_not_found`` / ``master_wallet_not_found`` rather than revealing
        that it exists elsewhere.

        Returns the wallet as it now stands.
        """
        return from_dict(
            Wallet,
            await self._post(
                "/v1/wallets/rebind-master",
                {"address": address, "master_wallet_address": master_wallet_address},
            ),
        )

    async def set_callback_url(self, address: str, callback_url: str) -> Wallet:
        """Set or clear a static wallet's deposit webhook after creation.

        Deposits are announced to the callback URL the *address* carries, which
        is fixed when the address is minted - so an address you did not create
        through your own integration, or one minted before your endpoint moved,
        keeps announcing its deposits somewhere else, or nowhere. This corrects
        it, from the next deposit on: one already announced is not re-announced
        to the new URL.

        Pass ``""`` to clear it and stop announcing deposits for the address.
        That is a real instruction rather than a missing field, so the SDK sends
        the empty string instead of dropping it the way it drops unset optional
        fields; the wallet then reads back ``callback_url=None``. ``None`` is
        not that instruction and is refused here rather than silently leaving
        the field off the body.

        Static wallets only - a master or transit has no per-deposit callback
        and answers 400. The address resolves against the authenticated project,
        so one that is not yours answers ``wallet_not_found``.

        Returns the wallet as it now stands.
        """
        if callback_url is None:
            raise CryptoChiefError(
                'cryptochief: set_callback_url: callback_url is required; pass "" to clear it'
            )
        return from_dict(
            Wallet,
            await self._post(
                "/v1/wallets/callback-url",
                {"address": address, "callback_url": callback_url},
            ),
        )

    async def set_label(self, address: str, label: str) -> Wallet:
        """Set or clear a wallet's label - the name it is read by.

        A label is yours alone: nothing on chain and nothing in routing depends
        on it. It is also the only thing telling one freshly minted address
        apart from the next in a list, so a wallet created before the label was
        supported, or minted somewhere other than your own integration, is worth
        naming after the fact. This is how.

        Every wallet type can be renamed - master, transit and static alike,
        because a label names the wallet rather than describing its role. That
        is unlike :meth:`set_callback_url`, which only a static wallet has.

        Pass ``""`` to clear the name and leave the wallet unnamed. That is a
        real instruction rather than a missing field, so the SDK sends the empty
        string instead of dropping it the way it drops unset optional fields;
        the wallet then reads back ``label=None``. ``None`` is not that
        instruction and is refused here rather than silently leaving the field
        off the body.

        Up to 255 characters, longer answers ``LABEL_TOO_LONG``. The address
        resolves against the authenticated project, so one that is not yours
        answers ``wallet_not_found`` rather than revealing that it exists
        elsewhere.

        Returns the wallet as it now stands.
        """
        if label is None:
            raise CryptoChiefError(
                'cryptochief: set_label: label is required; pass "" to clear it'
            )
        return from_dict(
            Wallet,
            await self._post("/v1/wallets/label", {"address": address, "label": label}),
        )

    def decrypt_private_key(self, encrypted: str) -> str:
        """Decrypt a generated wallet's ``private_key_encrypted`` field locally.

        Uses the RSA private key configured on the client (``rsa_private_key``
        option) and returns the chain-native hex private key. Raises
        :class:`RsaKeyNotConfiguredError` if no key was configured. Synchronous -
        never touches the network.
        """
        return self._client.rsa_decrypt(encrypted)
