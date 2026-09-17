"""The client over real HTTP against a mock gateway that checks HMAC v1 as the server does.

The check is gateway_hmac - the gateway's own rules, computing the string to sign
from the received request. The mock never reads the ``Signature`` header.
"""

import json
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

import gateway_hmac
from cryptochief import APIError, CryptoChiefClient, CryptoChiefError, ErrorCode, idempotency_key

MERCHANT = "M-mock"
API_KEY = "mock_api_key"


class MockGateway:
    def __init__(self) -> None:
        self.clock_offset = 0
        self.nonces: set = set()
        self.received: list = []  # (path, headers dict of lists, body) of every request
        self.accepted = 0


def make_handler(gw: MockGateway):
    class Handler(BaseHTTPRequestHandler):
        def handle_signed(self) -> None:
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            names = {k.lower() for k in self.headers.keys()}
            gw.received.append((self.path, {n: self.headers.get_all(n) for n in names}, body))

            raw_path, _, query = self.path.partition("?")
            req = gateway_hmac.SignedRequest(
                method=self.command,
                path=urllib.parse.unquote(raw_path),  # the gateway reads r.URL.Path
                query=query,
                body=body,
                headers=list(self.headers.items()),
            )
            now = int(time.time()) + gw.clock_offset
            outcome = gateway_hmac.check(req, api_key=API_KEY, now=now)
            if outcome == gateway_hmac.BAD_AUTH_HEADERS:
                return self.reply(400, {"ok": False, "error": "BAD_AUTH_HEADERS"})
            if outcome == gateway_hmac.TIMESTAMP_OUT_OF_RANGE:
                return self.reply(
                    401,
                    {"ok": False, "error": "SIGNATURE_TIMESTAMP_OUT_OF_RANGE", "server_time": now},
                )

            merchant = (self.headers.get("Merchant") or "").strip(" \t")
            if outcome != gateway_hmac.OK or merchant != MERCHANT:
                return self.reply(401, {"ok": False, "error": "INVALID_SIGNATURE"})

            nonce = (self.headers.get("X-CC-Nonce") or "").strip(" \t")
            if (MERCHANT, nonce) in gw.nonces:
                return self.reply(401, {"ok": False, "error": "SIGNATURE_REPLAYED"})
            gw.nonces.add((MERCHANT, nonce))
            gw.accepted += 1
            self.reply(
                200,
                {
                    "method": req.method,
                    "path": req.path,
                    "query": req.query,
                    "idempotency_key": (self.headers.get("Idempotency-Key") or "").strip(" \t"),
                    "body": json.loads(body or b"null"),
                },
            )

        # stdlib dispatch: do_<METHOD>
        do_POST = handle_signed
        do_GET = handle_signed
        do_PUT = handle_signed
        do_PATCH = handle_signed
        do_DELETE = handle_signed

        def reply(self, status: int, payload: dict) -> None:
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_args: object) -> None:
            pass

    return Handler


@pytest.fixture
def gateway():
    gw = MockGateway()
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(gw))
    thread = threading.Thread(target=server.serve_forever, args=(0.02,), daemon=True)
    thread.start()
    try:
        yield gw, f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def client(gateway):
    gw, base_url = gateway
    return CryptoChiefClient(merchant_id=MERCHANT, api_key=API_KEY, base_url=base_url)


async def test_client_requests_pass_the_mock_gateway(gateway, client):
    gw, _ = gateway
    async with client as c:
        info = await c.request("/v1/payout/info", {"uuid": "u1", "memo": None})
        big = await c.request("/v1/raw?b=2&a=1", {"n": 2**64 + 1, "s": "Кофе & <x>"})
        empty = await c.request("/v1/credits/balance", None)
        idem = await c.request("/v1/payout/execute", {"order_id": "o-1"}, idempotency_key="k-1")
        balance = await c.credits.balance()

    assert info["path"] == "/v1/payout/info"
    assert info["query"] == ""
    assert info["body"] == {"uuid": "u1"}
    assert big["query"] == "b=2&a=1"
    assert big["body"] == {"n": 2**64 + 1, "s": "Кофе & <x>"}
    assert empty["body"] is None
    assert idem["body"] == {"order_id": "o-1"}
    assert idem["idempotency_key"] == "k-1"
    assert balance is not None
    assert gw.accepted == 5
    for _, headers, _ in gw.received:
        assert "signature" not in headers


async def test_percent_escaped_path_passes_the_mock_gateway(gateway, client):
    gw, _ = gateway
    async with client as c:
        out = await c.request("/v1/a%2Fb%20c", {"uuid": "u1"})
    assert out["path"] == "/v1/a/b c"
    assert gw.received[0][0] == "/v1/a%2Fb%20c"
    assert gw.accepted == 1


async def test_non_ascii_path_and_query_pass_the_mock_gateway(gateway, client):
    gw, _ = gateway
    async with client as c:
        out = await c.request("/v1/кошелёк/info?q=кофе&x=a%2Fb", {"адрес": "TLa2f6"})
    assert out["path"] == "/v1/кошелёк/info"
    assert out["query"] == "q=%D0%BA%D0%BE%D1%84%D0%B5&x=a%2Fb"
    assert out["body"] == {"адрес": "TLa2f6"}
    assert gw.received[0][0] == "/v1/%D0%BA%D0%BE%D1%88%D0%B5%D0%BB%D1%91%D0%BA/info?" + (
        "q=%D0%BA%D0%BE%D1%84%D0%B5&x=a%2Fb"
    )
    assert gw.accepted == 1


async def test_signed_get_with_query_passes_the_mock_gateway(gateway, client):
    gw, _ = gateway
    async with client as c:
        out = await c.request(
            "/v1/payments/order/info?uuid=5b0c7a52&note=a%20b", method="get"
        )
    assert out == {
        "method": "GET",
        "path": "/v1/payments/order/info",
        "query": "uuid=5b0c7a52&note=a%20b",
        "idempotency_key": "",
        "body": None,
    }
    _, headers, body = gw.received[0]
    assert body == b""
    assert "content-type" not in headers  # no body, no Content-Type
    assert gw.accepted == 1


async def test_signed_request_with_another_method(gateway, client):
    gw, _ = gateway
    async with client as c:
        out = await c.request("/v1/wallets/info", {"address": "T9y"}, method="put")
    assert out["method"] == "PUT"
    assert out["body"] == {"address": "T9y"}
    assert gw.accepted == 1


async def test_idempotency_key_from_the_context_reaches_the_gateway(gateway, client):
    gw, _ = gateway
    async with client as c:
        with idempotency_key("payout-2026-09-16-0001"):
            await c.credits.balance()
            direct = await c.request("/v1/payout/execute", {"order_id": "o-1"})
            other = await c.request("/v1/payout/execute", {"order_id": "o-2"}, idempotency_key="k-2")
            none = await c.request("/v1/payout/execute", {"order_id": "o-3"}, idempotency_key="")
        outside = await c.request("/v1/payout/execute", {"order_id": "o-4"})

    assert direct["idempotency_key"] == "payout-2026-09-16-0001"
    assert other["idempotency_key"] == "k-2"
    assert none["idempotency_key"] == ""
    assert outside["idempotency_key"] == ""
    assert gw.received[0][1]["idempotency-key"] == ["payout-2026-09-16-0001"]
    assert "idempotency-key" not in gw.received[4][1]
    assert gw.accepted == 5


async def test_idempotency_key_is_checked_before_the_request(gateway, client):
    gw, _ = gateway
    async with client as c:
        for bad in (" k", "k ", "k\t", "ключ", "k\n1"):
            with pytest.raises(CryptoChiefError, match="idempotency_key"):
                await c.request("/v1/payout/execute", {"order_id": "o-1"}, idempotency_key=bad)
            with pytest.raises(CryptoChiefError, match="idempotency_key"):
                with idempotency_key(bad):
                    pass
    assert gw.received == []


async def test_signature_header_without_hmac_headers_is_refused(gateway):
    gw, base_url = gateway
    body = b'{"uuid":"u1"}'
    async with httpx.AsyncClient() as http:
        resp = await http.post(
            base_url + "/v1/payout/info",
            content=body,
            headers={
                "Content-Type": "application/json",
                "Merchant": MERCHANT,
                "Signature": "8b85b5464c9a92059a74039d7a008618",
            },
        )
    assert resp.status_code == 400
    assert resp.json()["error"] == "BAD_AUTH_HEADERS"
    assert gw.accepted == 0


async def test_clock_skew_is_corrected_once_over_http(gateway, client):
    gw, _ = gateway
    gw.clock_offset = 3600
    async with client as c:
        out = await c.request("/v1/payout/info", {"uuid": "u1"})
    assert out["body"] == {"uuid": "u1"}
    assert len(gw.received) == 2
    assert gw.accepted == 1
    first, second = (int(h["x-cc-timestamp"][0]) for _, h, _ in gw.received)
    assert second - first >= 3599


async def test_wrong_key_is_invalid_signature(gateway):
    gw, base_url = gateway
    async with CryptoChiefClient(merchant_id=MERCHANT, api_key="wrong", base_url=base_url) as c:
        with pytest.raises(APIError) as ei:
            await c.request("/v1/payout/info", {"uuid": "u1"})
    assert ei.value.code == ErrorCode.INVALID_SIGNATURE
    assert ei.value.http_status == 401
    assert len(gw.received) == 1


async def test_replayed_request_is_refused(gateway, client):
    gw, base_url = gateway
    async with client as c:
        await c.request("/v1/payout/info", {"uuid": "u1"})
    path, headers, body = gw.received[0]
    replay = {k: v[0] for k, v in headers.items() if k not in ("host", "content-length")}
    async with httpx.AsyncClient() as http:
        resp = await http.post(base_url + path, content=body, headers=replay)
    assert resp.status_code == 401
    assert resp.json()["error"] == "SIGNATURE_REPLAYED"
