"""HMAC v1 request signing against the gateway's vectors (testdata/hmac_v1_vectors.json).

testdata/hmac_v1_vectors.json is copied unchanged from
processing-api-gateway/internal/auth/testdata. Every record is run through both
sides: the SDK signs it, and gateway_hmac - the gateway's check - verifies it,
including the records the gateway refuses.
"""

import hashlib
import hmac
from collections import Counter

import pytest

import gateway_hmac
import vectors
from cryptochief import CryptoChiefClient, CryptoChiefError, hmac_v1_sign, hmac_v1_string_to_sign
from cryptochief.sign import hmac_v1_body_sha256

VECTORS_FILE = vectors.REQUEST_VECTORS_FILE
VECTORS = vectors.REQUEST_VECTORS
BY_NAME = {v["name"]: v for v in VECTORS}
IDS = [v["name"] for v in VECTORS]
REFUSED = [v for v in VECTORS if v["expect"] != gateway_hmac.OK]


def _fields(v: dict) -> dict:
    return {
        "timestamp": v["timestamp"],
        "nonce": v["nonce"],
        "method": v["method"],
        "path": v["path"],
        "query": v["query"],
        "merchant": v["merchant"],
        "idempotency_key": v["idempotency_key"],
        "body": v["body"].encode("utf-8"),
    }


def default_headers(v: dict) -> dict:
    """The headers built from the record's fields, before its overrides."""
    headers = {
        "Merchant": [v["merchant"]],
        "X-CC-Timestamp": [v["timestamp"]],
        "X-CC-Nonce": [v["nonce"]],
        "X-CC-Signature": [gateway_hmac.SIGNATURE_PREFIX + v["signature"]],
    }
    if v["idempotency_key"]:
        headers["Idempotency-Key"] = [v["idempotency_key"]]
    if v["body"]:
        headers["Content-Type"] = ["application/json"]
    return headers


def received(v: dict, *, overrides: bool = True) -> gateway_hmac.SignedRequest:
    """The request the gateway sees: headers from the fields, then the record's overrides."""
    headers = default_headers(v)
    if overrides:
        for name, values in v.get("headers", {}).items():
            for existing in [n for n in headers if n.lower() == name.lower()]:
                del headers[existing]
            headers[name] = values
    return gateway_hmac.SignedRequest(
        method=v["method"],
        path=v["path"],
        query=v["query"],
        body=v["body"].encode("utf-8"),
        headers=[(name, value) for name, values in headers.items() for value in values],
    )


def sdk_signed(
    *,
    api_key: str,
    method: str = "POST",
    path: str = "/v1/wallets/info",
    query: str = "",
    merchant: str = "3f2a1b4c-5d6e-7f80-9a1b-2c3d4e5f6071",
    idempotency_key: str = "",
    body: bytes = b'{"address":"TLa2f6VPqDgRE67v1736s7bJ8Ray5wYjU7"}',
    timestamp: str = "1789430400",
    nonce: str = "0123456789abcdef0123456789abcdef",
) -> gateway_hmac.SignedRequest:
    """A request the SDK signed, in the shape the gateway receives it."""
    signature = hmac_v1_sign(
        api_key,
        timestamp=timestamp,
        nonce=nonce,
        method=method,
        path=path,
        merchant=merchant,
        query=query,
        idempotency_key=idempotency_key,
        body=body,
    )
    headers = [
        ("Merchant", merchant),
        ("X-CC-Timestamp", timestamp),
        ("X-CC-Nonce", nonce),
        ("X-CC-Signature", gateway_hmac.SIGNATURE_PREFIX + signature),
    ]
    if idempotency_key:
        headers.append(("Idempotency-Key", idempotency_key))
    if body:
        headers.append(("Content-Type", "application/json"))
    return gateway_hmac.SignedRequest(
        method=method, path=path, query=query, body=body, headers=headers
    )


# -- Reference vectors ---------------------------------------------------------


def test_vector_file_is_the_reference_copy():
    assert vectors.REQUEST_VECTORS_SHA256 == (
        "a87df4921399dc14c7ceaa7e4c0dfa02495ad0400a5e722adfc0d3e3c1e064fe"
    )
    assert hashlib.sha256(VECTORS_FILE.read_bytes()).hexdigest() == (
        vectors.REQUEST_VECTORS_SHA256
    )
    assert b"\r" not in VECTORS_FILE.read_bytes()
    assert len(VECTORS) == len(BY_NAME) == 50
    assert Counter(v["expect"] for v in VECTORS) == {
        "ok": 21,
        "bad_auth_headers": 24,
        "invalid_signature": 3,
        "timestamp_out_of_range": 2,
    }


@pytest.mark.parametrize("v", VECTORS, ids=IDS)
def test_vector_string_to_sign_and_signature(v):
    """Signing side: every record, refusals included, has a correct signature."""
    fields = _fields(v)
    assert hmac_v1_body_sha256(fields["body"]) == v["body_sha256"]
    assert hmac_v1_string_to_sign(**fields) == v["string_to_sign"]
    assert hmac_v1_sign(v["api_key"], **fields) == v["signature"]


@pytest.mark.parametrize("v", VECTORS, ids=IDS)
def test_vector_verify(v):
    """Verifying side: the gateway's check gives exactly the expected outcome."""
    outcome = gateway_hmac.check(received(v), api_key=v["api_key"], now=v["now"])
    assert outcome == v["expect"]


@pytest.mark.parametrize("v", REFUSED, ids=[v["name"] for v in REFUSED])
def test_refused_vector_has_one_defect(v):
    """Without its single defect - the header override or the clock - the record passes."""
    now = int(v["timestamp"]) if v["expect"] == gateway_hmac.TIMESTAMP_OUT_OF_RANGE else v["now"]
    outcome = gateway_hmac.check(
        received(v, overrides=False), api_key=v["api_key"], now=now
    )
    assert outcome == gateway_hmac.OK


def test_str_body_is_utf8():
    v = BY_NAME["json_null_html_chars_non_ascii_u2028_numbers"]
    fields = {**_fields(v), "body": v["body"]}
    assert hmac_v1_sign(v["api_key"], **fields) == v["signature"]


def test_line_break_in_body_is_allowed():
    v = BY_NAME["body_whitespace_and_line_breaks"]
    assert hmac_v1_sign(v["api_key"], **_fields(v)) == v["signature"]


@pytest.mark.parametrize(
    "field", ["timestamp", "nonce", "method", "path", "query", "merchant", "idempotency_key"]
)
@pytest.mark.parametrize("brk", ["\n", "\r"])
def test_line_break_in_field_is_rejected(field, brk):
    fields = {**_fields(VECTORS[0]), field: "x" + brk + "y"}
    with pytest.raises(CryptoChiefError):
        hmac_v1_string_to_sign(**fields)
    with pytest.raises(CryptoChiefError):
        hmac_v1_sign("k", **fields)


# -- Method --------------------------------------------------------------------


def test_method_is_uppercased():
    v = BY_NAME["get_query_empty_body"]
    fields = {**_fields(v), "method": "get"}
    assert hmac_v1_string_to_sign(**fields) == v["string_to_sign"]
    assert hmac_v1_sign(v["api_key"], **fields) == v["signature"]


@pytest.mark.parametrize(
    ("method", "signed_as"),
    [
        ("pOsT", "POST"),
        ("post", "POST"),
        ("poßt", "POßT"),
        ("getſ", "GETſ"),
        ("Grüß", "GRüß"),
        ("ıd", "ıD"),
    ],
)
def test_method_is_uppercased_in_ascii_only(method, signed_as):
    """Only a-z is raised; other bytes go into the string to sign as they are."""
    fields = {**_fields(VECTORS[0]), "method": method}
    assert hmac_v1_string_to_sign(**fields).split("\n")[3] == signed_as


@pytest.mark.parametrize("method", ["POST", "post", "pOsT", "poßt", "getſ", "ıd", "PATCH"])
def test_method_case_matches_the_gateway(method):
    """The gateway sees the method as sent and raises the same letters."""
    key = "test_api_key_123"
    req = sdk_signed(api_key=key, method=method)
    assert gateway_hmac.check(req, api_key=key, now=1789430400) == gateway_hmac.OK


@pytest.mark.parametrize("method", ["poßt", "getſ", "PO ST", "GET\n", "GET\r\nX:1", ""])
async def test_client_refuses_a_method_that_is_not_a_token(method):
    async with CryptoChiefClient(merchant_id="M1", api_key="secret") as client:
        with pytest.raises(CryptoChiefError, match="method"):
            await client.request("/v1/wallets/info", {}, method=method)


# -- Path and query ------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "query"),
    [
        ("/v1/orders/payout/8814", ""),
        ("/v1/a/b c", ""),
        ("/v1/кошелёк/info", ""),
        ("/v1/wallets/info", "q=%D0%BA%D0%BE%D1%84%D0%B5&x=a%2Fb"),
        ("/v1/a/b c", "note=a+b&raw=%20"),
    ],
)
def test_decoded_path_and_raw_query_pass_the_gateway(path, query):
    """The gateway reads the path percent-decoded and the query as sent."""
    key = "test_api_key_123"
    req = sdk_signed(api_key=key, path=path, query=query)
    assert gateway_hmac.check(req, api_key=key, now=1789430400) == gateway_hmac.OK


def test_signing_the_encoded_path_does_not_pass_the_gateway():
    key = "test_api_key_123"
    req = sdk_signed(api_key=key, path="/v1/orders/payout%2F8814")
    req.path = "/v1/orders/payout/8814"  # what the server reads
    assert gateway_hmac.check(req, api_key=key, now=1789430400) == gateway_hmac.INVALID_SIGNATURE


# -- Empty key -----------------------------------------------------------------


@pytest.mark.parametrize("api_key", ["", " ", "\t", " \t "])
def test_blank_api_key_is_an_error_for_the_signer(api_key):
    with pytest.raises(CryptoChiefError, match="api_key"):
        hmac_v1_sign(api_key, **_fields(VECTORS[0]))
    with pytest.raises(CryptoChiefError, match="api_key"):
        CryptoChiefClient(merchant_id="M1", api_key=api_key)


@pytest.mark.parametrize("api_key", ["", " ", "\t", " \t "])
def test_blank_api_key_is_refused_by_the_gateway(api_key):
    """Even a request signed with that key, by hand, is refused."""
    req = sdk_signed(api_key="test_api_key_123")
    string_to_sign = gateway_hmac.string_to_sign(
        timestamp="1789430400",
        nonce="0123456789abcdef0123456789abcdef",
        method=req.method,
        path=req.path,
        query=req.query,
        merchant="3f2a1b4c-5d6e-7f80-9a1b-2c3d4e5f6071",
        idempotency_key="",
        body=req.body,
    )
    signature = hmac.new(
        api_key.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    req.headers = [
        (name, gateway_hmac.SIGNATURE_PREFIX + signature if name == "X-CC-Signature" else value)
        for name, value in req.headers
    ]
    assert gateway_hmac.check(req, api_key=api_key, now=1789430400) == (
        gateway_hmac.INVALID_SIGNATURE
    )
