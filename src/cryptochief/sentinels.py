"""Sentinels for values that ``None`` cannot express.

Python has one "absent" value and some APIs need two. Where an argument
distinguishes "not supplied" from "supplied as nothing", ``None`` takes the
first meaning and a sentinel from this module takes the second.
"""

from __future__ import annotations


class Clear:
    """Stop overriding a field and go back to inheriting it.

    Used with :meth:`cryptochief.SweepsService.update_settings`, where the API
    expresses "inherit this again" by naming a field and sending no value for
    it. ``None`` already means "leave this field alone", so it cannot also mean
    "reset it".

    Use the :data:`CLEAR` singleton rather than constructing this.
    """

    _instance: "Clear | None" = None

    def __new__(cls) -> "Clear":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "CLEAR"

    def __bool__(self) -> bool:
        # Truthy: `if value:` on a CLEAR must not read as "nothing was passed".
        return True


#: The singleton :class:`Clear`.
CLEAR = Clear()
