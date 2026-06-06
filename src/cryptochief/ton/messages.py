"""TON message-body builders.

BoC (de)serialization is delegated to ``pytoniq-core``; the SDK does not encode
cells by hand. These helpers produce the raw BoC bytes the contract-call
``data`` field expects (base64-encoded by the caller).
"""

from __future__ import annotations

from typing import Optional

from pytoniq_core import Address, Cell, begin_cell

from ..errors import CryptoChiefError

# TON internal-message op codes from the public TEP standards.
OP_JETTON_TRANSFER = 0x0F8A7EA5  # TEP-74
OP_NFT_TRANSFER = 0x5FCC3D14  # TEP-62
OP_TEXT_COMMENT = 0x00000000


def parse_ton_addr(s: str) -> Address:
    """Parse any TON address form (``EQ`` / ``UQ`` or raw ``workchain:hex``)."""
    try:
        return Address(s)
    except Exception as err:  # noqa: BLE001 - library raises various types
        raise CryptoChiefError(
            f"cryptochief/ton: invalid TON address {s!r} "
            f"(expected EQ/UQ or workchain:hex): {err}"
        ) from err


def build_jetton_transfer_body(
    *,
    query_id: int,
    amount: int,
    destination: Address,
    response_dest: Optional[Address],
    custom_payload: Optional[Cell] = None,
    forward_ton: int,
    forward_payload: Optional[Cell] = None,
) -> bytes:
    """Standard Jetton "transfer" body (TEP-74, op ``0x0f8a7ea5``).

    ``destination`` is the recipient's *main* TON wallet; the network handles the
    wallet-to-wallet hop.
    """
    if amount < 0:
        raise CryptoChiefError("cryptochief/ton: jetton amount must be non-negative")
    b = (
        begin_cell()
        .store_uint(OP_JETTON_TRANSFER, 32)
        .store_uint(query_id, 64)
        .store_coins(amount)
        .store_address(destination)
        .store_address(response_dest)
        .store_maybe_ref(custom_payload)
        .store_coins(max(forward_ton, 0))
    )
    # forward_payload: Either Cell ^Cell - ref when supplied, empty-inline otherwise.
    if forward_payload is not None:
        b = b.store_bit(1).store_ref(forward_payload)
    else:
        b = b.store_bit(0)
    return bytes(b.end_cell().to_boc())


def build_nft_transfer_body(
    *,
    query_id: int,
    new_owner: Address,
    response_dest: Optional[Address],
    custom_payload: Optional[Cell] = None,
    forward_ton: int,
    forward_payload: Optional[Cell] = None,
) -> bytes:
    """Standard NFT "transfer" body (TEP-62, op ``0x5fcc3d14``)."""
    b = (
        begin_cell()
        .store_uint(OP_NFT_TRANSFER, 32)
        .store_uint(query_id, 64)
        .store_address(new_owner)
        .store_address(response_dest)
        .store_maybe_ref(custom_payload)
        .store_coins(max(forward_ton, 0))
    )
    if forward_payload is not None:
        b = b.store_bit(1).store_ref(forward_payload)
    else:
        b = b.store_bit(0)
    return bytes(b.end_cell().to_boc())


def build_text_comment_cell(text: str) -> Cell:
    """A standalone text-comment cell (op ``0`` + UTF-8 snake string).

    Used both as a top-level body and as a Jetton transfer's ``forward_payload``
    ref when a memo is supplied.
    """
    return begin_cell().store_uint(OP_TEXT_COMMENT, 32).store_snake_string(text).end_cell()


def build_text_comment_body(text: str) -> bytes:
    """Simple text-comment body (what wallets show as the transfer note)."""
    return bytes(build_text_comment_cell(text).to_boc())
