"""webhook_server - verify webhook signatures and dispatch typed events.

The verification helpers do no I/O, so a plain (sync) stdlib server is enough -
use them the same way inside FastAPI / aiohttp / Django.

    API_KEY=... python examples/webhook_server.py

FastAPI equivalent:

    @app.post("/webhook")
    async def hook(request: Request):
        raw = await request.body()  # the EXACT bytes
        try:
            event = parse_webhook_event(API_KEY, raw, request.headers.get("Signature"))
        except WebhookSignatureError:
            raise HTTPException(401, "bad signature")
        ...  # handle event
        return {"ok": True}
"""

import os
from http.server import BaseHTTPRequestHandler, HTTPServer

from cryptochief import (
    WEBHOOK_HEADER,
    WEBHOOK_SENDER_IPS,
    PayInWebhookEvent,
    PayoutWebhookEvent,
    StaticDepositWebhookEvent,
    TransactionWebhookEvent,
    WebhookSignatureError,
    parse_webhook_event,
)

API_KEY = os.environ.get("API_KEY") or ""
if not API_KEY:
    raise SystemExit("set API_KEY in the environment")


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - stdlib naming
        if self.path != "/webhook":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        try:
            event = parse_webhook_event(API_KEY, raw, self.headers.get(WEBHOOK_HEADER))
        except WebhookSignatureError:
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b"invalid signature")
            return

        if isinstance(event, PayoutWebhookEvent):
            print(f"payout {event.uuid}: {event.status}")  # paid | system_fail
        elif isinstance(event, TransactionWebhookEvent):
            print(f"transaction {event.uuid}: {event.status}")  # confirmed | failed | expired
        elif isinstance(event, PayInWebhookEvent):
            print(f"invoice {event.uuid}: {event.status}")  # paid | expired | ...
        elif isinstance(event, StaticDepositWebhookEvent):
            print(f"static_deposit {event.uuid}: {event.status}")
        else:
            print("unhandled event:", event.get("event"))

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *_args: object) -> None:  # quiet default logging
        pass


if __name__ == "__main__":
    print("webhook server on http://localhost:3000/webhook")
    print("whitelist sender IPs at your edge:", ", ".join(WEBHOOK_SENDER_IPS))
    HTTPServer(("127.0.0.1", 3000), Handler).serve_forever()
