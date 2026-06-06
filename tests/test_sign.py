"""Signature regression vectors - fixed payloads with known-correct hashes.

A drift in canonical JSON or MD5 wiring fails here before it can fail against the
live API. Secret: "test_api_key_123".
"""

from cryptochief import canonical_json, sign

SECRET = "test_api_key_123"


def test_payout_estimate_vector():
    body = {
        "network": "ETH_SEPOLIA",
        "coin": "ETH",
        "amount": "0.0001",
        "to_address": "0xAbC",
        "from_addresses": ["0x111", "0x222"],
    }
    canonical = canonical_json(body)
    assert canonical == (
        '{"amount":"0.0001","coin":"ETH","from_addresses":["0x111","0x222"],'
        '"network":"ETH_SEPOLIA","to_address":"0xAbC"}'
    )
    assert sign(canonical, SECRET) == "97bd68e4e4dc86b6dad8aa06e1f7b63d"


def test_batch_payout_html_escaped_url():
    body = {
        "items": [
            {"order_id": "b", "user_id": "u", "amount": "1"},
            {"order_id": "a", "user_id": "u2", "amount": "2"},
        ],
        "url_callback": "https://x.io/cb?a=1&b=2",
    }
    assert sign(canonical_json(body), SECRET) == "8b85b5464c9a92059a74039d7a008618"


def test_nested_map_array_html_chars():
    body = {"z": True, "a": 1, "m": {"y": "<tag>", "x": "a&b"}, "arr": [3, 2, 1]}
    assert sign(canonical_json(body), SECRET) == "5fcfb2c41ee9d91073b9adcf22fe8a79"


def test_empty_body():
    assert canonical_json({}) == "{}"
    assert sign(canonical_json({}), SECRET) == "33d8723e69fba9d68b8991ad200be4b3"


def test_none_signs_as_md5_of_key():
    assert canonical_json(None) == ""
    assert sign("", SECRET) == sign(canonical_json(None), SECRET)


def test_drops_none_keeps_empties():
    assert canonical_json({"b": None, "a": "x", "c": None}) == '{"a":"x"}'
    assert canonical_json({"a": "", "b": []}) == '{"a":"","b":[]}'


def test_html_escapes_and_separators():
    assert canonical_json({"k": "<a>&  "}) == '{"k":"\\u003ca\\u003e\\u0026\\u2028\\u2029"}'
