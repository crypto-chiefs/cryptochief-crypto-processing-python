"""wallet_generate - provision a wallet and decrypt its private key locally.

    MERCHANT_ID=... API_KEY=... RSA_PRIVATE_KEY_FILE=key.pem python examples/wallet_generate.py
"""

import asyncio
import os

from cryptochief import ChainFamily, CryptoChiefClient, GenerateWalletRequest, WalletType


def need(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise SystemExit(f"set {key} in the environment")
    return value


async def main() -> None:
    rsa_pem = None
    key_file = os.environ.get("RSA_PRIVATE_KEY_FILE")
    if key_file:
        rsa_pem = open(key_file, "rb").read()

    async with CryptoChiefClient(
        merchant_id=need("MERCHANT_ID"), api_key=need("API_KEY"), rsa_private_key=rsa_pem
    ) as client:
        wallet = await client.wallets.generate(
            GenerateWalletRequest(wallet_type=WalletType.MASTER, chain_family=ChainFamily.EVM)
        )
        print("address:", wallet.address)

        if wallet.private_key_encrypted and rsa_pem:
            priv = client.wallets.decrypt_private_key(wallet.private_key_encrypted)
            print("decrypted private key (keep secret!):", priv[:6] + "..." + priv[-4:])

        # Read it back with current balances.
        info = await client.wallets.info(wallet.address)
        for coin in info.coins or []:
            print(f"  {coin.coin}: {coin.human_value}")


if __name__ == "__main__":
    asyncio.run(main())
