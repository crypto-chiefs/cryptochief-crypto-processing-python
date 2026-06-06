"""quickstart - list the project's enabled assets and read a wallet balance.

    MERCHANT_ID=... API_KEY=... ADDRESS=0x... python examples/quickstart.py
"""

import asyncio
import os

from cryptochief import Chain, CryptoChiefClient


def need(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise SystemExit(f"set {key} in the environment")
    return value


async def main() -> None:
    async with CryptoChiefClient(merchant_id=need("MERCHANT_ID"), api_key=need("API_KEY")) as client:
        resp = await client.blockchain.contracts_available(Chain.ETH_SEPOLIA)
        items = resp.items or []
        print(f"enabled assets on ETH Sepolia: {len(items)}")
        for a in items[:5]:
            print(f"  {a.coin:<6} type={a.type or 'native'} decimals={a.decimals} {a.contract or ''}")

        address = os.environ.get("ADDRESS")
        if address:
            for row in await client.blockchain.wallet_balance(Chain.ETH_SEPOLIA, [address]):
                print(f"balance {row.address}: {row.human_value} ({row.value} base units)")


if __name__ == "__main__":
    asyncio.run(main())
