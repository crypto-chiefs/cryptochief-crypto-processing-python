import pytest

from cryptochief import base58_decode, base58_encode, hex_to_tron, tron_to_hex

CASES = [
    ("TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t", "0x41a614f803b6fd780986a42c78ec9c7f77e6ded13c"),  # USDT
    ("TSSMHYeV2uE9qYH95DqyoCuNCzEL1NvU3S", "0x41b4a428ab7092c2f1395f376ce297033b3bb446c1"),  # SUN
]


@pytest.mark.parametrize("base58,hexv", CASES)
def test_round_trip(base58, hexv):
    assert tron_to_hex(base58).lower() == hexv.lower()
    assert hex_to_tron(hexv) == base58
    # 20-byte form (strip "0x41") round-trips via the auto 0x41 prefix.
    assert hex_to_tron("0x" + hexv[4:]) == base58


def test_rejects_bad_checksum():
    with pytest.raises(Exception):
        tron_to_hex("TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6T")


@pytest.mark.parametrize("bad", ["", "not-base58-0OIl", "TR7NHqjeKQxGTCi"])
def test_rejects_bad_base58(bad):
    with pytest.raises(Exception):
        tron_to_hex(bad)


@pytest.mark.parametrize("bad", ["", "0xzzz", "0xabcd", "0x42" + "ab" * 20])
def test_rejects_bad_hex(bad):
    with pytest.raises(Exception):
        hex_to_tron(bad)


def test_base58_round_trip_preserves_leading_zeros():
    inputs = [
        bytes([0x00]),
        bytes([0x00, 0x00, 0xFF]),
        bytes.fromhex("41a614f803b6fd780986a42c78ec9c7f77e6ded13cb83afd16"),
    ]
    for b in inputs:
        assert base58_decode(base58_encode(b)) == b
