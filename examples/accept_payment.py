"""accept_payment - create a pay-in (invoice) and settle it.

Fixes a fiat price; the customer pays the crypto equivalent at the hosted
payment link. In production, settle on the `invoice.*` webhook instead of
blocking on wait_for (see webhook_server.py).

    MERCHANT_ID=... API_KEY=... python examples/accept_payment.py
"""

import asyncio
import os

from cryptochief import CreatePayInRequest, CryptoChiefClient, PayInMode


def need(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise SystemExit(f"set {key} in the environment")
    return value


async def main() -> None:
    async with CryptoChiefClient(merchant_id=need("MERCHANT_ID"), api_key=need("API_KEY")) as client:
        invoice = await client.pay_ins.create(
            CreatePayInRequest(
                order_id="invoice-demo-1",  # your id - idempotency key, safe to retry
                user_id="user-1",
                mode=PayInMode.FIAT,  # fix a fiat price; customer pays the crypto equivalent
                amount_fiat="49.99",
                currency="USD",
                url_callback=os.environ.get("URL_CALLBACK", "https://example.com/cb"),
                url_success=os.environ.get("URL_SUCCESS", "https://example.com/thanks"),
            )
        )
        print("invoice uuid:", invoice.uuid, "status:", invoice.status)
        print("send the customer to:", invoice.payment_link)

        # In production, settle on the invoice.* webhook. Here we just block.
        final = await client.pay_ins.wait_for(invoice.uuid, timeout=1800)
        print("final status:", final.status)  # paid | expired | cancel


if __name__ == "__main__":
    asyncio.run(main())
