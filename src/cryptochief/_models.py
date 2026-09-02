"""Dataclass <-> wire helpers.

The public API is modeled with dataclasses whose field names already match the
snake_case wire format, so there is no case conversion to do - requests serialize
straight to the body and responses parse straight back.

:func:`to_payload` turns a request (dataclass / dict / list / enum / scalar) into
a JSON-ready value, dropping ``None`` fields. :func:`from_dict` builds a typed
dataclass from a response dict, recursing into nested dataclass, list and map
fields and tolerating unknown keys (forward-compatible with new server fields).
"""

from __future__ import annotations

import dataclasses
import enum
from typing import Any, Mapping, Optional, Type, TypeVar, Union, get_args, get_origin, get_type_hints

T = TypeVar("T")

_hints_cache: dict[type, dict[str, Any]] = {}


def _type_hints(cls: type) -> dict[str, Any]:
    cached = _hints_cache.get(cls)
    if cached is None:
        cached = get_type_hints(cls)
        _hints_cache[cls] = cached
    return cached


def to_payload(value: Any) -> Any:
    """Recursively convert a request value to a JSON-ready form, dropping ``None``."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, enum.Enum):
        return value.value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        out: dict[str, Any] = {}
        for f in dataclasses.fields(value):
            v = getattr(value, f.name)
            if v is None:
                continue
            out[f.name] = to_payload(v)
        return out
    if isinstance(value, dict):
        return {k: to_payload(v) for k, v in value.items() if v is not None}
    if isinstance(value, (list, tuple)):
        return [to_payload(v) for v in value]
    return value


def _unwrap_optional(tp: Any) -> Any:
    if get_origin(tp) is Union:
        args = [a for a in get_args(tp) if a is not type(None)]
        if len(args) == 1:
            return args[0]
        return args[0] if args else Any
    return tp


def _is_optional(tp: Any) -> bool:
    return get_origin(tp) is Union and type(None) in get_args(tp)


def _coerce(tp: Any, value: Any) -> Any:
    inner = _unwrap_optional(tp)
    origin = get_origin(inner)
    if value is None:
        # A slot the type declares as a list is a promise of a list: a wire
        # ``null`` there becomes ``[]`` rather than a ``None`` sitting in a
        # ``List[...]`` - which is what the values of ``Dict[str, List[str]]``
        # are, and what a caller iterating them would trip over.
        # ``Optional[List[...]]`` keeps its ``None``: there the absence is part
        # of the declared shape, and the SDK's idiom for it is ``x or []``.
        if origin in (list, tuple) and not _is_optional(tp):
            return []
        return None
    if origin in (list, tuple):
        args = get_args(inner)
        elem = args[0] if args else Any
        return [_coerce(elem, v) for v in value]
    if origin is dict and isinstance(value, Mapping):
        args = get_args(inner)
        val_tp = args[1] if len(args) == 2 else Any
        return {k: _coerce(val_tp, v) for k, v in value.items()}
    if isinstance(inner, type) and dataclasses.is_dataclass(inner):
        return from_dict(inner, value)
    return value


def from_dict(cls: Type[T], data: Optional[Mapping[str, Any]]) -> T:
    """Build a dataclass of type ``cls`` from a response mapping.

    Recurses into nested dataclass / list / map fields and ignores keys the
    dataclass does not declare (forward-compatible with new server fields). A
    ``None`` or empty body yields an all-defaults instance - every response
    model is constructible with no arguments, so a literal ``null`` body decodes
    rather than raising.

    A ``null`` arriving for a field whose type is a plain ``List[...]`` decodes
    as ``[]``, since a non-optional list field promises a list; an
    ``Optional[List[...]]`` field keeps its ``None``.
    """
    if not isinstance(data, Mapping):
        data = {}
    hints = _type_hints(cls)
    kwargs: dict[str, Any] = {}
    for f in dataclasses.fields(cls):  # type: ignore[arg-type]  # cls is a dataclass type
        if f.name in data:
            kwargs[f.name] = _coerce(hints.get(f.name, Any), data[f.name])
    return cls(**kwargs)
