"""Crypto Chief Python SDK - the official async client for the
`Crypto Chief <https://crypto-chief.com/processing/>`_ crypto processing API.

Accept crypto payments, send single and mass payouts, sign on-chain
transactions and smart-contract calls, manage wallets, convert fiat to crypto,
and verify webhooks across Ethereum, Tron, TON, Solana, Bitcoin, XRP and 20+
more blockchains.

>>> import asyncio
>>> from cryptochief import CryptoChiefClient, Chain
>>> from cryptochief import EstimatePayoutRequest
>>>
>>> async def main():
...     async with CryptoChiefClient(merchant_id="M", api_key="K") as client:
...         est = await client.payouts.estimate(EstimatePayoutRequest(
...             network=Chain.ETH_SEPOLIA, coin="ETH", amount="0.0001",
...             to_address="0x...",
...         ))
...         print(est.amount_to_receive)
>>> asyncio.run(main())  # doctest: +SKIP
"""

from __future__ import annotations

from ._version import __version__
from .amount import InvalidAmountError, base_to_human, human_to_base, nano_ton
from .assets import Asset, AssetsPolicy
from .chains import Chain, ChainFamily, chain_family, supports_contract_calls
from .client import DEFAULT_BASE_URL, VERSION, CryptoChiefClient
from .contract import (
    BorshValue,
    anchor_discriminator,
    base58_decode,
    base58_encode,
    borsh_bool,
    borsh_bytes,
    borsh_fixed_bytes,
    borsh_i8,
    borsh_i16,
    borsh_i32,
    borsh_i64,
    borsh_option,
    borsh_pubkey,
    borsh_string,
    borsh_struct,
    borsh_u8,
    borsh_u16,
    borsh_u32,
    borsh_u64,
    borsh_u128,
    borsh_vec,
    canonical_signature,
    decode_solana_pubkey,
    encode_anchor_instruction,
    encode_evm_call,
    encode_evm_call_hex,
    evm_selector,
    hex_to_tron,
    keccak_256,
    tron_to_hex,
)
from .errors import APIError, CryptoChiefError, ErrorCode, is_api_error, is_retryable
from .pagination import HistoryMeta, HistoryQuery
from .poll import PollTimeoutError, wait_for_terminal
from .rsa import (
    RsaKeyNotConfiguredError,
    decrypt_rsa_oaep,
    load_rsa_private_key_file,
    load_rsa_private_key_pem,
)
from .services.blockchain import (
    AvailableContract,
    AvailableContractsResponse,
    BlockchainService,
    TxStatusRow,
    WalletBalanceRow,
)
from .services.currencies import ConvertRequest, ConvertResponse, CurrenciesService
from .services.payins import (
    CoinOption,
    CreatePayInRequest,
    PayIn,
    PayInHistoryResponse,
    PayInMode,
    PayInsService,
    PayInStatus,
    SelectAssetRequest,
    is_payin_terminal,
)
from .services.payouts import (
    BatchItemResult,
    BatchPayoutRequest,
    BatchPayoutResponse,
    EstimatePayoutRequest,
    EstimatePayoutResponse,
    ExecutePayoutRequest,
    PayoutFeeInfo,
    PayoutHistoryResponse,
    PayoutInfo,
    PayoutsService,
    PayoutSource,
    PayoutStatus,
    is_payout_terminal,
)
from .services.static_deposits import (
    StaticDeposit,
    StaticDepositHistoryQuery,
    StaticDepositHistoryResponse,
    StaticDepositsService,
    StaticDepositStatus,
)
from .services.sweeps import (
    ForceSweepResponse,
    Sweep,
    SweepHistoryQuery,
    SweepHistoryResponse,
    SweepMode,
    SweepsService,
)
from .services.transactions import (
    AnchorCallRequest,
    ContractCall,
    Erc20TransferRequest,
    EvmCallRequest,
    ExecuteTransactionRequest,
    JettonTransferRequest,
    NftTransferRequest,
    SignTransactionRequest,
    SignTransactionResponse,
    SolanaAccount,
    SolanaCallRequest,
    TonCallRequest,
    TonCommentRequest,
    TransactionHistoryResponse,
    TransactionInfo,
    TransactionsService,
    TxStatus,
    TxType,
    is_transaction_terminal,
)
from .services.wallets import (
    GenerateWalletRequest,
    ListWalletsResponse,
    Wallet,
    WalletCoinBalance,
    WalletsService,
    WalletType,
)
from .services.withdrawals import Withdrawal, WithdrawalHistoryResponse, WithdrawalsService
from .sign import canonical_json, sign, sign_value
from .ton import (
    TonAddress,
    crc16_xmodem,
    parse_ton_address,
    ton_address_to_raw,
    ton_address_to_string,
)
from .webhook import (
    WEBHOOK_HEADER,
    WEBHOOK_SENDER_IPS,
    PayInWebhookEvent,
    PayoutWebhookEvent,
    StaticDepositWebhookEvent,
    TransactionWebhookEvent,
    WebhookSignatureError,
    coerce_webhook_event,
    parse_webhook_event,
    verify_webhook_signature,
)

__all__ = [
    "__version__",
    # Client
    "CryptoChiefClient",
    "VERSION",
    "DEFAULT_BASE_URL",
    # Errors
    "CryptoChiefError",
    "APIError",
    "ErrorCode",
    "is_api_error",
    "is_retryable",
    # Signing
    "canonical_json",
    "sign",
    "sign_value",
    # Amounts
    "human_to_base",
    "base_to_human",
    "nano_ton",
    "InvalidAmountError",
    # Chains / assets / pagination
    "Chain",
    "ChainFamily",
    "chain_family",
    "supports_contract_calls",
    "Asset",
    "AssetsPolicy",
    "HistoryQuery",
    "HistoryMeta",
    # Polling
    "wait_for_terminal",
    "PollTimeoutError",
    # RSA
    "load_rsa_private_key_pem",
    "load_rsa_private_key_file",
    "decrypt_rsa_oaep",
    "RsaKeyNotConfiguredError",
    # Webhooks
    "verify_webhook_signature",
    "parse_webhook_event",
    "coerce_webhook_event",
    "WebhookSignatureError",
    "WEBHOOK_HEADER",
    "WEBHOOK_SENDER_IPS",
    "PayoutWebhookEvent",
    "TransactionWebhookEvent",
    "PayInWebhookEvent",
    "StaticDepositWebhookEvent",
    # Services
    "PayoutsService",
    "TransactionsService",
    "PayInsService",
    "WalletsService",
    "SweepsService",
    "WithdrawalsService",
    "StaticDepositsService",
    "BlockchainService",
    "CurrenciesService",
    # Payout types
    "EstimatePayoutRequest",
    "ExecutePayoutRequest",
    "EstimatePayoutResponse",
    "PayoutInfo",
    "PayoutFeeInfo",
    "PayoutSource",
    "PayoutHistoryResponse",
    "BatchPayoutRequest",
    "BatchPayoutResponse",
    "BatchItemResult",
    "PayoutStatus",
    "is_payout_terminal",
    # Transaction types
    "SignTransactionRequest",
    "SignTransactionResponse",
    "ExecuteTransactionRequest",
    "TransactionInfo",
    "TransactionHistoryResponse",
    "ContractCall",
    "SolanaAccount",
    "EvmCallRequest",
    "Erc20TransferRequest",
    "AnchorCallRequest",
    "SolanaCallRequest",
    "TonCallRequest",
    "JettonTransferRequest",
    "NftTransferRequest",
    "TonCommentRequest",
    "TxType",
    "TxStatus",
    "is_transaction_terminal",
    # Pay-in types
    "CreatePayInRequest",
    "SelectAssetRequest",
    "PayIn",
    "CoinOption",
    "PayInHistoryResponse",
    "PayInMode",
    "PayInStatus",
    "is_payin_terminal",
    # Wallet types
    "GenerateWalletRequest",
    "Wallet",
    "WalletCoinBalance",
    "ListWalletsResponse",
    "WalletType",
    # Sweep types
    "Sweep",
    "SweepHistoryQuery",
    "SweepHistoryResponse",
    "ForceSweepResponse",
    "SweepMode",
    # Withdrawal types
    "Withdrawal",
    "WithdrawalHistoryResponse",
    # Static deposit types
    "StaticDeposit",
    "StaticDepositHistoryQuery",
    "StaticDepositHistoryResponse",
    "StaticDepositStatus",
    # Blockchain types
    "AvailableContract",
    "AvailableContractsResponse",
    "WalletBalanceRow",
    "TxStatusRow",
    # Currency types
    "ConvertRequest",
    "ConvertResponse",
    # Contract encoders
    "encode_evm_call",
    "encode_evm_call_hex",
    "evm_selector",
    "canonical_signature",
    "keccak_256",
    "BorshValue",
    "borsh_u8",
    "borsh_u16",
    "borsh_u32",
    "borsh_u64",
    "borsh_i8",
    "borsh_i16",
    "borsh_i32",
    "borsh_i64",
    "borsh_u128",
    "borsh_bool",
    "borsh_string",
    "borsh_bytes",
    "borsh_fixed_bytes",
    "borsh_pubkey",
    "borsh_option",
    "borsh_vec",
    "borsh_struct",
    "anchor_discriminator",
    "encode_anchor_instruction",
    "decode_solana_pubkey",
    "tron_to_hex",
    "hex_to_tron",
    "base58_encode",
    "base58_decode",
    # TON address utilities (offline)
    "parse_ton_address",
    "ton_address_to_string",
    "ton_address_to_raw",
    "crc16_xmodem",
    "TonAddress",
]
