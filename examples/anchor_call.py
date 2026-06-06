"""anchor_call - a Solana Anchor program instruction with typed Borsh args.

    MERCHANT_ID=... API_KEY=... FROM_ADDRESS=... PROGRAM=... python examples/anchor_call.py
"""

import asyncio
import os

from cryptochief import (
    AnchorCallRequest,
    Chain,
    CryptoChiefClient,
    SolanaAccount,
    borsh_string,
    borsh_u64,
)


def need(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise SystemExit(f"set {key} in the environment")
    return value


async def main() -> None:
    from_address = need("FROM_ADDRESS")
    async with CryptoChiefClient(merchant_id=need("MERCHANT_ID"), api_key=need("API_KEY")) as client:
        signed = await client.transactions.sign_anchor_call(
            AnchorCallRequest(
                network=Chain.SOLANA_MAINNET,
                from_address=from_address,
                program=need("PROGRAM"),
                method="initialize",
                # Borsh has no on-wire type tags - describe each arg explicitly.
                args=[borsh_u64(1_000), borsh_string("hello")],
                # Solana has no on-chain ABI; supply the account metas yourself.
                accounts=[SolanaAccount(pubkey=from_address, is_signer=True, is_writable=True)],
            )
        )
        print("signed Anchor call:", signed.uuid, signed.tx_hash)


if __name__ == "__main__":
    asyncio.run(main())
