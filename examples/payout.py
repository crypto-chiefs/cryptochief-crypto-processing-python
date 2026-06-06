"""payout - a single end-to-end payout with confirmation.

    MERCHANT_ID=... API_KEY=... TO_ADDRESS=0x... URL_CALLBACK=... python examples/payout.py
"""

import asyncio
import os

from cryptochief import (
    APIError,
    Chain,
    CryptoChiefClient,
    ErrorCode,
    EstimatePayoutRequest,
    ExecutePayoutRequest,
)


def need(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise SystemExit(f"set {key} in the environment")
    return value


async def main() -> None:
    async with CryptoChiefClient(merchant_id=need("MERCHANT_ID"), api_key=need("API_KEY")) as client:
        to_address = need("TO_ADDRESS")

        est = await client.payouts.estimate(
            EstimatePayoutRequest(
                network=Chain.ETH_SEPOLIA, coin="ETH", amount="0.0001", to_address=to_address
            )
        )
        print("amount to receive:", est.amount_to_receive)

        try:
            payout = await client.payouts.execute(
                ExecutePayoutRequest(
                    order_id="order-demo-1",  # idempotency key - safe to retry
                    user_id="user-1",
                    network=Chain.ETH_SEPOLIA,
                    coin="ETH",
                    amount="0.0001",
                    to_address=to_address,
                    url_callback=os.environ.get("URL_CALLBACK", "https://example.com/cb"),
                )
            )
        except APIError as err:
            if err.code == ErrorCode.INSUFFICIENT_FUNDS:
                raise SystemExit("top up the project balance and try again") from err
            raise

        print("payout uuid:", payout.uuid, "status:", payout.status)
        final = await client.payouts.wait_for(payout.uuid, timeout=300)
        print("final status:", final.status, "txid:", final.txid)


if __name__ == "__main__":
    asyncio.run(main())
