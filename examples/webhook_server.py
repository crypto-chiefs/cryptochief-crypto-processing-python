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
    SweepWebhookEvent,
    TransactionWebhookEvent,
    WebhookSignatureError,
    parse_webhook_event,
)

API_KEY = os.environ.get("API_KEY") or ""
if not API_KEY:
    raise SystemExit("set API_KEY in the environment")


def on_sweep_confirmed(event: SweepWebhookEvent) -> None:
    """Your money finishing its move into your own custody.

    A ``static_deposit.paid`` told you a customer paid. This says the funds have
    been swept off the deposit address and the sweep is confirmed on chain.
    Until it fires the balance still sits on the deposit wallet, so treasury
    reporting and "available to pay out" should key off this, not the deposit.
    """
    print(
        f"sweep {event.task_id}: {event.amount_human} {event.asset_symbol} "
        f"{event.wallet_address} -> {event.to_address} "
        f"tx={event.sweep_tx_hash} confirmations={event.sweep_confirmations} "
        f"trigger={event.type_work} fee_usd={event.total_fee_usd}"
    )

    # task_id is the idempotency key: one sweep settles once. Seeing it twice
    # means a redelivery - acknowledge and stop.
    # if treasury.already_recorded(event.task_id):
    #     return

    # The event only ever arrives confirmed, but apply your own finality policy
    # here if you have one - "confirmed" is not the same number on every chain.
    # treasury.record_settled(event.task_id, event.asset_symbol, event.amount_human, event.sweep_tx_hash)
    # ledger.move_to_available(customer_for(event.wallet_address), event.asset_symbol, event.amount_human)
    # costs.record(event.task_id, event.total_fee_usd)  # sweeps are not free


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
        elif isinstance(event, SweepWebhookEvent):
            on_sweep_confirmed(event)
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
