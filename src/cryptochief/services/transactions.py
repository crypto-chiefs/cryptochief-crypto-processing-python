"""Two-phase sign/execute for arbitrary merchant-owned transactions, plus
one-call helpers for EVM/TRON contracts, Solana Anchor programs, and TON
Jetton/NFT/comment transfers.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List, Optional, Union

from .._models import from_dict
from ..contract.borsh import BorshValue, encode_anchor_instruction
from ..contract.evm_abi import encode_evm_call_hex
from ..errors import CryptoChiefError
from ..pagination import HistoryMeta, HistoryQuery
from ..poll import wait_for_terminal
from ..ton.messages import (
    build_jetton_transfer_body,
    build_nft_transfer_body,
    build_text_comment_body,
    build_text_comment_cell,
    parse_ton_addr,
)
from .base import BaseService


class TxType(str, Enum):
    """Transaction type discriminator the API uses to pick a signing path."""

    NATIVE = "native"  # native-asset transfer: to_address + value
    TOKEN = "token"  # ERC-20-style token transfer: to_address + value + contract
    CONTRACT = "contract"  # arbitrary contract call(s): calls[]


class TxStatus(str, Enum):
    SIGNED = "signed"
    BROADCASTING = "broadcasting"
    BROADCASTED = "broadcasted"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    EXPIRED = "expired"


_TX_TERMINAL = frozenset({"confirmed", "failed", "expired"})


def is_transaction_terminal(status: str) -> bool:
    """Whether a transaction status is final."""
    return status in _TX_TERMINAL


# Default attached-gas budgets for TON transfers (nanoTON).
_JETTON_ATTACHED_EXISTING_WALLET = 70_000_000  # 0.07 TON
_JETTON_ATTACHED_NEW_WALLET = 150_000_000  # 0.15 TON
_NFT_ATTACHED_DEFAULT = 50_000_000  # 0.05 TON


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _value_string(v: Union[str, int, None]) -> str:
    if v is None or v == "":
        return "0"
    return str(v)


@dataclass(kw_only=True)
class SolanaAccount:
    """Solana account meta."""

    pubkey: str
    is_signer: bool
    is_writable: bool


@dataclass(kw_only=True)
class ContractCall:
    """One instruction in a ``contract``-type request.

    Per-family encoding:

    * EVM/TRON - ``data`` is hex calldata (``0x...``), single call.
    * TON - ``data`` is a base64 BoC body cell, single call, ``bounce`` defaults true.
    * Solana - ``to`` is the program id, ``data`` base64 instruction data,
      ``accounts`` lists the metas; multiple instructions allowed.
    """

    to: str
    data: str
    value: Optional[str] = None
    accounts: Optional[List[SolanaAccount]] = None
    bounce: Optional[bool] = None


@dataclass(kw_only=True)
class SignTransactionRequest:
    network: str
    from_address: str
    type: str
    to_address: Optional[str] = None  # transfer-mode (native/token)
    value: Optional[str] = None  # transfer-mode value in BASE units (e.g. wei)
    contract: Optional[str] = None  # token contract for `token` type
    calls: Optional[List[ContractCall]] = None  # contract-mode instructions
    url_callback: Optional[str] = None


@dataclass(kw_only=True)
class SignTransactionResponse:
    uuid: str = ""
    status: str = ""
    signed_tx_hex: Optional[str] = None
    tx_hash: Optional[str] = None
    expires_at: Optional[str] = None
    chain_family: Optional[str] = None
    network: Optional[str] = None


@dataclass(kw_only=True)
class ExecuteTransactionRequest:
    uuid: str
    signed_tx_hex: Optional[str] = None  # optional client-vs-server byte-match check


@dataclass(kw_only=True)
class TransactionInfo:
    uuid: str = ""
    status: str = ""
    network: Optional[str] = None
    chain_family: Optional[str] = None
    from_address: Optional[str] = None
    to_address: Optional[str] = None
    type: Optional[str] = None
    value: Optional[str] = None
    coin: Optional[str] = None
    contract: Optional[str] = None
    tx_hash: Optional[str] = None
    signed_tx_hex: Optional[str] = None
    expires_at: Optional[str] = None
    nonce: Optional[int] = None
    actual_fee: Optional[str] = None
    actual_fee_fiat: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    error: Optional[str] = None


@dataclass(kw_only=True)
class TransactionHistoryResponse:
    items: Optional[List[TransactionInfo]] = None
    meta: Optional[HistoryMeta] = None


# -- High-level contract-call request shapes ----------------------------------


@dataclass(kw_only=True)
class EvmCallRequest:
    """EVM / TRON contract call by Solidity-style signature."""

    network: str
    from_address: str
    contract: str
    method: str  # e.g. "transfer(address,uint256)"
    args: List[Any] = field(default_factory=list)
    value: Optional[str] = None
    url_callback: Optional[str] = None


@dataclass(kw_only=True)
class Erc20TransferRequest:
    network: str
    from_address: str
    token_contract: str
    recipient: str
    amount: Union[int, str]  # token base units (use human_to_base with the decimals)
    url_callback: Optional[str] = None


@dataclass(kw_only=True)
class AnchorCallRequest:
    network: str
    from_address: str
    program: str
    method: str
    args: List[BorshValue] = field(default_factory=list)
    accounts: List[SolanaAccount] = field(default_factory=list)
    url_callback: Optional[str] = None


@dataclass(kw_only=True)
class SolanaCallRequest:
    network: str
    from_address: str
    program: str
    instruction_data: bytes
    accounts: List[SolanaAccount] = field(default_factory=list)
    url_callback: Optional[str] = None


@dataclass(kw_only=True)
class TonCallRequest:
    network: str
    from_address: str
    contract: str
    body_cell: bytes  # raw BoC bytes; base64-encoded internally
    value: Union[str, int, None] = None
    bounce: Optional[bool] = None
    url_callback: Optional[str] = None


@dataclass(kw_only=True)
class JettonTransferRequest:
    network: str
    from_address: str  # sender's TON wallet (owns the Jetton wallet)
    recipient: str  # recipient's *main* TON wallet (not their Jetton wallet)
    amount: int  # Jetton amount in base units
    jetton_master: Optional[str] = None  # token id; needed if jetton_wallet_address omitted
    jetton_wallet_address: Optional[str] = None  # pre-resolved sender Jetton wallet
    response_destination: Optional[str] = None  # receives unused gas; defaults to from_address
    attached_ton: Optional[int] = None  # gas budget nanoTON; auto-picked when omitted
    forward_ton_amount: Optional[int] = None  # nanoTON; defaults to 1 when memo set, else 0
    memo: Optional[str] = None  # comment shown by wallets (encoded as forward payload)
    query_id: Optional[int] = None
    url_callback: Optional[str] = None


@dataclass(kw_only=True)
class NftTransferRequest:
    network: str
    from_address: str
    nft_item: str
    new_owner: str
    response_destination: Optional[str] = None
    attached_ton: Optional[int] = None
    forward_ton_amount: Optional[int] = None
    query_id: Optional[int] = None
    url_callback: Optional[str] = None


@dataclass(kw_only=True)
class TonCommentRequest:
    network: str
    from_address: str
    recipient: str
    text: str
    amount_ton: Optional[int] = None  # amount to send in nanoTON
    url_callback: Optional[str] = None


class TransactionsService(BaseService):
    async def sign(self, req: SignTransactionRequest) -> SignTransactionResponse:
        """Build and sign a transaction WITHOUT broadcasting.

        The signature has a per-family TTL (EVM 10m, UTXO 15m, TRON 45s, Solana
        60s, XRP 90s, TON 300s) - call ``execute`` before it elapses.
        """
        return from_dict(SignTransactionResponse, await self._post("/v1/transaction/signature", req))

    async def execute(self, req: ExecuteTransactionRequest) -> TransactionInfo:
        """Broadcast a previously-signed transaction by uuid."""
        return from_dict(TransactionInfo, await self._post("/v1/transaction/execute", req))

    async def info(self, uuid: str) -> TransactionInfo:
        """Fetch the current state of one transaction by uuid."""
        return from_dict(TransactionInfo, await self._post("/v1/transaction/info", {"uuid": uuid}))

    async def history(self, query: Optional[HistoryQuery] = None) -> TransactionHistoryResponse:
        """Paged list of merchant-owned transactions."""
        return from_dict(
            TransactionHistoryResponse,
            await self._post("/v1/transaction/history", query or HistoryQuery()),
        )

    async def wait_for(
        self, uuid: str, *, interval: float = 5.0, timeout: float = 600.0
    ) -> TransactionInfo:
        """Poll ``info`` until the transaction reaches a terminal state (or timeout)."""

        async def fetch() -> TransactionInfo:
            return await self.info(uuid)

        return await wait_for_terminal(
            fetch, lambda t: is_transaction_terminal(t.status), interval=interval, timeout=timeout
        )

    # -- Contract-call helpers --------------------------------------------------

    async def sign_evm_call(self, req: EvmCallRequest) -> SignTransactionResponse:
        """Sign an EVM/TRON contract call, ABI-encoding ``data`` from the signature + args."""
        try:
            data = encode_evm_call_hex(req.method, *req.args)
        except Exception as err:  # noqa: BLE001 - add call context
            raise CryptoChiefError(f"cryptochief: encode call {req.method!r}: {err}") from err
        return await self.sign(
            SignTransactionRequest(
                network=req.network,
                from_address=req.from_address,
                type=TxType.CONTRACT.value,
                url_callback=req.url_callback,
                calls=[ContractCall(to=req.contract, value=_value_string(req.value), data=data)],
            )
        )

    async def sign_tron_call(self, req: EvmCallRequest) -> SignTransactionResponse:
        """Alias for :meth:`sign_evm_call` - TRON shares the EVM ABI encoding."""
        return await self.sign_evm_call(req)

    async def erc20_transfer(self, req: Erc20TransferRequest) -> SignTransactionResponse:
        """One-liner for an ERC-20 / TRC-20 ``transfer(address,uint256)``."""
        return await self.sign_evm_call(
            EvmCallRequest(
                network=req.network,
                from_address=req.from_address,
                contract=req.token_contract,
                method="transfer(address,uint256)",
                args=[req.recipient, req.amount],
                url_callback=req.url_callback,
            )
        )

    async def sign_anchor_call(self, req: AnchorCallRequest) -> SignTransactionResponse:
        """Sign an Anchor program call (8-byte discriminator + Borsh-encoded args)."""
        try:
            data = encode_anchor_instruction(req.method, *req.args)
        except Exception as err:  # noqa: BLE001 - add call context
            raise CryptoChiefError(
                f"cryptochief: encode anchor instruction {req.method!r}: {err}"
            ) from err
        return await self.sign(
            SignTransactionRequest(
                network=req.network,
                from_address=req.from_address,
                type=TxType.CONTRACT.value,
                url_callback=req.url_callback,
                calls=[ContractCall(to=req.program, data=_b64(data), accounts=req.accounts)],
            )
        )

    async def sign_solana_call(self, req: SolanaCallRequest) -> SignTransactionResponse:
        """Sign a non-Anchor Solana program call with raw instruction bytes."""
        return await self.sign(
            SignTransactionRequest(
                network=req.network,
                from_address=req.from_address,
                type=TxType.CONTRACT.value,
                url_callback=req.url_callback,
                calls=[
                    ContractCall(
                        to=req.program, data=_b64(req.instruction_data), accounts=req.accounts
                    )
                ],
            )
        )

    async def sign_ton_call(self, req: TonCallRequest) -> SignTransactionResponse:
        """Sign a TON contract call from a pre-built BoC body cell."""
        return await self.sign(
            SignTransactionRequest(
                network=req.network,
                from_address=req.from_address,
                type=TxType.CONTRACT.value,
                url_callback=req.url_callback,
                calls=[
                    ContractCall(
                        to=req.contract,
                        value=_value_string(req.value),
                        data=_b64(req.body_cell),
                        bounce=req.bounce,
                    )
                ],
            )
        )

    async def jetton_transfer(self, req: JettonTransferRequest) -> SignTransactionResponse:
        """Transfer Jetton tokens.

        Builds the TEP-74 transfer body, resolves the sender's Jetton wallet (via
        RPC if not supplied), and picks a sensible gas budget automatically.
        """
        if not req.recipient:
            raise CryptoChiefError("cryptochief: jetton_transfer: recipient required")
        if not req.jetton_master and not req.jetton_wallet_address:
            raise CryptoChiefError(
                "cryptochief: jetton_transfer: jetton_master or jetton_wallet_address required"
            )
        rpc = self._client.ton_rpc()

        if req.jetton_wallet_address:
            jetton_wallet = req.jetton_wallet_address
        else:
            assert req.jetton_master  # guaranteed by the check above
            jetton_wallet = await rpc.lookup_jetton_wallet(req.jetton_master, req.from_address)

        destination = parse_ton_addr(req.recipient)
        response_dest = parse_ton_addr(req.response_destination or req.from_address)
        forward_payload = build_text_comment_cell(req.memo) if req.memo else None
        forward_ton = req.forward_ton_amount
        if forward_ton is None:
            forward_ton = 1 if req.memo else 0

        body_cell = build_jetton_transfer_body(
            query_id=req.query_id or 0,
            amount=req.amount,
            destination=destination,
            response_dest=response_dest,
            forward_ton=forward_ton,
            forward_payload=forward_payload,
        )

        attached = req.attached_ton
        if attached is None:
            attached = _JETTON_ATTACHED_NEW_WALLET
            if req.jetton_master and await rpc.has_jetton_wallet(req.jetton_master, req.recipient):
                attached = _JETTON_ATTACHED_EXISTING_WALLET

        return await self.sign_ton_call(
            TonCallRequest(
                network=req.network,
                from_address=req.from_address,
                contract=jetton_wallet,
                body_cell=body_cell,
                value=attached,
                bounce=True,
                url_callback=req.url_callback,
            )
        )

    async def nft_transfer(self, req: NftTransferRequest) -> SignTransactionResponse:
        """Transfer ownership of an NFT item (TEP-62 transfer body)."""
        if not req.nft_item or not req.new_owner:
            raise CryptoChiefError("cryptochief: nft_transfer: nft_item and new_owner required")
        new_owner = parse_ton_addr(req.new_owner)
        response_dest = parse_ton_addr(req.response_destination or req.from_address)
        body_cell = build_nft_transfer_body(
            query_id=req.query_id or 0,
            new_owner=new_owner,
            response_dest=response_dest,
            forward_ton=req.forward_ton_amount or 0,
        )
        return await self.sign_ton_call(
            TonCallRequest(
                network=req.network,
                from_address=req.from_address,
                contract=req.nft_item,
                body_cell=body_cell,
                value=req.attached_ton or _NFT_ATTACHED_DEFAULT,
                bounce=True,
                url_callback=req.url_callback,
            )
        )

    async def send_ton_comment(self, req: TonCommentRequest) -> SignTransactionResponse:
        """Send TON with a text comment (the note every wallet displays)."""
        if not req.recipient:
            raise CryptoChiefError("cryptochief: send_ton_comment: recipient required")
        body_cell = build_text_comment_body(req.text)
        return await self.sign_ton_call(
            TonCallRequest(
                network=req.network,
                from_address=req.from_address,
                contract=req.recipient,
                body_cell=body_cell,
                value=req.amount_ton or 0,
                bounce=False,
                url_callback=req.url_callback,
            )
        )
