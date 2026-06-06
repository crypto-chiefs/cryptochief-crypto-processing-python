"""trc20_transfer - a TRC-20 transfer using the erc20_transfer one-liner.

TRON base58 addresses are accepted directly inside the ABI.

    MERCHANT_ID=... API_KEY=... FROM_ADDRESS=T... TO_ADDRESS=T... python examples/trc20_transfer.py
"""

import asyncio
import os

from cryptochief import Chain, CryptoChiefClient, Erc20TransferRequest, human_to_base


def need(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise SystemExit(f"set {key} in the environment")
    return value


async def main() -> None:
    usdt = os.environ.get("TOKEN", "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t")  # USDT-TRC20
    async with CryptoChiefClient(merchant_id=need("MERCHANT_ID"), api_key=need("API_KEY")) as client:
        signed = await client.transactions.erc20_transfer(
            Erc20TransferRequest(
                network=Chain.TRON_MAINNET,
                from_address=need("FROM_ADDRESS"),
                token_contract=usdt,
                recipient=need("TO_ADDRESS"),
                amount=human_to_base("12.5", 6),  # USDT has 6 decimals
            )
        )
        print("signed TRC-20 transfer:", signed.uuid, signed.tx_hash)


if __name__ == "__main__":
    asyncio.run(main())
