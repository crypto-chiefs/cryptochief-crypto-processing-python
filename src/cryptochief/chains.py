"""Chain codes and protocol families.

:class:`Chain` is the value of the ``network`` / ``chain`` / ``network_code``
fields across the API; :class:`ChainFamily` (the ``chain_family`` field) groups
chains by underlying protocol and drives capability checks such as "does this
chain accept contract calls?".

Both are ``str`` enums: a member compares equal to its wire string, and any
plain string is accepted wherever a chain is expected, so new chains work before
this SDK is updated.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional


class Chain(str, Enum):
    """Chain codes the API currently supports."""

    ETH_MAINNET = "ETH_MAINNET"
    ETH_SEPOLIA = "ETH_SEPOLIA"
    BSC_MAINNET = "BSC_MAINNET"
    BSC_TESTNET = "BSC_TESTNET"
    POLYGON_MAINNET = "POLYGON_MAINNET"
    POLYGON_AMOY = "POLYGON_AMOY"
    ARBITRUM_ONE = "ARBITRUM_ONE"
    ARBITRUM_SEPOLIA = "ARBITRUM_SEPOLIA"
    OPTIMISM_MAINNET = "OPTIMISM_MAINNET"
    OPTIMISM_SEPOLIA = "OPTIMISM_SEPOLIA"
    AVAX_MAINNET = "AVAX_MAINNET"
    AVAX_TESTNET = "AVAX_TESTNET"

    BTC_MAINNET = "BTC_MAINNET"
    BTC_TESTNET_4 = "BTC_TESTNET_4"
    LITECOIN_MAINNET = "LITECOIN_MAINNET"
    BITCOIN_CASH_MAINNET = "BITCOIN_CASH_MAINNET"
    DOGECOIN_MAINNET = "DOGECOIN_MAINNET"

    TRON_MAINNET = "TRON_MAINNET"
    TRON_NILE = "TRON_NILE"

    SOLANA_MAINNET = "SOLANA_MAINNET"
    SOLANA_DEVNET = "SOLANA_DEVNET"

    TON_MAINNET = "TON_MAINNET"
    TON_TESTNET = "TON_TESTNET"

    XRP_MAINNET = "XRP_MAINNET"
    XRP_TESTNET = "XRP_TESTNET"


class ChainFamily(str, Enum):
    """Protocol families (the ``chain_family`` field in API responses)."""

    EVM = "EVM"
    TRON = "TRON"
    SOLANA = "SOLANA"
    XRP_LEDGER = "XRP_LEDGER"
    TON = "TON"
    BTC_UTXO = "BTC_UTXO"
    BTC_UTXO_TESTNET = "BTC_UTXO_TESTNET"
    DOGECOIN_UTXO = "DOGECOIN_UTXO"
    BTC_CASH_UTXO = "BTC_CASH_UTXO"
    LITECOIN_UTXO = "LITECOIN_UTXO"


_CHAIN_TO_FAMILY = {
    Chain.ETH_MAINNET: ChainFamily.EVM,
    Chain.ETH_SEPOLIA: ChainFamily.EVM,
    Chain.BSC_MAINNET: ChainFamily.EVM,
    Chain.BSC_TESTNET: ChainFamily.EVM,
    Chain.POLYGON_MAINNET: ChainFamily.EVM,
    Chain.POLYGON_AMOY: ChainFamily.EVM,
    Chain.ARBITRUM_ONE: ChainFamily.EVM,
    Chain.ARBITRUM_SEPOLIA: ChainFamily.EVM,
    Chain.OPTIMISM_MAINNET: ChainFamily.EVM,
    Chain.OPTIMISM_SEPOLIA: ChainFamily.EVM,
    Chain.AVAX_MAINNET: ChainFamily.EVM,
    Chain.AVAX_TESTNET: ChainFamily.EVM,
    Chain.BTC_MAINNET: ChainFamily.BTC_UTXO,
    Chain.BTC_TESTNET_4: ChainFamily.BTC_UTXO_TESTNET,
    Chain.LITECOIN_MAINNET: ChainFamily.LITECOIN_UTXO,
    Chain.BITCOIN_CASH_MAINNET: ChainFamily.BTC_CASH_UTXO,
    Chain.DOGECOIN_MAINNET: ChainFamily.DOGECOIN_UTXO,
    Chain.TRON_MAINNET: ChainFamily.TRON,
    Chain.TRON_NILE: ChainFamily.TRON,
    Chain.SOLANA_MAINNET: ChainFamily.SOLANA,
    Chain.SOLANA_DEVNET: ChainFamily.SOLANA,
    Chain.TON_MAINNET: ChainFamily.TON,
    Chain.TON_TESTNET: ChainFamily.TON,
    Chain.XRP_MAINNET: ChainFamily.XRP_LEDGER,
    Chain.XRP_TESTNET: ChainFamily.XRP_LEDGER,
}
# Allow plain-string lookups too (e.g. the value off a response).
_CHAIN_TO_FAMILY_STR = {k.value: v for k, v in _CHAIN_TO_FAMILY.items()}


def chain_family(chain: str) -> Optional[ChainFamily]:
    """Return the protocol family for a chain, or ``None`` if unrecognized."""
    return _CHAIN_TO_FAMILY_STR.get(str(chain))


def supports_contract_calls(family: str) -> bool:
    """Whether a chain family accepts the ``contract`` transaction type.

    Only EVM, TRON, Solana, and TON do.
    """
    return family in (
        ChainFamily.EVM,
        ChainFamily.TRON,
        ChainFamily.SOLANA,
        ChainFamily.TON,
    )
