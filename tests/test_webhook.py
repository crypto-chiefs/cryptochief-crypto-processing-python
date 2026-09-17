"""Webhook verification (HMAC-SHA256 v1) and typed event parsing.

testdata/webhook_hmac_v1_vectors.json is copied unchanged from
processing-webhook-service/internal/signature/testdata.
"""

import base64
import decimal
import email.message
import hashlib
import hmac
import inspect
import json
import math
from collections import Counter

import httpx
import pytest

import cryptochief
import cryptochief.webhook
import vectors
from cryptochief import (
    DEFAULT_WEBHOOK_TOLERANCE,
    WEBHOOK_DELIVERY_HEADER,
    WEBHOOK_SIGNATURE_HEADER,
    WEBHOOK_TIMESTAMP_HEADER,
    CryptoChiefError,
    PayInWebhookEvent,
    PayoutWebhookEvent,
    StaticDepositWebhookEvent,
    SweepWebhookEvent,
    TransactionWebhookEvent,
    WebhookHeadersError,
    WebhookSignatureError,
    WebhookTimestampError,
    WebhookVerificationError,
    parse_webhook_event,
    sign_webhook_v1,
    verify_webhook,
    webhook_v1_string_to_sign,
)

VECTORS_FILE = vectors.WEBHOOK_VECTORS_FILE
VECTORS = vectors.WEBHOOK_VECTORS
BY_NAME = {v["name"]: v for v in VECTORS}
IDS = [v["name"] for v in VECTORS]

REFUSAL = {
    "ok": None,
    "bad_headers": WebhookHeadersError,
    "timestamp_out_of_range": WebhookTimestampError,
    "bad_signature": WebhookSignatureError,
}
REASON = {
    "bad_headers": "headers",
    "timestamp_out_of_range": "timestamp",
    "bad_signature": "signature",
}

KEY = "test_api_key_123"
TS = 1789430400
DELIVERY = "7c9e6679-7425-40de-944b-e07fc1f90ae7"


def body_of(v: dict) -> bytes:
    if "body_base64" in v:
        return base64.b64decode(v["body_base64"])
    return v["body"].encode("utf-8")


def headers_of(v: dict) -> dict:
    """Headers the receiver sees: name -> list of values ([] means absent)."""
    headers = {
        WEBHOOK_TIMESTAMP_HEADER: [str(v["timestamp"])],
        WEBHOOK_DELIVERY_HEADER: [v["delivery_id"]],
        WEBHOOK_SIGNATURE_HEADER: [v["signature"]],
    }
    headers.update(v.get("headers", {}))
    return headers


def header_shapes(headers: dict) -> dict:
    """The same headers in the shapes receivers pass them."""
    pairs = [(name, value) for name, values in headers.items() for value in values]
    message = email.message.Message()
    for name, value in pairs:
        message[name] = value
    return {
        "dict_of_lists": headers,
        "lowercase_names": {name.lower(): values for name, values in headers.items()},
        "pairs": pairs,
        "asgi_bytes_pairs": [(n.lower().encode("latin-1"), v.encode("utf-8")) for n, v in pairs],
        "email_message": message,
    }


def outcome(fn):
    try:
        fn()
    except WebhookVerificationError as err:
        return type(err)
    return None


def signed(body, *, key=KEY, ts=TS, delivery=DELIVERY):
    raw = body if isinstance(body, (bytes, str)) else json.dumps(body).encode("utf-8")
    return raw, {
        WEBHOOK_TIMESTAMP_HEADER: str(ts),
        WEBHOOK_DELIVERY_HEADER: delivery,
        WEBHOOK_SIGNATURE_HEADER: sign_webhook_v1(key, ts, delivery, raw),
    }


# -- Reference vectors ---------------------------------------------------------


def test_vector_file_is_the_reference_copy():
    assert vectors.WEBHOOK_VECTORS_SHA256 == (
        "15a6e1423708e8c3b9ec4fac7ee6eb383db56703605647e02308a29166722502"
    )
    assert hashlib.sha256(VECTORS_FILE.read_bytes()).hexdigest() == (
        vectors.WEBHOOK_VECTORS_SHA256
    )
    assert b"\r" not in VECTORS_FILE.read_bytes()
    assert len(VECTORS) == len(BY_NAME) == 54
    assert Counter(v["expect"] for v in VECTORS) == {
        "ok": 22,
        "bad_headers": 26,
        "bad_signature": 4,
        "timestamp_out_of_range": 2,
    }


@pytest.mark.parametrize("v", VECTORS, ids=IDS)
def test_vector_string_to_sign_and_signature(v):
    body = body_of(v)
    assert hashlib.sha256(body).hexdigest() == v["body_sha256"]
    assert webhook_v1_string_to_sign(v["timestamp"], v["delivery_id"], body) == v["string_to_sign"]
    assert sign_webhook_v1(v["api_key"], v["timestamp"], v["delivery_id"], body) == v["signature"]
    if "body" in v:
        assert sign_webhook_v1(v["api_key"], v["timestamp"], v["delivery_id"], v["body"]) == (
            v["signature"]
        )


@pytest.mark.parametrize("v", VECTORS, ids=IDS)
def test_vector_verify(v):
    body = body_of(v)
    expected = REFUSAL[v["expect"]]
    for shape, headers in header_shapes(headers_of(v)).items():
        got = outcome(lambda: verify_webhook(v["api_key"], body, headers, now=v["now"]))
        assert got is expected, shape
    if "body" in v:
        got = outcome(lambda: verify_webhook(v["api_key"], v["body"], headers_of(v), now=v["now"]))
        assert got is expected
    if expected is not None:
        with pytest.raises(expected) as ei:
            verify_webhook(v["api_key"], body, headers_of(v), now=v["now"])
        assert ei.value.reason == REASON[v["expect"]]
        assert isinstance(ei.value, CryptoChiefError)


@pytest.mark.parametrize("v", VECTORS, ids=IDS)
def test_vector_parse(v):
    body = body_of(v)
    headers = headers_of(v)
    expected = REFUSAL[v["expect"]]
    if expected is not None:
        with pytest.raises(expected):
            parse_webhook_event(v["api_key"], body, headers, now=v["now"])
        return
    try:
        data = json.loads(body)
    except ValueError:
        data = None
    if isinstance(data, dict):
        event = parse_webhook_event(v["api_key"], body, headers, now=v["now"])
        assert event is not None
    else:
        with pytest.raises(CryptoChiefError) as ei:
            parse_webhook_event(v["api_key"], body, headers, now=v["now"])
        assert not isinstance(ei.value, WebhookVerificationError)


def test_vector_events_are_typed():
    cases = {
        "payin_invoice_paid_with_nulls": PayInWebhookEvent,
        "payout_paid": PayoutWebhookEvent,
        "static_deposit_paid": StaticDepositWebhookEvent,
        "sweep_confirmed": SweepWebhookEvent,
        "transaction_failed": TransactionWebhookEvent,
    }
    for name, cls in cases.items():
        v = BY_NAME[name]
        event = parse_webhook_event(v["api_key"], body_of(v), headers_of(v), now=v["now"])
        assert isinstance(event, cls), name
        assert event.event == json.loads(body_of(v))["event"]

    v = BY_NAME["payin_invoice_paid_with_nulls"]
    event = parse_webhook_event(v["api_key"], body_of(v), headers_of(v), now=v["now"])
    assert event.event == "invoice.paid"
    assert event.order_id == "ORD-2026-000187"


# -- Headers -------------------------------------------------------------------


def test_header_constants():
    assert WEBHOOK_DELIVERY_HEADER == "X-Webhook-Delivery"
    assert WEBHOOK_TIMESTAMP_HEADER == "X-CC-Timestamp"
    assert WEBHOOK_SIGNATURE_HEADER == "X-CC-Signature"
    assert DEFAULT_WEBHOOK_TOLERANCE == 300


def test_plain_dict_of_strings():
    raw, headers = signed({"event": "payout.paid"})
    verify_webhook(KEY, raw, headers, now=TS)
    verify_webhook(KEY, raw, {k.upper(): v for k, v in headers.items()}, now=TS)


def test_one_header_under_two_spellings_is_a_repeat():
    raw, headers = signed({"event": "payout.paid"})
    for name in headers:
        doubled = {**headers, name.lower(): headers[name]}
        with pytest.raises(WebhookHeadersError):
            verify_webhook(KEY, raw, doubled, now=TS)


def test_names_match_ignoring_ascii_case_only():
    raw, headers = signed({"event": "payout.paid"})
    # U+017F and U+212A fold to "s" and "k" in Unicode, not in ASCII.
    lookalike = {
        "X-CC-Timeſtamp": headers[WEBHOOK_TIMESTAMP_HEADER],
        WEBHOOK_DELIVERY_HEADER: headers[WEBHOOK_DELIVERY_HEADER],
        WEBHOOK_SIGNATURE_HEADER: headers[WEBHOOK_SIGNATURE_HEADER],
    }
    with pytest.raises(WebhookHeadersError):
        verify_webhook(KEY, raw, lookalike, now=TS)
    extra = {
        **headers,
        "X-WebhooK-Delivery": "other",
        "x-cc-ſignature": "v1=" + "0" * 64,
        "X-CC-TIMESTAMP".encode("latin-1") + b"\xc5\xbf": "1",
    }
    verify_webhook(KEY, raw, extra, now=TS)
    verify_webhook(KEY, raw, {k.swapcase(): v for k, v in headers.items()}, now=TS)


def test_none_value_is_an_empty_value_not_an_absent_header():
    raw, headers = signed({"event": "payout.paid"})
    with pytest.raises(WebhookHeadersError):
        verify_webhook(KEY, raw, {**headers, WEBHOOK_SIGNATURE_HEADER: None}, now=TS)
    for name in headers:
        for repeat in ([(name, None)], [(name, [None])]):
            with pytest.raises(WebhookHeadersError):
                verify_webhook(KEY, raw, repeat + list(headers.items()), now=TS)


def test_headers_may_be_a_one_shot_iterable():
    raw, headers = signed({"event": "payout.paid"})
    pairs = list(headers.items())
    verify_webhook(KEY, raw, iter(pairs), now=TS)
    verify_webhook(KEY, raw, ((name, value) for name, value in pairs), now=TS)
    event = parse_webhook_event(KEY, raw, iter(pairs), now=TS)
    assert event.event == "payout.paid"
    with pytest.raises(WebhookHeadersError):
        verify_webhook(KEY, raw, iter(pairs + [(WEBHOOK_DELIVERY_HEADER, DELIVERY)]), now=TS)


def test_httpx_headers():
    raw, headers = signed({"event": "payout.paid"})
    verify_webhook(KEY, raw, httpx.Headers(headers), now=TS)
    repeated = httpx.Headers(list(headers.items()) + [(WEBHOOK_SIGNATURE_HEADER, "v1=" + "0" * 64)])
    with pytest.raises(WebhookHeadersError):
        verify_webhook(KEY, raw, repeated, now=TS)


class MultiDict:
    """Headers object whose ``items()`` yields every value, as Starlette and Werkzeug do."""

    def __init__(self, pairs):
        self._pairs = pairs

    def items(self):
        return list(self._pairs)


def test_items_with_repeated_names():
    raw, headers = signed({"event": "payout.paid"})
    verify_webhook(KEY, raw, MultiDict(headers.items()), now=TS)
    pairs = list(headers.items()) + [(WEBHOOK_DELIVERY_HEADER.lower(), DELIVERY)]
    with pytest.raises(WebhookHeadersError):
        verify_webhook(KEY, raw, MultiDict(pairs), now=TS)


@pytest.mark.parametrize(
    "timestamp",
    [
        "9223372036854775808",
        "99999999999999999999",
        "١٧٨٩٤٣٠٤٠٠",
        "1789430400 1",
        "0x6aa6d680",
        "1_789_430_400",
    ],
)
def test_malformed_timestamp(timestamp):
    raw, headers = signed({"event": "payout.paid"})
    with pytest.raises(WebhookHeadersError):
        verify_webhook(KEY, raw, {**headers, WEBHOOK_TIMESTAMP_HEADER: timestamp}, now=TS)


def test_largest_int64_timestamp_is_out_of_range():
    raw, headers = signed({"event": "payout.paid"})
    with pytest.raises(WebhookTimestampError):
        verify_webhook(
            KEY, raw, {**headers, WEBHOOK_TIMESTAMP_HEADER: "9223372036854775807"}, now=TS
        )


@pytest.mark.parametrize("timestamp", ["0" + str(TS), "000" + str(TS), "01", "00"])
def test_timestamp_with_a_leading_zero(timestamp):
    raw, headers = signed({"event": "payout.paid"})
    with pytest.raises(WebhookHeadersError):
        verify_webhook(KEY, raw, {**headers, WEBHOOK_TIMESTAMP_HEADER: timestamp}, now=TS)


def test_zero_timestamp():
    raw, headers = signed({"event": "payout.paid"})
    zero = {**headers, WEBHOOK_TIMESTAMP_HEADER: "0"}
    with pytest.raises(WebhookTimestampError):
        verify_webhook(KEY, raw, zero, now=TS)
    with pytest.raises(WebhookHeadersError):
        verify_webhook(KEY, raw, zero, now=100)


@pytest.mark.parametrize(
    "signature",
    [
        "v1=" + "ab" * 16 + " " + "ab" * 15 + "a",
        "v1= " + "ab" * 32,
        "v1=" + "ａ" * 64,
        "v1:" + "ab" * 32,
        "v2=" + "ab" * 32,
        "sha256=" + "ab" * 32,
    ],
)
def test_malformed_signature(signature):
    raw, headers = signed({"event": "payout.paid"})
    with pytest.raises(WebhookHeadersError):
        verify_webhook(KEY, raw, {**headers, WEBHOOK_SIGNATURE_HEADER: signature}, now=TS)


def test_order_of_checks():
    raw, headers = signed({"event": "payout.paid"})
    stale_and_wrong = {**headers, WEBHOOK_SIGNATURE_HEADER: "v1=" + "0" * 64}
    with pytest.raises(WebhookTimestampError):
        verify_webhook(KEY, raw, stale_and_wrong, now=TS + 301)
    malformed_and_stale = {**stale_and_wrong, WEBHOOK_DELIVERY_HEADER: "a.b"}
    with pytest.raises(WebhookHeadersError):
        verify_webhook(KEY, raw, malformed_and_stale, now=TS + 301)


@pytest.mark.parametrize("api_key", ["", " ", "\t", " \t "])
def test_blank_api_key_is_a_usage_error_before_headers(api_key):
    """A key of nothing but spaces and tabs is empty: it never verifies anything."""
    raw, headers = signed({"event": "payout.paid"})
    for bad_headers in (headers, {}):
        with pytest.raises(CryptoChiefError, match="api_key") as ei:
            verify_webhook(api_key, raw, bad_headers, now=TS)
        assert not isinstance(ei.value, WebhookVerificationError)
    own = {
        WEBHOOK_TIMESTAMP_HEADER: str(TS),
        WEBHOOK_DELIVERY_HEADER: DELIVERY,
        WEBHOOK_SIGNATURE_HEADER: "v1="
        + hmac.new(
            api_key.encode("utf-8"),
            webhook_v1_string_to_sign(TS, DELIVERY, raw).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest(),
    }
    with pytest.raises(CryptoChiefError, match="api_key"):
        verify_webhook(api_key, raw, own, now=TS)


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("tolerance", math.inf),
        ("tolerance", -math.inf),
        ("tolerance", math.nan),
        ("tolerance", "300"),
        ("tolerance", decimal.Decimal("Infinity")),
        ("tolerance", decimal.Decimal("NaN")),
        ("now", math.inf),
        ("now", -math.inf),
        ("now", math.nan),
        ("now", "1789430400"),
        ("now", decimal.Decimal("sNaN")),
    ],
)
def test_non_finite_tolerance_or_now_is_a_usage_error_before_headers(option, value):
    raw, headers = signed({"event": "payout.paid"})
    kwargs = {"now": TS, option: value}
    for fn in (verify_webhook, parse_webhook_event):
        for bad_headers in (headers, {}):
            with pytest.raises(CryptoChiefError, match=option) as ei:
                fn(KEY, raw, bad_headers, **kwargs)
            assert not isinstance(ei.value, WebhookVerificationError)


def test_large_finite_tolerance_and_now():
    raw, headers = signed({"event": "payout.paid"})
    verify_webhook(KEY, raw, headers, tolerance=10**30, now=10**25)
    verify_webhook(KEY, raw, headers, tolerance=1e300, now=-1e200)
    verify_webhook(KEY, raw, headers, tolerance=decimal.Decimal(10), now=decimal.Decimal(TS + 10))
    with pytest.raises(WebhookTimestampError):
        verify_webhook(KEY, raw, headers, now=10**25)


def test_exception_hierarchy():
    for cls in (WebhookHeadersError, WebhookTimestampError, WebhookSignatureError):
        assert issubclass(cls, WebhookVerificationError)
        assert issubclass(cls, CryptoChiefError)
    assert {WebhookHeadersError().reason, WebhookTimestampError().reason,
            WebhookSignatureError().reason} == {"headers", "timestamp", "signature"}


# -- Window --------------------------------------------------------------------


def test_tolerance_and_clock():
    raw, headers = signed({"event": "payout.paid"})
    verify_webhook(KEY, raw, headers, tolerance=10, now=TS + 10)
    verify_webhook(KEY, raw, headers, tolerance=10, now=TS - 10)
    with pytest.raises(WebhookTimestampError):
        verify_webhook(KEY, raw, headers, tolerance=10, now=TS + 11)
    for default in (0, -5):
        verify_webhook(KEY, raw, headers, tolerance=default, now=TS + 300)
        with pytest.raises(WebhookTimestampError):
            verify_webhook(KEY, raw, headers, tolerance=default, now=TS + 301)
    verify_webhook(KEY, raw, headers, now=TS + 300.9)
    with pytest.raises(WebhookTimestampError):
        verify_webhook(KEY, raw, headers, now=TS - 300.5)


def test_default_clock_is_time_time(monkeypatch):
    raw, headers = signed({"event": "payout.paid"})
    monkeypatch.setattr(cryptochief.webhook.time, "time", lambda: TS + 299.99)
    verify_webhook(KEY, raw, headers)
    monkeypatch.setattr(cryptochief.webhook.time, "time", lambda: TS + 301.0)
    with pytest.raises(WebhookTimestampError):
        verify_webhook(KEY, raw, headers)
    with pytest.raises(WebhookTimestampError):
        parse_webhook_event(KEY, raw, headers)


# -- Signature -----------------------------------------------------------------


def test_signature_covers_the_exact_bytes():
    body = {"event": "payout.paid", "uuid": "p-1", "status": "paid"}
    raw, headers = signed(json.dumps(body, separators=(",", ":")).encode("utf-8"))
    verify_webhook(KEY, raw, headers, now=TS)
    for other in (
        json.dumps(body).encode("utf-8"),
        json.dumps(dict(reversed(list(body.items())))).encode("utf-8"),
        raw + b"\n",
        raw.replace(b"paid", b"PAID"),
    ):
        with pytest.raises(WebhookSignatureError):
            verify_webhook(KEY, other, headers, now=TS)
    with pytest.raises(WebhookSignatureError):
        verify_webhook(KEY + "x", raw, headers, now=TS)


def test_body_types():
    raw, headers = signed(b'{"event":"payout.paid","memo":"\xd0\x9a"}')
    for body in (raw, bytearray(raw), memoryview(raw), raw.decode("utf-8")):
        verify_webhook(KEY, body, headers, now=TS)


def test_str_body_decoded_with_surrogateescape_matches_its_bytes():
    raw, headers = signed(b'{"event":"payout.paid","memo":"\xff"}')
    verify_webhook(KEY, raw.decode("utf-8", "surrogateescape"), headers, now=TS)
    with pytest.raises(WebhookSignatureError):
        verify_webhook(KEY, '{"event":"payout.paid","memo":"\ud800"}', headers, now=TS)


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (("", TS, DELIVERY), "api_key"),
        ((" ", TS, DELIVERY), "api_key"),
        (("\t", TS, DELIVERY), "api_key"),
        ((" \t ", TS, DELIVERY), "api_key"),
        ((KEY, 0, DELIVERY), "timestamp"),
        ((KEY, -1, DELIVERY), "timestamp"),
        ((KEY, True, DELIVERY), "timestamp"),
        ((KEY, str(TS), DELIVERY), "timestamp"),
        ((KEY, 2**63, DELIVERY), "timestamp"),
        ((KEY, 2**64, DELIVERY), "timestamp"),
        ((KEY, TS, ""), "delivery id"),
        ((KEY, TS, "a" * 129), "delivery id"),
        ((KEY, TS, "dlv.1"), "delivery id"),
        ((KEY, TS, "dlv\n1"), "delivery id"),
        ((KEY, TS, "dél"), "delivery id"),
    ],
)
def test_sign_rejects_invalid_input(args, message):
    with pytest.raises(CryptoChiefError, match=message):
        sign_webhook_v1(*args, b"{}")
    if message != "api_key":  # the string to sign carries no key
        with pytest.raises(CryptoChiefError, match=message):
            webhook_v1_string_to_sign(args[1], args[2], b"{}")


def test_sign_and_verify_the_largest_timestamp():
    ts = 2**63 - 1
    raw, headers = signed(b"{}", ts=ts)
    assert webhook_v1_string_to_sign(ts, DELIVERY, raw).split("\n")[1] == "9223372036854775807"
    verify_webhook(KEY, raw, headers, now=ts)


def test_sign_empty_body_by_default():
    v = BY_NAME["empty_body"]
    assert sign_webhook_v1(v["api_key"], v["timestamp"], v["delivery_id"]) == v["signature"]
    assert webhook_v1_string_to_sign(v["timestamp"], v["delivery_id"]) == v["string_to_sign"]


def test_removed_signing_api_is_not_exported():
    for name in (
        "sign",
        "sign_value",
        "canonical_json",
        "canonicalize_json",
        "verify_webhook_signature",
        "verify_webhook_payload",
        "webhook_signature",
        "WEBHOOK_HEADER",
    ):
        value = getattr(cryptochief, name, None)
        assert value is None or inspect.ismodule(value), name
        assert name not in cryptochief.__all__
    assert not hasattr(cryptochief.sign, "sign")
    assert not hasattr(cryptochief.sign, "canonical_json")


# -- Parsing -------------------------------------------------------------------


def test_parse_checks_before_parsing():
    raw, headers = signed(b"not json")
    with pytest.raises(WebhookSignatureError):
        parse_webhook_event(KEY + "x", raw, headers, now=TS)
    with pytest.raises(CryptoChiefError, match="not JSON") as ei:
        parse_webhook_event(KEY, raw, headers, now=TS)
    assert not isinstance(ei.value, WebhookVerificationError)


@pytest.mark.parametrize(
    "body",
    [b"[]", b'"payout.paid"', b"null", b"", b"\xef\xbb\xbf{}", b"[" * 100000 + b"]" * 100000],
    ids=["array", "string", "null", "empty", "bom", "deep"],
)
def test_parse_verified_body_that_is_not_an_object(body):
    raw, headers = signed(body)
    with pytest.raises(CryptoChiefError) as ei:
        parse_webhook_event(KEY, raw, headers, now=TS)
    assert not isinstance(ei.value, WebhookVerificationError)


def test_parse_reads_the_raw_body():
    raw, headers = signed(
        b'{"event":"custom.x","a":"first","n":1.50,"big":9007199254740993,"a":"last",'
        b'"memo":"\xff","s":"\\u003c\\ud83d\\ude00"}'
    )
    assert parse_webhook_event(KEY, raw, headers, now=TS) == {
        "event": "custom.x",
        "a": "last",
        "n": 1.5,
        "big": 9007199254740993,
        "memo": "�",
        "s": "<\U0001f600",
    }


def test_payout_webhook_carries_confirmations_and_leaves_them_out_before_a_transaction():
    paid = {
        "event": "payout.paid",
        "uuid": "p-1",
        "order_id": "o-1",
        "status": "paid",
        "amount_to_receive": "0.0099",
        "sources": [
            {"address": "0xa", "txid": "0x01", "confirmations": 12},
            {"address": "0xb", "txid": "0x02", "confirmations": 5},
        ],
        "service_operations": [{"type": "gas_refuel", "txid": "0x03", "confirmations": 30}],
        "confirmations": 5,
        "required_confirmations": 5,
    }
    evt = parse_webhook_event(KEY, *signed(paid), now=TS)
    assert isinstance(evt, PayoutWebhookEvent)
    assert (evt.order_id, evt.amount_to_receive) == ("o-1", "0.0099")
    assert evt.confirmations == 5
    assert evt.required_confirmations == 5
    assert [s["confirmations"] for s in evt.sources] == [12, 5]
    assert evt.service_operations[0]["confirmations"] == 30

    failed = {
        "event": "payout.system_fail",
        "uuid": "p-2",
        "status": "system_fail",
        "sources": [{"address": "0xa"}],
        "service_operations": [],
    }
    evt = parse_webhook_event(KEY, *signed(failed), now=TS)
    assert isinstance(evt, PayoutWebhookEvent)
    assert evt.confirmations is None
    assert "confirmations" not in evt.sources[0]
    assert evt.required_confirmations is None


def test_transaction_webhook_carries_confirmations_and_the_threshold():
    confirmed = {
        "event": "transaction.confirmed",
        "uuid": "tx-1",
        "status": "confirmed",
        "tx_hash": "0xabc",
        "confirmations": 13,
        "required_confirmations": 12,
    }
    evt = parse_webhook_event(KEY, *signed(confirmed), now=TS)
    assert isinstance(evt, TransactionWebhookEvent)
    assert (evt.confirmations, evt.required_confirmations) == (13, 12)

    expired = {
        "event": "transaction.expired",
        "uuid": "tx-2",
        "status": "expired",
        "confirmations": 0,
        "required_confirmations": 1,
    }
    evt = parse_webhook_event(KEY, *signed(expired), now=TS)
    assert isinstance(evt, TransactionWebhookEvent)
    assert (evt.confirmations, evt.required_confirmations) == (0, 1)


SWEEP_CONFIRMED = {
    "event": "sweep.confirmed",
    "task_id": "t-1",
    "status": "completed",
    "wallet_address": "0xdeposit",
    "network": "ETH_MAINNET",
    "asset_symbol": "USDT",
    "sweep_tx_hash": "0xsweep",
}


def test_sweep_webhook_carries_the_finality_depth_it_was_held_to():
    body = {**SWEEP_CONFIRMED, "sweep_confirmations": 12, "required_confirmations": 12}
    evt = parse_webhook_event(KEY, *signed(body), now=TS)
    assert isinstance(evt, SweepWebhookEvent)
    assert evt.status == "completed"
    assert (evt.sweep_confirmations, evt.required_confirmations) == (12, 12)


def test_sweep_webhook_without_depth():
    body = {**SWEEP_CONFIRMED, "sweep_confirmations": 1}
    evt = parse_webhook_event(KEY, *signed(body), now=TS)
    assert isinstance(evt, SweepWebhookEvent)
    assert evt.sweep_confirmations == 1
    assert evt.required_confirmations is None


def test_payin_body_with_nulls():
    v = BY_NAME["payin_invoice_paid_with_nulls"]
    evt = parse_webhook_event(v["api_key"], body_of(v), headers_of(v), now=v["now"])
    assert isinstance(evt, PayInWebhookEvent)
    data = json.loads(body_of(v))
    assert evt.uuid == data["uuid"]
    assert evt.txid == data.get("txid")
    assert evt.prev_status == data.get("prev_status")
