import pytest

from cryptochief import (
    TonAddress,
    crc16_xmodem,
    parse_ton_address,
    ton_address_to_raw,
    ton_address_to_string,
)

USDT_MASTER = "EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs"
HASH_HEX = "b113a994b5024a16719f69139328eb759596c38a25f59028b146fecdc3621dfe"


def test_round_trip_user_friendly_bounceable():
    a = parse_ton_address(USDT_MASTER)
    assert a.workchain == 0
    assert a.bounceable is True
    assert a.testnet is False
    assert ton_address_to_string(a) == USDT_MASTER


def test_parse_raw_form():
    a = parse_ton_address("0:" + HASH_HEX)
    assert a.hash == bytes.fromhex(HASH_HEX)
    assert ton_address_to_raw(a) == "0:" + HASH_HEX


def test_user_friendly_and_raw_agree():
    a1 = parse_ton_address(USDT_MASTER)
    a2 = parse_ton_address(ton_address_to_raw(a1))
    assert a2.workchain == a1.workchain
    assert a2.hash == a1.hash


def test_uq_non_bounceable_round_trip():
    a = TonAddress(workchain=0, hash=bytes.fromhex(HASH_HEX), bounceable=False, testnet=False)
    uq = ton_address_to_string(a)
    assert uq.startswith("UQ")
    back = parse_ton_address(uq)
    assert back.bounceable is False
    assert back.hash == a.hash


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "not-an-address",
        "EQ_too_short",
        "EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_AAA",  # corrupt CRC
        "foo:" + HASH_HEX,  # bad workchain
        "0:abcd",  # bad hash length
    ],
)
def test_rejects_malformed(bad):
    with pytest.raises(Exception):
        parse_ton_address(bad)


def test_crc16_canonical_vector():
    assert crc16_xmodem(b"123456789") == 0x31C3
    assert crc16_xmodem(b"") == 0
