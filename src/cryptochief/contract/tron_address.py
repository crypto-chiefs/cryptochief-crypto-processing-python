"""TRON address conversion (Base58Check <-> 0x41 hex)."""

from __future__ import annotations

import hashlib

from ..errors import CryptoChiefError
from .base58 import base58_decode, base58_encode


def _sha256d(b: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(b).digest()).digest()


def tron_to_hex(base58_addr: str) -> str:
    """Convert a TRON base58 address (``T...``) to its 0x41-prefixed 21-byte hex.

    Validates the Base58Check (double-SHA-256) checksum.

    >>> tron_to_hex("TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t")
    '0x41a614f803b6fd780986a42c78ec9c7f77e6ded13c'
    """
    decoded = base58_decode(base58_addr.strip())
    if len(decoded) != 25:
        raise CryptoChiefError(f"cryptochief/tron: decoded length {len(decoded)}, want 25")
    payload = decoded[:21]
    checksum = decoded[21:]
    if payload[0] != 0x41:
        raise CryptoChiefError(f"cryptochief/tron: leading byte 0x{payload[0]:02x}, want 0x41")
    if checksum != _sha256d(payload)[:4]:
        raise CryptoChiefError("cryptochief/tron: checksum mismatch")
    return "0x" + payload.hex()


def hex_to_tron(hex_addr: str) -> str:
    """Convert a 20-byte EVM-style hex (or a 0x41-prefixed 21-byte TRON hex) to base58.

    A 20-byte input is prefixed with ``0x41`` automatically.
    """
    s = hex_addr.strip()
    if s[:2].lower() == "0x":
        s = s[2:]
    try:
        raw = bytes.fromhex(s)
    except ValueError as err:
        raise CryptoChiefError(f"cryptochief/tron: bad hex {hex_addr!r}: {err}") from err
    if len(raw) == 20:
        payload = b"\x41" + raw
    elif len(raw) == 21:
        if raw[0] != 0x41:
            raise CryptoChiefError(
                f"cryptochief/tron: 21-byte input must start with 0x41, got 0x{raw[0]:02x}"
            )
        payload = raw
    else:
        raise CryptoChiefError(
            f"cryptochief/tron: want 20- or 21-byte hex address, got {len(raw)} bytes"
        )
    checksum = _sha256d(payload)[:4]
    return base58_encode(payload + checksum)
