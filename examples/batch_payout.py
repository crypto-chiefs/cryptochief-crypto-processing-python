"""batch_payout - mass payout with concurrent per-item polling.

    MERCHANT_ID=... API_KEY=... TO_ADDRESS=0x... python examples/batch_payout.py
"""

import asyncio
import os

from cryptochief import (
    BatchPayoutRequest,
    Chain,
    CryptoChiefClient,
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
        items = [
            ExecutePayoutRequest(
                order_id=f"batch-demo-{i}",
                user_id=f"user-{i}",
                network=Chain.ETH_SEPOLIA,
                coin="ETH",
                amount="0.0001",
                to_address=to_address,
                url_callback="https://example.com/cb",
            )
            for i in range(3)
        ]

        result = await client.payouts.batch_execute(BatchPayoutRequest(items=items))
        print(f"batch {result.batch_uuid}: accepted={result.accepted} rejected={result.rejected}")

        # Poll every accepted item concurrently.
        accepted = [it for it in (result.items or []) if it.uuid]
        finals = await asyncio.gather(
            *(client.payouts.wait_for(it.uuid, timeout=300) for it in accepted)
        )
        for it, final in zip(accepted, finals):
            print(f"  {it.order_id}: {final.status} {final.txid or ''}")


if __name__ == "__main__":
    asyncio.run(main())
