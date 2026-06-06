"""Contract-call encoders: EVM/TRON ABI, Solana Borsh/Anchor, base58, TRON addresses."""

from __future__ import annotations

from .base58 import base58_decode, base58_encode
from .borsh import (
    BorshValue,
    anchor_discriminator,
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
    decode_solana_pubkey,
    encode_anchor_instruction,
)
from .evm_abi import (
    canonical_signature,
    encode_evm_call,
    encode_evm_call_hex,
    evm_selector,
)
from .keccak import keccak_256
from .tron_address import hex_to_tron, tron_to_hex

__all__ = [
    "base58_decode",
    "base58_encode",
    "BorshValue",
    "anchor_discriminator",
    "borsh_bool",
    "borsh_bytes",
    "borsh_fixed_bytes",
    "borsh_i8",
    "borsh_i16",
    "borsh_i32",
    "borsh_i64",
    "borsh_option",
    "borsh_pubkey",
    "borsh_string",
    "borsh_struct",
    "borsh_u8",
    "borsh_u16",
    "borsh_u32",
    "borsh_u64",
    "borsh_u128",
    "borsh_vec",
    "decode_solana_pubkey",
    "encode_anchor_instruction",
    "canonical_signature",
    "encode_evm_call",
    "encode_evm_call_hex",
    "evm_selector",
    "keccak_256",
    "hex_to_tron",
    "tron_to_hex",
]
