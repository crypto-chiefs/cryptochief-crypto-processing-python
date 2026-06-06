import pytest

from cryptochief import encode_evm_call, encode_evm_call_hex, evm_selector


def selhex(sig: str) -> str:
    return evm_selector(sig).hex()


@pytest.mark.parametrize(
    "sig,want",
    [
        ("transfer(address,uint256)", "a9059cbb"),
        ("approve(address,uint256)", "095ea7b3"),
        ("balanceOf(address)", "70a08231"),
        ("totalSupply()", "18160ddd"),
        ("transferFrom(address,address,uint256)", "23b872dd"),
        ("swapExactTokensForTokens(uint256,uint256,address[],address,uint256)", "38ed1739"),
        ("transfer(address,uint)", "a9059cbb"),  # alias uint -> uint256
        ("transfer(address to, uint256 amount)", "a9059cbb"),  # strip names/spaces
    ],
)
def test_well_known_selectors(sig, want):
    assert selhex(sig) == want


def test_erc20_transfer_encoding():
    data = encode_evm_call(
        "transfer(address,uint256)", "0xbcd4042de499d14e55001ccbb24a551f3b954096", 1_000_000
    )
    assert data.hex() == (
        "a9059cbb"
        "000000000000000000000000bcd4042de499d14e55001ccbb24a551f3b954096"
        "00000000000000000000000000000000000000000000000000000000000f4240"
    )


def test_dynamic_arrays_head_tail():
    data = encode_evm_call(
        "multiSend(address[],uint256[])",
        ["0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"],
        [100, 200],
    )
    assert data.hex() == (
        selhex("multiSend(address[],uint256[])")
        + "0000000000000000000000000000000000000000000000000000000000000040"
        + "00000000000000000000000000000000000000000000000000000000000000a0"
        + "0000000000000000000000000000000000000000000000000000000000000002"
        + "000000000000000000000000aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        + "000000000000000000000000bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        + "0000000000000000000000000000000000000000000000000000000000000002"
        + "0000000000000000000000000000000000000000000000000000000000000064"
        + "00000000000000000000000000000000000000000000000000000000000000c8"
    )


def test_dynamic_bytes_and_string():
    data = encode_evm_call("bar(bytes,string)", "0xdeadbeef", "hello")
    assert data.hex() == (
        selhex("bar(bytes,string)")
        + "0000000000000000000000000000000000000000000000000000000000000040"
        + "0000000000000000000000000000000000000000000000000000000000000080"
        + "0000000000000000000000000000000000000000000000000000000000000004"
        + "deadbeef00000000000000000000000000000000000000000000000000000000"
        + "0000000000000000000000000000000000000000000000000000000000000005"
        + "68656c6c6f000000000000000000000000000000000000000000000000000000"
    )


def test_tron_base58_address_inside_abi():
    data = encode_evm_call("balanceOf(address)", "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t")
    assert data[:4].hex() == selhex("balanceOf(address)")
    assert data[16:36].hex() == "a614f803b6fd780986a42c78ec9c7f77e6ded13c"
    assert data[4:16].hex() == "00" * 12  # left-padded


def test_rejects_bad_length_and_arg_count():
    with pytest.raises(Exception, match="expected 32 bytes"):
        encode_evm_call("twiddle(bool,bytes32)", True, "0xdeadbeef")
    with pytest.raises(Exception):
        encode_evm_call("transfer(address,uint256)", "0x00")


def test_alias_and_whitespace_canonicalize_identically():
    want = (
        "a9059cbb"
        "000000000000000000000000bcd4042de499d14e55001ccbb24a551f3b954096"
        "00000000000000000000000000000000000000000000000000000000000f4240"
    )
    for sig in [
        "transfer(address,uint256)",
        "transfer(address,uint)",
        "transfer(address to, uint256 amount)",
        "transfer ( address to , uint amount )",
    ]:
        assert encode_evm_call_hex(sig, "0xbcd4042de499d14e55001ccbb24a551f3b954096", 1_000_000)[2:] == want
