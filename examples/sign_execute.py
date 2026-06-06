"""sign_execute - two-phase sign + broadcast of a native transfer.

    MERCHANT_ID=... API_KEY=... FROM_ADDRESS=0x... TO_ADDRESS=0x... python examples/sign_execute.py
"""

import asyncio
import os

from cryptochief import (
    Chain,
    CryptoChiefClient,
    ExecuteTransactionRequest,
    SignTransactionRequest,
    TxType,
    human_to_base,
)


def need(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise SystemExit(f"set {key} in the environment")
    return value


async def main() -> None:
    async with CryptoChiefClient(merchant_id=need("MERCHANT_ID"), api_key=need("API_KEY")) as client:
        signed = await client.transactions.sign(
            SignTransactionRequest(
                network=Chain.ETH_SEPOLIA,
                from_address=need("FROM_ADDRESS"),
                type=TxType.NATIVE,
                to_address=need("TO_ADDRESS"),
                value=str(human_to_base("0.0001", 18)),  # value is in BASE units (wei)
                url_callback="https://example.com/cb",
            )
        )
        print("signed:", signed.uuid, "expires_at:", signed.expires_at)

        # Broadcast before the per-family signature TTL elapses.
        info = await client.transactions.execute(ExecuteTransactionRequest(uuid=signed.uuid))
        print("broadcasted:", info.status, info.tx_hash)

        final = await client.transactions.wait_for(signed.uuid, timeout=300)
        print("final:", final.status, final.tx_hash)


if __name__ == "__main__":
    asyncio.run(main())
