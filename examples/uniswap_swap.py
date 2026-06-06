"""uniswap_swap - a real swapExactTokensForTokens contract call (EVM).

The ABI calldata is built from the Solidity signature + args - you never encode
``data`` by hand.

    MERCHANT_ID=... API_KEY=... FROM_ADDRESS=0x... python examples/uniswap_swap.py
"""

import asyncio
import os
import time

from cryptochief import Chain, CryptoChiefClient, EvmCallRequest, human_to_base


def need(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise SystemExit(f"set {key} in the environment")
    return value


async def main() -> None:
    from_address = need("FROM_ADDRESS")
    router = os.environ.get("ROUTER", "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D")  # UniV2
    token_in = os.environ.get("TOKEN_IN", "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2")
    token_out = os.environ.get("TOKEN_OUT", "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48")

    async with CryptoChiefClient(merchant_id=need("MERCHANT_ID"), api_key=need("API_KEY")) as client:
        signed = await client.transactions.sign_evm_call(
            EvmCallRequest(
                network=Chain.ETH_MAINNET,
                from_address=from_address,
                contract=router,
                method="swapExactTokensForTokens(uint256,uint256,address[],address,uint256)",
                args=[
                    human_to_base("100", 18),  # amount in
                    0,  # min amount out
                    [token_in, token_out],  # path
                    from_address,  # recipient
                    int(time.time()) + 1200,  # deadline
                ],
            )
        )
        print("signed swap:", signed.uuid, "tx_hash:", signed.tx_hash)


if __name__ == "__main__":
    asyncio.run(main())
