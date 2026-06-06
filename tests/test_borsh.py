import hashlib

import pytest

from cryptochief import (
    anchor_discriminator,
    borsh_bool,
    borsh_fixed_bytes,
    borsh_option,
    borsh_pubkey,
    borsh_string,
    borsh_u32,
    borsh_u64,
    borsh_u128,
    borsh_vec,
    encode_anchor_instruction,
)


def test_anchor_discriminator():
    for m in ["initialize", "transfer", "swap", "set_authority"]:
        want = hashlib.sha256(f"global:{m}".encode()).digest()[:8]
        assert anchor_discriminator(m) == want


def test_u64_little_endian():
    assert borsh_u64(1_234_567).encode().hex() == "87d6120000000000"


def test_u128_little_endian():
    b = borsh_u128(1 << 64).encode()
    assert len(b) == 16
    assert b.hex() == "00000000000000000100000000000000"


def test_string():
    assert borsh_string("hello").encode().hex() == "0500000068656c6c6f"


def test_bool():
    assert borsh_bool(True).encode().hex() == "01"
    assert borsh_bool(False).encode().hex() == "00"


def test_vec_u32():
    assert borsh_vec([borsh_u32(1), borsh_u32(2), borsh_u32(3)]).encode().hex() == (
        "03000000" + "01000000" + "02000000" + "03000000"
    )


def test_pubkey_system_program():
    b = borsh_pubkey("11111111111111111111111111111111").encode()
    assert len(b) == 32
    assert b.hex() == "00" * 32


def test_fixed_bytes_and_length_check():
    assert borsh_fixed_bytes(bytes([1, 2, 3, 4]), 4).encode().hex() == "01020304"
    with pytest.raises(Exception):
        borsh_fixed_bytes(bytes([1, 2, 3]), 4)


def test_option_none_some():
    assert borsh_option(None).encode().hex() == "00"
    assert borsh_option(borsh_u32(42)).encode().hex() == "012a000000"


def test_encode_anchor_instruction():
    data = encode_anchor_instruction("transfer", borsh_u64(1_000), borsh_bool(True))
    assert data[:8] == anchor_discriminator("transfer")
    assert data[8:16].hex() == "e803000000000000"  # u64 1000 LE
    assert data[16] == 0x01
    assert len(data) == 17
