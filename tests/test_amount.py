import pytest

from cryptochief import InvalidAmountError, base_to_human, human_to_base, nano_ton


def test_human_to_base_full_precision():
    assert human_to_base("1.5", 18) == 1_500_000_000_000_000_000
    assert human_to_base("0.0001", 8) == 10_000
    assert human_to_base("0.5", 6) == 500_000
    assert human_to_base("12.5", 6) == 12_500_000
    assert human_to_base("0", 18) == 0
    assert human_to_base("100", 0) == 100


def test_human_to_base_truncates_sub_base_unit():
    assert human_to_base("1.123456789", 6) == 1_123_456


@pytest.mark.parametrize("bad", ["-1", "1e3", "", "1.2.3", "abc", "1."])
def test_human_to_base_rejects(bad):
    with pytest.raises(InvalidAmountError):
        human_to_base(bad, 18)


def test_base_to_human_trims_trailing_zeroes():
    assert base_to_human(1_500_000_000_000_000_000, 18) == "1.5"
    assert base_to_human(0, 18) == "0"
    assert base_to_human(10_000, 8) == "0.0001"
    assert base_to_human(100, 0) == "100"


@pytest.mark.parametrize("human,decimals", [("123.456", 18), ("0.000001", 6), ("1000000", 8)])
def test_round_trip(human, decimals):
    assert base_to_human(human_to_base(human, decimals), decimals) == human


def test_nano_ton():
    assert nano_ton("0.05") == 50_000_000
    assert nano_ton("1") == 1_000_000_000
