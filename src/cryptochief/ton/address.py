"""Offline parsing / validation of TON addresses.

TON addresses come in three skins, all wrapping the same 33 bytes (1 tag +
1 workchain + 32 hash):

* user-friendly bounceable     ``EQ...`` (mainnet) / ``kQ...`` (testnet)
* user-friendly non-bounceable ``UQ...`` (mainnet) / ``0Q...`` (testnet)
* raw                          ``<workchain>:<32-byte-hex>``

The user-friendly forms add a 2-byte CRC16-XMODEM checksum, which this parser
validates. No network access - this is purely for local validation / display.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

from ..errors import CryptoChiefError


@dataclass
class TonAddress:
    workchain: int
    hash: bytes  # 32 bytes
    bounceable: bool
    testnet: bool


def crc16_xmodem(data: bytes) -> int:
    """CRC-16/XMODEM (poly 0x1021, init 0x0000, non-reflected) - TON's checksum."""
    crc = 0
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc & 0xFFFF


def _parse_raw(s: str, colon: int) -> TonAddress:
    try:
        wc = int(s[:colon], 10)
    except ValueError as err:
        raise CryptoChiefError(f"cryptochief/ton: bad raw workchain {s[:colon]!r}") from err
    if wc < -128 or wc > 127:
        raise CryptoChiefError(f"cryptochief/ton: bad raw workchain {s[:colon]!r}")
    hash_hex = s[colon + 1 :]
    if len(hash_hex) != 64:
        raise CryptoChiefError(f"cryptochief/ton: hash hex length {len(hash_hex)}, want 64")
    try:
        h = bytes.fromhex(hash_hex)
    except ValueError as err:
        raise CryptoChiefError("cryptochief/ton: bad hash hex") from err
    return TonAddress(workchain=wc, hash=h, bounceable=True, testnet=False)


def _parse_friendly(s: str) -> TonAddress:
    if len(s) != 48:
        raise CryptoChiefError(f"cryptochief/ton: user-friendly address length {len(s)}, want 48")
    # TON uses URL-safe base64; accept the standard alphabet too.
    try:
        raw = base64.b64decode(s.replace("-", "+").replace("_", "/"))
    except (ValueError, base64.binascii.Error) as err:  # type: ignore[attr-defined]
        raise CryptoChiefError(f"cryptochief/ton: bad base64 address: {err}") from err
    if len(raw) != 36:
        raise CryptoChiefError(f"cryptochief/ton: decoded length {len(raw)}, want 36")
    want = crc16_xmodem(raw[:34])
    got = (raw[34] << 8) | raw[35]
    if want != got:
        raise CryptoChiefError("cryptochief/ton: CRC mismatch")
    tag = raw[0]
    workchain = raw[1] - 256 if raw[1] > 127 else raw[1]  # sign-extend to int8
    return TonAddress(
        workchain=workchain,
        hash=raw[2:34],
        bounceable=(tag & 0x40) == 0,
        testnet=(tag & 0x80) != 0,
    )


def parse_ton_address(value: str) -> TonAddress:
    """Parse any of the three TON address forms; raises on CRC / length errors."""
    s = value.strip()
    if s == "":
        raise CryptoChiefError("cryptochief/ton: empty address")
    colon = s.find(":")
    if colon > 0:
        return _parse_raw(s, colon)
    return _parse_friendly(s)


def ton_address_to_string(a: TonAddress) -> str:
    """Render the user-friendly form (URL-safe base64, no padding)."""
    tag = 0x11 if a.bounceable else 0x51
    if a.testnet:
        tag |= 0x80
    buf = bytearray(36)
    buf[0] = tag
    buf[1] = a.workchain & 0xFF
    buf[2:34] = a.hash[:32]
    crc = crc16_xmodem(bytes(buf[:34]))
    buf[34] = crc >> 8
    buf[35] = crc & 0xFF
    return base64.urlsafe_b64encode(bytes(buf)).decode("ascii").rstrip("=")


def ton_address_to_raw(a: TonAddress) -> str:
    """Render the raw ``workchain:hex`` form."""
    return f"{a.workchain}:{a.hash.hex()}"
