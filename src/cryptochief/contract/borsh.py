"""Borsh encoding + Anchor instruction building for Solana.

Anchor instruction data is ``[8-byte discriminator][Borsh-encoded args]``. Borsh
has no on-wire type tags, so the caller must describe each argument's type
explicitly - the ``borsh_*`` constructors below force that. Each returns a
:class:`BorshValue`; pass them to :func:`encode_anchor_instruction`.
"""

from __future__ import annotations

import hashlib
from typing import List, Optional, Union

from ..errors import CryptoChiefError
from .base58 import base58_decode


class BorshError(CryptoChiefError):
    def __init__(self, message: str) -> None:
        super().__init__(f"cryptochief/anchor: {message}")


class BorshValue:
    """A value paired with its Borsh encoding, ready to concatenate."""

    __slots__ = ("_data",)

    def __init__(self, data: bytes) -> None:
        self._data = data

    def encode(self) -> bytes:
        return self._data


def _le(value: int, width: int) -> bytes:
    return (value & ((1 << (8 * width)) - 1)).to_bytes(width, "little")


# Unsigned little-endian integers.
def borsh_u8(n: int) -> BorshValue:
    return BorshValue(_le(n, 1))


def borsh_u16(n: int) -> BorshValue:
    return BorshValue(_le(n, 2))


def borsh_u32(n: int) -> BorshValue:
    return BorshValue(_le(n, 4))


def borsh_u64(n: int) -> BorshValue:
    return BorshValue(_le(n, 8))


# Signed little-endian integers (two's complement - same wire bytes as unsigned).
borsh_i8 = borsh_u8
borsh_i16 = borsh_u16
borsh_i32 = borsh_u32
borsh_i64 = borsh_u64


def borsh_u128(n: int) -> BorshValue:
    """128-bit unsigned little-endian. Must be non-negative and < 2^128."""
    if n < 0:
        raise BorshError("u128 negative")
    if n >= (1 << 128):
        raise BorshError("u128 overflow")
    return BorshValue(_le(n, 16))


def borsh_bool(b: bool) -> BorshValue:
    """1-byte boolean (0x00 / 0x01)."""
    return BorshValue(b"\x01" if b else b"\x00")


def borsh_string(s: str) -> BorshValue:
    """UTF-8 string: 4-byte LE length prefix + bytes."""
    data = s.encode("utf-8")
    return BorshValue(_le(len(data), 4) + data)


def borsh_bytes(b: bytes) -> BorshValue:
    """Raw byte slice: 4-byte LE length prefix + bytes (same wire form as a string)."""
    b = bytes(b)
    return BorshValue(_le(len(b), 4) + b)


def borsh_fixed_bytes(b: bytes, n: int) -> BorshValue:
    """Fixed-length bytes with NO length prefix (Anchor's ``[u8; N]``)."""
    b = bytes(b)
    if len(b) != n:
        raise BorshError(f"borsh_fixed_bytes: expected {n} bytes, got {len(b)}")
    return BorshValue(b)


def borsh_pubkey(pk: Union[str, bytes]) -> BorshValue:
    """A Solana 32-byte pubkey (base58 string or raw 32 bytes)."""
    return BorshValue(decode_solana_pubkey(pk))


def borsh_option(inner: Optional[BorshValue]) -> BorshValue:
    """Nullable value: ``None`` -> 0x00; otherwise 0x01 + inner encoding."""
    if inner is None:
        return BorshValue(b"\x00")
    return BorshValue(b"\x01" + inner.encode())


def borsh_vec(items: List[BorshValue]) -> BorshValue:
    """Homogeneous ``Vec<T>``: 4-byte LE length + elements."""
    body = b"".join(it.encode() for it in items)
    return BorshValue(_le(len(items), 4) + body)


def borsh_struct(*fields: BorshValue) -> BorshValue:
    """Heterogeneous struct / tuple: fields in order, no length prefix."""
    return BorshValue(b"".join(f.encode() for f in fields))


def anchor_discriminator(method: str) -> bytes:
    """The 8-byte Anchor instruction discriminator: ``sha256("global:" + method)[:8]``."""
    return hashlib.sha256(f"global:{method}".encode("utf-8")).digest()[:8]


def encode_anchor_instruction(method: str, *args: BorshValue) -> bytes:
    """Raw Anchor instruction data: 8-byte discriminator + Borsh-encoded args."""
    parts = [anchor_discriminator(method)]
    parts.extend(a.encode() for a in args)
    return b"".join(parts)


def decode_solana_pubkey(pk: Union[str, bytes]) -> bytes:
    """Decode a Solana pubkey (base58 string or raw 32 bytes) to its 32-byte form."""
    if isinstance(pk, (bytes, bytearray)):
        if len(pk) != 32:
            raise BorshError(f"solana pubkey: want 32 bytes, got {len(pk)}")
        return bytes(pk)
    raw = base58_decode(pk)
    if len(raw) != 32:
        raise BorshError(f"solana pubkey: decoded length {len(raw)}, want 32")
    return raw
