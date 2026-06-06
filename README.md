# Crypto Chief Python SDK - Crypto Processing API Client

[![PyPI](https://img.shields.io/pypi/v/cryptochief-crypto-processing-python.svg)](https://pypi.org/project/cryptochief-crypto-processing-python/)
[![Python](https://img.shields.io/pypi/pyversions/cryptochief-crypto-processing-python.svg)](https://pypi.org/project/cryptochief-crypto-processing-python/)
[![SDK Docs](https://img.shields.io/badge/docs-SDK%20guide-2ea44f)](https://docs-sdk.crypto-chief.com/processing/python)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**Crypto Chief Python SDK** is the official **asyncio** client library for the
[Crypto Chief](https://crypto-chief.com/processing/) **crypto processing API** -
a unified crypto payment gateway for accepting crypto payments, sending crypto
payouts (single and mass), signing on-chain transactions, managing wallets, and
verifying webhooks across **Ethereum, Tron, TON, Solana, Bitcoin and 20+ more
blockchains**.

Drop it into any async Python backend (FastAPI, aiohttp, Litestar, Django ASGI,
serverless ...) to add cryptocurrency payment processing - stablecoin
(USDT / USDC) payouts, pay-ins, swaps, and smart-contract calls - with typed
dataclass requests / responses, integer-precise amounts, and an `except`-friendly
error hierarchy.

- One-line setup; a reusable `CryptoChiefClient` you `await`.
- **Typed dataclasses** for every request and response - editor autocomplete and
  attribute access (`est.amount_to_receive`), no dict juggling.
- **Contract calls without hand-encoded calldata** - Solidity ABI for EVM and
  TRON, Anchor + Borsh for Solana, Jetton / NFT / comment helpers for TON.
- **Local RSA decryption** of generated wallet private keys.
- Stable error codes via `APIError.code`, automatic retry on transient failures.
- Arbitrary-precision amounts via native `int` - never `float`.
- Webhook verification + typed events, framework-agnostic.
- `await client.payouts.wait_for(uuid)` polling that resolves when a payout /
  transaction / pay-in is final.

> The wire format is snake_case and so is Python - the public API uses the same
> field names the REST API does, with no translation layer in between.

## Install

```bash
pip install cryptochief-crypto-processing-python
```

```python
import cryptochief
from cryptochief import CryptoChiefClient, Chain
```

Requires Python 3.10+.

## Quick start

```python
import asyncio
from cryptochief import CryptoChiefClient, Chain, EstimatePayoutRequest

async def main():
    async with CryptoChiefClient(
        merchant_id="YOUR_MERCHANT_ID",
        api_key="YOUR_API_KEY",  # signing secret - keep it server-side
    ) as client:
        est = await client.payouts.estimate(EstimatePayoutRequest(
            network=Chain.ETH_SEPOLIA,
            coin="ETH",
            amount="0.0001",
            to_address="0xRecipient...",
        ))
        print("amount to receive:", est.amount_to_receive)

asyncio.run(main())
```

Both credentials come from the Dashboard -> Project.

## What you can do with it

| Domain | Service | Key methods |
|---|---|---|
| Single payout (incl. auto-convert swap) | `client.payouts` | `estimate`, `execute`, `info`, `history`, `wait_for` |
| Mass payout (up to 50 items) | `client.payouts` | `batch_estimate`, `batch_execute` |
| Two-phase sign / broadcast for arbitrary txs | `client.transactions` | `sign`, `execute`, `info`, `history`, `wait_for` |
| EVM / TRON contract calls (incl. ERC-20 / TRC-20) | `client.transactions` | `sign_evm_call`, `sign_tron_call`, `erc20_transfer` |
| Solana programs | `client.transactions` | `sign_anchor_call`, `sign_solana_call` |
| TON contract calls (Jetton / NFT / text) | `client.transactions` | `jetton_transfer`, `nft_transfer`, `send_ton_comment`, `sign_ton_call` |
| Accept incoming payments | `client.pay_ins` | `create`, `select_asset`, `reset_asset`, `cancel`, `info`, `history`, `wait_for` |
| Wallet management + RSA decrypt | `client.wallets` | `generate`, `list`, `info`, `freeze`, `decrypt_private_key` |
| Treasury sweeps | `client.sweeps` | `force`, `history`, `wallet_history` |
| Withdrawals (read-only) | `client.withdrawals` | `info`, `history` |
| Static-deposit history | `client.static_deposits` | `info`, `history` |
| On-chain queries | `client.blockchain` | `contracts_available`, `wallet_balance`, `transaction_status` |
| Fiat <-> crypto rate quote | `client.currencies` | `fiat_to_crypto`, `crypto_to_fiat` |

## Accept a crypto payment (pay-in)

Create an invoice, send the customer to the hosted `payment_link`, then settle it
when the `invoice.*` webhook arrives (recommended) or by polling `wait_for`.

```python
from cryptochief import CryptoChiefClient, CreatePayInRequest, PayInMode

async def accept():
    async with CryptoChiefClient(merchant_id="M", api_key="K") as client:
        invoice = await client.pay_ins.create(CreatePayInRequest(
            order_id="invoice-1001",   # your id - idempotency key, safe to retry
            user_id="user-7",
            mode=PayInMode.FIAT,       # fix a fiat price; the customer pays the crypto equivalent
            amount_fiat="49.99",
            currency="USD",
            url_callback="https://example.com/webhooks/crypto-chief",
            url_success="https://example.com/thanks",
        ))
        print("send the customer to:", invoice.payment_link)

        final = await client.pay_ins.wait_for(invoice.uuid, timeout=1800)
        print(final.status)  # paid | expired | cancel
```

For a fixed-crypto invoice use `mode=PayInMode.CRYPTO` with `amount_crypto` and
`asset=Asset(coin="USDT", network=Chain.TRON_MAINNET)`. For host-to-host flows
where the customer picks the coin in your own UI, create the order without a fixed
asset and commit the choice with `client.pay_ins.select_asset(...)`.

## Send a payout (with confirmation)

```python
from cryptochief import (
    CryptoChiefClient, Chain, APIError, ErrorCode, ExecutePayoutRequest,
)

async def pay():
    async with CryptoChiefClient(merchant_id="M", api_key="K") as client:
        try:
            payout = await client.payouts.execute(ExecutePayoutRequest(
                order_id="order-42",  # idempotency key - safe to retry
                user_id="user-7",
                network=Chain.ETH_SEPOLIA,
                coin="ETH",
                amount="0.0001",
                to_address="0xRecipient...",
                url_callback="https://example.com/webhooks/crypto-chief",
            ))
            final = await client.payouts.wait_for(payout.uuid, timeout=300)
            print(final.status, final.txid)
        except APIError as e:
            if e.code == ErrorCode.INSUFFICIENT_FUNDS:
                ...  # top up and retry
            raise
```

## Amounts: always integers, never floats

```python
from cryptochief import human_to_base, base_to_human

human_to_base("1.5", 18)            # 1500000000000000000
base_to_human(10_000, 8)            # "0.0001"
```

`int` is arbitrary-precision in Python, so token values never overflow and
decimal strings round-trip exactly. Discover an asset's decimals with
`client.blockchain.contracts_available()`.

## Contract calls without hand-encoding

```python
from cryptochief import EvmCallRequest, Erc20TransferRequest, Chain, human_to_base

# Any EVM/TRON method by Solidity signature - args are ABI-encoded for you.
await client.transactions.sign_evm_call(EvmCallRequest(
    network=Chain.ETH_MAINNET,
    from_address="0xYourWallet...",
    contract="0xA0b8...",  # Uniswap router, etc.
    method="swapExactTokensForTokens(uint256,uint256,address[],address,uint256)",
    args=[10**6, 0, ["0xTokenIn...", "0xTokenOut..."], "0xYourWallet...", 1750000000],
))

# ERC-20 / TRC-20 transfer in one line (TRON base58 addresses accepted):
await client.transactions.erc20_transfer(Erc20TransferRequest(
    network=Chain.TRON_MAINNET,
    from_address="TYour...",
    token_contract="TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",  # USDT
    recipient="TRecipient...",
    amount=human_to_base("12.5", 6),
))
```

TON Jetton transfers resolve the sender's Jetton wallet automatically and pick a
sensible gas budget:

```python
from cryptochief import JettonTransferRequest, Chain, human_to_base

await client.transactions.jetton_transfer(JettonTransferRequest(
    network=Chain.TON_MAINNET,
    from_address="UQYour...",
    jetton_master="EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs",  # USDT
    recipient="UQRecipient...",
    amount=human_to_base("5", 6),
    memo="Order #4242",
))
```

Solana Anchor calls take explicitly-typed Borsh args:

```python
from cryptochief import AnchorCallRequest, SolanaAccount, borsh_u64, borsh_string, Chain

await client.transactions.sign_anchor_call(AnchorCallRequest(
    network=Chain.SOLANA_MAINNET,
    from_address="YourPubkey...",
    program="YourProgramId...",
    method="initialize",
    args=[borsh_u64(1_000), borsh_string("hello")],
    accounts=[SolanaAccount(pubkey="...", is_signer=True, is_writable=True)],
))
```

## Webhooks

`verify_webhook_signature` and `parse_webhook_event` are framework-agnostic - feed
them the raw request bytes and the `Signature` header. With FastAPI:

```python
from fastapi import FastAPI, Request, HTTPException
from cryptochief import (
    parse_webhook_event,
    WebhookSignatureError,
    PayInWebhookEvent,
    PayoutWebhookEvent,
)

app = FastAPI()
API_KEY = "..."

@app.post("/webhooks/crypto-chief")
async def hook(request: Request):
    raw = await request.body()  # the EXACT bytes - do not re-encode
    try:
        event = parse_webhook_event(API_KEY, raw, request.headers.get("Signature"))
    except WebhookSignatureError:
        raise HTTPException(status_code=401, detail="bad signature")

    if isinstance(event, PayInWebhookEvent):
        if event.status == "paid":
            ...  # invoice.paid -> fulfill the order for event.order_id
    elif isinstance(event, PayoutWebhookEvent):
        ...  # payout.paid / payout.system_fail -> reconcile your ledger
    return {"ok": True}
```

`parse_webhook_event` returns a typed event (`PayoutWebhookEvent`,
`TransactionWebhookEvent`, `PayInWebhookEvent`, `StaticDepositWebhookEvent`) chosen
by the event-name prefix, or the raw dict for an unrecognized prefix. Whitelist
the sender IPs in `WEBHOOK_SENDER_IPS` at your edge for defense in depth.

## Errors

Everything the SDK raises derives from `CryptoChiefError`. API failures are
`APIError` with a stable `.code` (and `.http_status`); branch on `ErrorCode`
rather than parsing messages. 5xx and network errors are retried automatically;
4xx is raised immediately.

```python
from cryptochief import APIError, ErrorCode

try:
    await client.payouts.execute(req)
except APIError as e:
    if e.code == ErrorCode.DEBT_LIMIT_EXCEEDED:
        ...
```

## Wallet private-key decryption

Generated wallets return `private_key_encrypted` (RSA-OAEP / SHA-256, base64).
Configure your project's RSA private key to decrypt locally - it never touches
the network:

```python
client = CryptoChiefClient(
    merchant_id="M", api_key="K",
    rsa_private_key=open("project_private_key.pem").read(),
)
wallet = await client.wallets.generate(...)
priv = client.wallets.decrypt_private_key(wallet.private_key_encrypted)
```

## FAQ - common crypto-processing tasks in Python

- **How do I accept crypto payments in Python?** Create a pay-in with
  `client.pay_ins.create(...)`, redirect the customer to `pay_in.payment_link`,
  and confirm via webhook or `client.pay_ins.wait_for(uuid)`.
- **How do I send a USDT payout?** `client.payouts.execute(...)` with the
  stablecoin's `coin` / `network`; poll `wait_for`.
- **How do I send many payouts at once?** `client.payouts.batch_execute(...)` -
  up to 50 items, funds locked sequentially.
- **How do I do a crypto swap?** A swap is a payout with `auto_convert=True`.
- **How do I call a smart contract?** `client.transactions.sign_evm_call` /
  `sign_anchor_call` / `jetton_transfer`, then `transactions.execute`.

## Documentation

- SDK guide: https://docs-sdk.crypto-chief.com/processing/python
- REST API reference: https://docs-processing.crypto-chief.com
- Product: https://crypto-chief.com/processing/

## License

MIT
