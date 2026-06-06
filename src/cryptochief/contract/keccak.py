"""Keccak-256 (Ethereum's legacy hash, distinct from NIST SHA3-256).

Used only to derive EVM/TRON function selectors. Backed by pycryptodome's
well-tested implementation.
"""

from __future__ import annotations

from Cryptodome.Hash import keccak as _keccak


def keccak_256(data: bytes) -> bytes:
    """Return the 32-byte Keccak-256 digest of ``data``."""
    h = _keccak.new(digest_bits=256)
    h.update(data)
    return h.digest()
