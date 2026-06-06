"""Amount conversion helpers backed by Python's arbitrary-precision ``int``.

**Never use ``float`` for crypto amounts**: ``0.1 + 0.2 != 0.3`` and large token
values lose precision. These helpers parse decimal strings exactly and return
``int`` base units.
"""

from __future__ import annotations

from .errors import CryptoChiefError


class InvalidAmountError(CryptoChiefError):
    """Raised by :func:`human_to_base` when its input is not a plain decimal."""

    def __init__(self, message: str) -> None:
        super().__init__(f"cryptochief: invalid amount: {message}")


def _is_ascii_digits(s: str) -> bool:
    return len(s) > 0 and all("0" <= c <= "9" for c in s)


def human_to_base(human: str, decimals: int) -> int:
    """Convert a decimal human amount (e.g. ``"0.0001"``) to its base-unit ``int``.

    Precise to the last digit. Negative amounts and scientific notation are
    rejected. Sub-base-unit precision is truncated, since it is meaningless
    on-chain.

    >>> human_to_base("1.5", 18)
    1500000000000000000
    >>> human_to_base("0.0001", 8)
    10000
    """
    s = human.strip()
    if s == "":
        raise InvalidAmountError("empty")
    if not isinstance(decimals, int) or isinstance(decimals, bool) or decimals < 0:
        raise InvalidAmountError(f"negative or non-integer decimals {decimals!r}")
    if "e" in s or "E" in s:
        raise InvalidAmountError(f"scientific notation not allowed: {human!r}")
    if s.startswith("-"):
        raise InvalidAmountError(f"negative not allowed: {human!r}")

    dot = s.find(".")
    if dot < 0:
        if not _is_ascii_digits(s):
            raise InvalidAmountError(repr(human))
        int_part, frac_part = s, ""
    else:
        int_part = s[:dot] or "0"
        frac_part = s[dot + 1 :]
        if frac_part == "":
            raise InvalidAmountError(repr(human))
        if not _is_ascii_digits(int_part) or not _is_ascii_digits(frac_part):
            raise InvalidAmountError(repr(human))

    if len(frac_part) > decimals:
        frac_part = frac_part[:decimals]
    else:
        frac_part = frac_part.ljust(decimals, "0")

    combined = (int_part + frac_part).lstrip("0") or "0"
    return int(combined)


def base_to_human(base: int, decimals: int) -> str:
    """Inverse of :func:`human_to_base`: a base-unit ``int`` to a decimal string.

    Trailing zeroes are trimmed.

    >>> base_to_human(1500000000000000000, 18)
    '1.5'
    >>> base_to_human(0, 18)
    '0'
    """
    if decimals < 0:
        decimals = 0
    abs_s = str(-base if base < 0 else base)
    if decimals == 0:
        return abs_s
    if len(abs_s) <= decimals:
        abs_s = "0" * (decimals - len(abs_s) + 1) + abs_s
    cut = len(abs_s) - decimals
    int_part = abs_s[:cut]
    frac_part = abs_s[cut:].rstrip("0")
    return int_part if frac_part == "" else f"{int_part}.{frac_part}"


def nano_ton(human: str) -> int:
    """Convert a human TON amount (``"0.05"``) into base-unit nanoTON (``50000000``).

    Equivalent to ``human_to_base(human, 9)`` - the form the TON helpers'
    ``attached_ton`` / ``forward_ton_amount`` fields expect.
    """
    return human_to_base(human, 9)
