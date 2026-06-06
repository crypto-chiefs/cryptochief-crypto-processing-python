"""Solidity ABI encoder - turns a function signature + argument values into
calldata, so callers never hand-encode the ``data`` field. Shared by EVM and
TRON (TRON uses the same ABI).

Supported types: ``uint<M>`` / ``int<M>`` (M in 8..256, step 8; bare ``uint`` /
``int`` alias to 256), ``address`` (0x hex, 0x41 TRON hex, or ``T...`` base58),
``bool``, ``bytes``, ``bytes<N>`` (N in 1..32), ``string``, and fixed / dynamic
arrays ``T[]`` / ``T[N]`` of any supported ``T``.

Argument value forms: integers accept ``int`` or a string (decimal / ``0x``
hex); ``bytes`` accept ``bytes`` / ``bytearray`` or a string (raw / ``0x`` hex);
``address`` / ``string`` take strings; arrays take lists of the above.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional

from ..errors import CryptoChiefError
from .keccak import keccak_256
from .tron_address import tron_to_hex


class EvmAbiError(CryptoChiefError):
    def __init__(self, message: str) -> None:
        super().__init__(f"cryptochief/evm: {message}")


@dataclass
class _AbiType:
    # kind: uint | int | address | bool | bytes | string | bytesN | array
    kind: str
    size: int = 0  # bits for int/uint; byte length for bytesN; element count for fixed arrays (-1 dynamic)
    element: Optional["_AbiType"] = None


# -- Signature parsing --------------------------------------------------------


def _expand_alias(t: str) -> str:
    i = t.rfind("[")
    if i > 0:
        return _expand_alias(t[:i]) + t[i:]
    if t == "uint":
        return "uint256"
    if t == "int":
        return "int256"
    if t == "byte":
        return "bytes1"
    return t


def _strip_param_name(p: str) -> str:
    p = p.strip()
    sp = p.find(" ")
    if sp >= 0:
        p = p[:sp].strip()
    return _expand_alias(p)


def canonical_signature(sig: str) -> str:
    """Canonical form keccak hashes against (no spaces, no parameter names)."""
    open_i = sig.find("(")
    close_i = sig.rfind(")")
    if open_i < 0 or close_i < 0 or close_i < open_i:
        return sig.replace(" ", "")
    name = sig[:open_i].strip()
    body = sig[open_i + 1 : close_i].strip()
    if body == "":
        return f"{name}()"
    parts = [_strip_param_name(p) for p in body.split(",")]
    return f"{name}({','.join(parts)})"


def _parse_signature(sig: str) -> tuple[str, List[str]]:
    open_i = sig.find("(")
    close_i = sig.rfind(")")
    if open_i < 0 or close_i < 0 or close_i < open_i:
        raise EvmAbiError(f"bad signature {sig!r}")
    name = sig[:open_i].strip()
    if name == "":
        raise EvmAbiError("signature missing name")
    body = sig[open_i + 1 : close_i].strip()
    if body == "":
        return name, []
    return name, [_strip_param_name(p) for p in body.split(",")]


def _parse_int_bits(s: str, kind: str) -> int:
    if s == "":
        return 256
    if not s.isdigit():
        raise EvmAbiError(f"invalid {kind} width {s!r}")
    bits = int(s)
    if bits <= 0 or bits > 256 or bits % 8 != 0:
        raise EvmAbiError(f"invalid {kind} width {s!r}")
    return bits


def _parse_type(raw: str) -> _AbiType:
    t = raw.strip()
    if t == "":
        raise EvmAbiError("empty type")
    if t.endswith("]"):
        open_i = t.rfind("[")
        if open_i < 0:
            raise EvmAbiError(f"malformed type {t!r}")
        element = _parse_type(t[:open_i])
        span = t[open_i + 1 : len(t) - 1]
        size = -1
        if span != "":
            if not span.isdigit():
                raise EvmAbiError(f"bad array size in {t!r}")
            size = int(span)
        return _AbiType(kind="array", size=size, element=element)
    if t.startswith("uint"):
        return _AbiType(kind="uint", size=_parse_int_bits(t[4:], "uint"))
    if t.startswith("int"):
        return _AbiType(kind="int", size=_parse_int_bits(t[3:], "int"))
    if t == "address":
        return _AbiType(kind="address")
    if t == "bool":
        return _AbiType(kind="bool")
    if t == "string":
        return _AbiType(kind="string")
    if t == "bytes":
        return _AbiType(kind="bytes")
    if t.startswith("bytes"):
        rest = t[5:]
        if not rest.isdigit():
            raise EvmAbiError(f"invalid fixed bytes type {t!r}")
        n = int(rest)
        if n < 1 or n > 32:
            raise EvmAbiError(f"invalid fixed bytes type {t!r}")
        return _AbiType(kind="bytesN", size=n)
    raise EvmAbiError(f"unsupported type {t!r}")


def _is_dynamic(t: _AbiType) -> bool:
    if t.kind in ("bytes", "string"):
        return True
    if t.kind == "array":
        return t.size < 0 or _is_dynamic(t.element)  # type: ignore[arg-type]
    return False


# -- Value coercion -----------------------------------------------------------


def _to_int(v: Any) -> int:
    if isinstance(v, bool):
        raise EvmAbiError("integer: got bool")
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        s = v.strip()
        if s == "":
            raise EvmAbiError("integer: empty string")
        try:
            return int(s, 16) if s[:2].lower() == "0x" else int(s, 10)
        except ValueError as err:
            raise EvmAbiError(f"invalid integer string {v!r}") from err
    raise EvmAbiError(f"integer: unsupported type {type(v).__name__}")


def _to_big_uint(v: Any, bits: int) -> int:
    n = _to_int(v)
    if n < 0:
        raise EvmAbiError(f"uint{bits}: negative value {n}")
    if n >= (1 << bits):
        raise EvmAbiError(f"uint{bits}: value {n} exceeds max")
    return n


def _to_bytes(v: Any) -> bytes:
    if isinstance(v, (bytes, bytearray)):
        return bytes(v)
    if isinstance(v, str):
        s = v.strip()
        if s[:2].lower() == "0x":
            hexpart = s[2:]
            try:
                return bytes.fromhex(hexpart)
            except ValueError as err:
                raise EvmAbiError(f"bytes: bad hex {v!r}") from err
        return s.encode("utf-8")
    raise EvmAbiError(f"bytes: unsupported type {type(v).__name__}")


def _normalize_evm_address(value: Any) -> bytes:
    """Accept 0x hex, 0x41 TRON hex, or ``T...`` base58; return the 20-byte address."""
    if not isinstance(value, str):
        raise EvmAbiError(f"address: want string, got {type(value).__name__}")
    s = value.strip()
    if s == "":
        raise EvmAbiError("address: empty")
    if len(s) >= 30 and s[0] in "Tt" and s[:2].lower() != "0x":
        raw = bytes.fromhex(tron_to_hex(s)[2:])
        if len(raw) == 21 and raw[0] == 0x41:
            return raw[1:]
        if len(raw) == 20:
            return raw
        raise EvmAbiError(f"address: unexpected TRON length {len(raw)}")
    if s[:2].lower() == "0x":
        s = s[2:]
    if len(s) == 42 and s[:2] == "41":  # 0x41-prefixed TRON hex
        s = s[2:]
    if len(s) != 40:
        raise EvmAbiError(f"address: want 20 hex bytes, got {len(s)} chars")
    try:
        return bytes.fromhex(s)
    except ValueError as err:
        raise EvmAbiError("address: bad hex") from err


# -- Word packing -------------------------------------------------------------

_TWO_256 = 1 << 256


def _uint256_bytes(n: int) -> bytes:
    return (n % _TWO_256).to_bytes(32, "big")


def _round_up_32(n: int) -> int:
    r = n % 32
    return n if r == 0 else n + 32 - r


def _encode_dyn_bytes(b: bytes) -> bytes:
    return _uint256_bytes(len(b)) + b + b"\x00" * (_round_up_32(len(b)) - len(b))


def _encode_one(t: _AbiType, v: Any) -> bytes:
    if t.kind == "uint":
        return _uint256_bytes(_to_big_uint(v, t.size))
    if t.kind == "int":
        return _uint256_bytes(_to_int(v))
    if t.kind == "address":
        return b"\x00" * 12 + _normalize_evm_address(v)
    if t.kind == "bool":
        if not isinstance(v, bool):
            raise EvmAbiError(f"bool: want bool, got {type(v).__name__}")
        return b"\x00" * 31 + (b"\x01" if v else b"\x00")
    if t.kind == "bytesN":
        b = _to_bytes(v)
        if len(b) != t.size:
            raise EvmAbiError(f"bytes{t.size}: expected {t.size} bytes, got {len(b)}")
        return b + b"\x00" * (32 - t.size)
    if t.kind == "bytes":
        return _encode_dyn_bytes(_to_bytes(v))
    if t.kind == "string":
        if not isinstance(v, str):
            raise EvmAbiError(f"string: want string, got {type(v).__name__}")
        return _encode_dyn_bytes(v.encode("utf-8"))
    if t.kind == "array":
        if not isinstance(v, (list, tuple)):
            raise EvmAbiError(f"array: want list, got {type(v).__name__}")
        if t.size >= 0 and len(v) != t.size:
            raise EvmAbiError(f"fixed array T[{t.size}]: expected {t.size} items, got {len(v)}")
        assert t.element is not None  # arrays always carry an element type
        inner = [t.element] * len(v)
        body = _encode_components(inner, list(v))
        if t.size < 0:
            return _uint256_bytes(len(v)) + body
        return body
    raise EvmAbiError(f"cannot encode kind {t.kind}")


def _encode_components(types: List[_AbiType], args: List[Any]) -> bytes:
    tails: List[bytes] = []
    for i, t in enumerate(types):
        try:
            tails.append(_encode_one(t, args[i]))
        except EvmAbiError as err:
            raise EvmAbiError(f"arg {i}: {_strip_prefix(str(err))}") from err
    head_size = 32 * len(types)
    offsets: List[int] = [0] * len(types)
    cursor = head_size
    for i, t in enumerate(types):
        if _is_dynamic(t):
            offsets[i] = cursor
            cursor += len(tails[i])
    heads: List[bytes] = []
    for i, t in enumerate(types):
        heads.append(_uint256_bytes(offsets[i]) if _is_dynamic(t) else tails[i])
    dynamic_tails = [tails[i] if _is_dynamic(t) else b"" for i, t in enumerate(types)]
    return b"".join(heads) + b"".join(dynamic_tails)


def _strip_prefix(msg: str) -> str:
    prefix = "cryptochief/evm: "
    return msg[len(prefix) :] if msg.startswith(prefix) else msg


# -- Public API ---------------------------------------------------------------


def evm_selector(signature: str) -> bytes:
    """The 4-byte function selector for a Solidity signature."""
    return keccak_256(canonical_signature(signature).encode("utf-8"))[:4]


def encode_evm_call(signature: str, *args: Any) -> bytes:
    """Build ABI calldata (selector + encoded args) as raw bytes."""
    name, type_strs = _parse_signature(signature)
    if len(type_strs) != len(args):
        raise EvmAbiError(f"signature has {len(type_strs)} args, got {len(args)}")
    parsed: List[_AbiType] = []
    for i, s in enumerate(type_strs):
        try:
            parsed.append(_parse_type(s))
        except EvmAbiError as err:
            raise EvmAbiError(f"arg {i} ({s}): {_strip_prefix(str(err))}") from err
    return evm_selector(signature) + _encode_components(parsed, list(args))


def encode_evm_call_hex(signature: str, *args: Any) -> str:
    """Build ABI calldata as a ``0x...`` hex string (the form the ``data`` field expects)."""
    return "0x" + encode_evm_call(signature, *args).hex()
