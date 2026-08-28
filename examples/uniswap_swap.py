"""uniswap_swap - a real swapExactTokensForTokens contract call (EVM).

The ABI calldata is built from the Solidity signature + args - you never encode
``data`` by hand.

Two transactions, not one: the router pulls the input token out of your wallet
with ``transferFrom``, so it needs an ERC-20 allowance first. Approve, let that
confirm, then swap - a swap signed before the approve is mined reserves the same
nonce and reverts.

    MERCHANT_ID=... API_KEY=... FROM_ADDRESS=0x... MIN_OUT=1234.5 \
        python examples/uniswap_swap.py

Set BROADCAST=1 to actually send both transactions; without it the example stops
after signing the approve.
"""

import asyncio
import os
import time

from cryptochief import (
    Chain,
    CryptoChiefClient,
    EvmCallRequest,
    ExecuteTransactionRequest,
    TxStatus,
    human_to_base,
)


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
    broadcast = bool(os.environ.get("BROADCAST"))

    amount_in = human_to_base("100", 18)
    # Slippage floor, in the output token's base units. Zero accepts whatever the
    # pool returns, which on a public mempool hands the trade to the first
    # sandwich bot that sees it, so it has to be asked for rather than defaulted.
    amount_out_min = human_to_base(need("MIN_OUT"), 18)  # 18 decimals; USDC/USDT are 6
    if amount_out_min == 0:
        print("MIN_OUT=0 - no slippage protection on this swap")

    async with CryptoChiefClient(merchant_id=need("MERCHANT_ID"), api_key=need("API_KEY")) as client:
        # The allowance the router needs before it can move token_in.
        approve = await client.transactions.sign_evm_call(
            EvmCallRequest(
                network=Chain.ETH_MAINNET,
                from_address=from_address,
                contract=token_in,
                method="approve(address,uint256)",
                args=[router, amount_in],
            )
        )
        print("signed approve:", approve.uuid, "tx_hash:", approve.tx_hash)

        if not broadcast:
            print("BROADCAST unset - stopping after the approve signature")
            return

        await client.transactions.execute(ExecuteTransactionRequest(uuid=approve.uuid))
        approved = await client.transactions.wait_for(approve.uuid, timeout=480)
        if approved.status != TxStatus.CONFIRMED:
            raise SystemExit(f"approve did not confirm: status={approved.status}")
        print("approve confirmed:", approved.tx_hash)

        signed = await client.transactions.sign_evm_call(
            EvmCallRequest(
                network=Chain.ETH_MAINNET,
                from_address=from_address,
                contract=router,
                method="swapExactTokensForTokens(uint256,uint256,address[],address,uint256)",
                args=[
                    amount_in,  # amount in
                    amount_out_min,  # min amount out
                    [token_in, token_out],  # path
                    from_address,  # recipient
                    int(time.time()) + 1200,  # deadline
                ],
            )
        )
        print("signed swap:", signed.uuid, "tx_hash:", signed.tx_hash)

        await client.transactions.execute(ExecuteTransactionRequest(uuid=signed.uuid))
        final = await client.transactions.wait_for(signed.uuid, timeout=480)
        print("terminal:", final.status, final.tx_hash)


if __name__ == "__main__":
    asyncio.run(main())
