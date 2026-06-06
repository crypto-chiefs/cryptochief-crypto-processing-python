"""ton_jetton_transfer - a USDT Jetton transfer with an auto-resolved Jetton wallet.

The sender's Jetton wallet address is resolved via the TON RPC proxy, and a
sensible gas budget is chosen automatically. No BoC encoding in user code.

    MERCHANT_ID=... API_KEY=... FROM_ADDRESS=UQ... TO_ADDRESS=UQ... python examples/ton_jetton_transfer.py
"""

import asyncio
import os

from cryptochief import Chain, CryptoChiefClient, JettonTransferRequest, human_to_base


def need(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise SystemExit(f"set {key} in the environment")
    return value


async def main() -> None:
    # USDT Jetton master on TON.
    jetton_master = os.environ.get("JETTON_MASTER", "EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs")
    async with CryptoChiefClient(merchant_id=need("MERCHANT_ID"), api_key=need("API_KEY")) as client:
        signed = await client.transactions.jetton_transfer(
            JettonTransferRequest(
                network=Chain.TON_MAINNET,
                from_address=need("FROM_ADDRESS"),
                jetton_master=jetton_master,
                recipient=need("TO_ADDRESS"),
                amount=human_to_base("5", 6),  # USDT has 6 decimals
                memo="Order #4242",  # shown by the recipient's wallet
            )
        )
        print("signed Jetton transfer:", signed.uuid, signed.tx_hash)


if __name__ == "__main__":
    asyncio.run(main())
