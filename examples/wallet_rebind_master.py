"""wallet_rebind_master - fix a deposit wallet that settles, notifies or reads wrong.

All three operations correct a decision made when the address was minted: which
master it sweeps into, where its deposits are announced, and what it is called.

    MERCHANT_ID=... API_KEY=... ADDRESS=0x... MASTER_WALLET_ADDRESS=0x... \
        [LABEL="EU shop - order 4471"] \
        [CALLBACK_URL=https://example.com/webhooks/deposits] \
        python examples/wallet_rebind_master.py
"""

import asyncio
import os

from cryptochief import CryptoChiefClient, WalletType


def need(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise SystemExit(f"set {key} in the environment")
    return value


async def main() -> None:
    address = need("ADDRESS")

    async with CryptoChiefClient(
        merchant_id=need("MERCHANT_ID"), api_key=need("API_KEY")
    ) as client:
        # Moves no money: it changes where the NEXT sweep settles, including
        # sweeps already queued. Anything already swept stays on the previous
        # master and has to be sent from there as an ordinary payout.
        #
        # Idempotent - a wallet already bound to that master answers 200 and
        # changes nothing, so re-running this over a list is safe.
        wallet = await client.wallets.rebind_master(address, need("MASTER_WALLET_ADDRESS"))
        print("type:", wallet.type)
        print("master is now:", wallet.master_wallet_address)
        # None when the wallet has no name - never an empty string.
        print("name:", wallet.label)

        # Renaming works on every wallet type, master and transit included: a
        # label names the wallet, it does not describe its role. Like the
        # callback below, "" is the CLEAR instruction and so is not defaulted
        # into - an unset LABEL must not wipe the name off a live wallet.
        label = os.environ.get("LABEL")
        if label is not None:
            wallet = await client.wallets.set_label(address, label)
            print("name is now:", wallet.label)

        if wallet.type != WalletType.STATIC.value:
            # A master or transit has no per-deposit callback to set.
            return

        # Deposits are announced to the URL the ADDRESS carries. An empty string
        # clears it and stops the announcements - a real instruction, not a
        # missing field, so it is sent rather than dropped.
        #
        # NOT defaulted to "": that is the CLEAR instruction, so an example run
        # without CALLBACK_URL set would silently stop deposit notifications on
        # a live address. Clearing has to be asked for, never fallen into.
        callback_url = os.environ.get("CALLBACK_URL")
        if callback_url is None:
            print("CALLBACK_URL not set - skipping (pass CALLBACK_URL='' to clear it)")
            return

        wallet = await client.wallets.set_callback_url(address, callback_url)
        # None once cleared: the API answers null, never an empty string.
        print("callback is now:", wallet.callback_url)


if __name__ == "__main__":
    asyncio.run(main())
