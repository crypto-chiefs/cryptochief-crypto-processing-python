"""examples/webhook_server.py over real HTTP: raw body and headers as a server receives them."""

import importlib.util
import json
import threading
import time
from http.server import HTTPServer
from pathlib import Path

import httpx
import pytest

from cryptochief import sign_webhook_v1

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "webhook_server.py"
KEY = "example_api_key"
DELIVERY = "0b8f4d2e-3a71-4c5e-9f06-1d2c3b4a5e6f"


@pytest.fixture
def server_url(monkeypatch):
    monkeypatch.setenv("API_KEY", KEY)
    spec = importlib.util.spec_from_file_location("webhook_server_example", EXAMPLE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    server = HTTPServer(("127.0.0.1", 0), module.Handler)
    thread = threading.Thread(target=server.serve_forever, args=(0.02,), daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/webhook"
    finally:
        server.shutdown()
        server.server_close()


def post(url, body: bytes, headers: dict) -> httpx.Response:
    with httpx.Client(timeout=5) as http:
        return http.post(url, content=body, headers={"Content-Type": "application/json", **headers})


def signed_headers(body: bytes, *, key=KEY, ts=None, delivery=DELIVERY) -> dict:
    ts = int(time.time()) if ts is None else ts
    return {
        "X-Webhook-Delivery": delivery,
        "X-CC-Timestamp": str(ts),
        "X-CC-Signature": sign_webhook_v1(key, ts, delivery, body),
    }


SWEEP = json.dumps(
    {
        "event": "sweep.confirmed",
        "task_id": "t-1",
        "status": "completed",
        "wallet_address": "0xdeposit",
        "network": "ETH_MAINNET",
        "asset_symbol": "USDT",
        "sweep_tx_hash": "0xsweep",
        "sweep_confirmations": 12,
    },
    indent=2,
).encode("utf-8")


def test_accepts_a_signed_webhook(server_url, capsys):
    resp = post(server_url, SWEEP, signed_headers(SWEEP))
    assert (resp.status_code, resp.text) == (200, "ok")
    out = capsys.readouterr().out
    assert f"delivery {DELIVERY}" in out
    assert "sweep t-1" in out


def test_lowercase_header_names_are_accepted(server_url):
    headers = {k.lower(): v for k, v in signed_headers(SWEEP).items()}
    assert post(server_url, SWEEP, headers).status_code == 200


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda body, h: (body.replace(b"12", b"13"), h), "signature"),
        (lambda body, h: (body, {**h, "X-Webhook-Delivery": "other-delivery"}), "signature"),
        (lambda body, h: (body, signed_headers(body, key="other")), "signature"),
        (lambda body, h: (body, signed_headers(body, ts=int(time.time()) - 3600)), "timestamp"),
        (lambda body, h: (body, {k: v for k, v in h.items() if k != "X-CC-Timestamp"}), "headers"),
        (lambda body, h: (body, {**h, "X-CC-Signature": h["X-CC-Signature"][3:]}), "headers"),
        (
            lambda body, h: (
                body,
                {
                    "Signature": "8b85b5464c9a92059a74039d7a008618",
                    "X-Webhook-Delivery": h["X-Webhook-Delivery"],
                },
            ),
            "headers",
        ),
    ],
    ids=[
        "tampered-body",
        "other-delivery-id",
        "other-key",
        "stale-timestamp",
        "no-timestamp",
        "signature-without-prefix",
        "md5-signature-only",
    ],
)
def test_refuses_with_401(server_url, mutate, reason):
    body, headers = mutate(SWEEP, signed_headers(SWEEP))
    resp = post(server_url, body, headers)
    assert (resp.status_code, resp.text) == (401, f"invalid webhook: {reason}")


def test_repeated_signature_header_is_refused(server_url):
    headers = signed_headers(SWEEP)
    pairs = list(headers.items()) + [("X-CC-Signature", headers["X-CC-Signature"])]
    with httpx.Client(timeout=5) as http:
        resp = http.post(server_url, content=SWEEP, headers=pairs)
    assert (resp.status_code, resp.text) == (401, "invalid webhook: headers")


def test_verified_body_that_is_not_json_is_400(server_url):
    body = b"not json"
    assert post(server_url, body, signed_headers(body)).status_code == 400
