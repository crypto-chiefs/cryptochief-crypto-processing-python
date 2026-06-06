"""Base58 (Bitcoin / Tron / Solana alphabet).

Shared by the TRON address codec and Solana pubkey decoding. Pure ``int``
arithmetic - no external dependency.
"""

from __future__ import annotations

from ..errors import CryptoChiefError

_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_DECODE = {c: i for i, c in enumerate(_ALPHABET)}


def base58_encode(data: bytes) -> str:
    zeros = 0
    while zeros < len(data) and data[zeros] == 0:
        zeros += 1
    num = int.from_bytes(data, "big")
    out = ""
    while num > 0:
        num, rem = divmod(num, 58)
        out = _ALPHABET[rem] + out
    return _ALPHABET[0] * zeros + out


def base58_decode(s: str) -> bytes:
    if s == "":
        raise CryptoChiefError("cryptochief: base58: empty input")
    zeros = 0
    while zeros < len(s) and s[zeros] == _ALPHABET[0]:
        zeros += 1
    num = 0
    for ch in s:
        v = _DECODE.get(ch, -1)
        if v < 0:
            raise CryptoChiefError(f"cryptochief: base58: invalid char {ch!r}")
        num = num * 58 + v
    body = num.to_bytes((num.bit_length() + 7) // 8, "big") if num > 0 else b""
    return b"\x00" * zeros + body
