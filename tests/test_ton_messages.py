"""TON message bodies (built with pytoniq-core, re-parsed for verification)."""

from pytoniq_core import Cell

from cryptochief.ton.messages import (
    build_jetton_transfer_body,
    build_nft_transfer_body,
    build_text_comment_body,
    build_text_comment_cell,
    parse_ton_addr,
)

RECIPIENT = "EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs"


def test_jetton_transfer_body():
    dest = parse_ton_addr(RECIPIENT)
    boc = build_jetton_transfer_body(
        query_id=0,
        amount=12_500_000,
        destination=dest,
        response_dest=dest,
        forward_ton=1,
        forward_payload=build_text_comment_cell("Order #4242"),
    )
    s = Cell.one_from_boc(boc).begin_parse()
    assert s.load_uint(32) == 0x0F8A7EA5
    assert s.load_uint(64) == 0  # query id
    assert s.load_coins() == 12_500_000  # amount
    assert s.load_address().to_str() == dest.to_str()  # destination
    s.load_address()  # response destination
    assert s.load_maybe_ref() is None  # custom payload
    assert s.load_coins() == 1  # forward ton
    assert s.load_bit()  # forward payload as ref


def test_nft_transfer_body():
    owner = parse_ton_addr(RECIPIENT)
    boc = build_nft_transfer_body(query_id=7, new_owner=owner, response_dest=owner, forward_ton=0)
    s = Cell.one_from_boc(boc).begin_parse()
    assert s.load_uint(32) == 0x5FCC3D14
    assert s.load_uint(64) == 7
    assert s.load_address().to_str() == owner.to_str()


def test_text_comment_body():
    s = Cell.one_from_boc(build_text_comment_body("Thanks for the coffee!")).begin_parse()
    assert s.load_uint(32) == 0
    assert s.load_snake_string() == "Thanks for the coffee!"
