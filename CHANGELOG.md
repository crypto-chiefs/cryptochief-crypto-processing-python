# Changelog

## [0.12.0] — 2026-09-19

- **Breaking for direct callers of `hmac_v1_sign`:** it now returns the full `X-CC-Signature` header value (`v1=` + lowercase hex), matching `sign_webhook_v1`. Requests sent through the client are unchanged — the header on the wire is byte-for-byte the same

## [0.11.0] — 2026-09-19

- `client.transactions.estimate(EstimateTransactionRequest)` — POST `/v1/transaction/estimate`: prices a transfer's network fee without signing or broadcasting anything; `native` and `token` transfers only, `type="contract"` is refused with `CONTRACT_ESTIMATE_UNSUPPORTED`; `EstimateTransactionResponse` carries `estimated_fee` / `estimated_fee_fiat` and `required` / `required_fiat` (the native coin the from-wallet must hold: fee + value for a native transfer, fee only for a token one; the fiat fields are `""` when no USD rate is available), and on TRON additionally a fee breakdown: `fee_expected` (the fee with the wallet's current energy pool applied — not a guarantee, the pool can be spent first), `fee_limit` (the on-chain cap written into the transaction), `energy`, `energy_fee`, `bandwidth_fee` and `activation_fee` (native transfer to a fresh address); an estimation infrastructure failure answers 502 `ESTIMATE_UNAVAILABLE`
- `client.energy` — TRON energy rental billed in API credits: `quote(EnergyQuoteRequest)` (free of charge; the answer prices the rental against what burning TRX would cost), `rent(EnergyRentRequest, idempotency_key=...)` (synchronous — the answer is always the order; the idempotency key is required and enforced client-side), `order(key)` to reconcile; `EnergyOrder`, `EnergyOrderStatus` (`delivered` / `refused` / `unresolved` / `refunded`), `is_energy_order_terminal`
- `client.native` — buy a network's native coin for API credits, sent to any address: `quote(NativeQuoteRequest)` (free of charge; `total_usd` is the full price, the platform's own transfer fee included), `buy(NativeBuyRequest, idempotency_key=...)` (synchronous — the answer is always the order; the idempotency key is required and enforced client-side), `order(key)` to reconcile; `NativeOrder`, `NativeOrderStatus`, `is_native_order_terminal`
- a `refused` (HTTP 502, or 402 when the credits balance ran out) or `unresolved` (HTTP 409, `needs_attention=true`) energy / native order is returned as the order itself instead of raising — the API answers with the order as the body, and the machine-readable `error_code` / human `error` on it say why, with nothing charged; an `unresolved` order is not to be retried — reconcile with `order(key)` until it settles; only failures with no order to report (a spent `quote_ref`, gateway errors) raise `APIError`
- `APIError.code` is read from `error_code` when the body is not an error envelope (an order reported on a non-2xx answer, where `error` holds a sanitised human sentence and the machine code travels in `error_code`); the envelope shape is now recognised by its markers — `ok: false` or a `msg` key — rather than by the presence of an `error` key
- `ErrorCode.CONTRACT_ESTIMATE_UNSUPPORTED`
- `.gitattributes` pins `* text=auto eol=lf` so text files check out with LF everywhere, Windows included — the signature test vectors are pinned by sha256 and a CRLF checkout changes their bytes; `*.bat` keeps CRLF

## [0.10.0] — 2026-09-17

- **Breaking:** requests are signed with HMAC-SHA256 v1 only: headers `X-CC-Timestamp`, `X-CC-Nonce`, `X-CC-Signature`; the `Signature` header is not sent; one repeat with clock correction on `SIGNATURE_TIMESTAMP_OUT_OF_RANGE`
- **Breaking:** removed `sign`, `sign_value`, `canonical_json`
- `hmac_v1_sign`, `hmac_v1_string_to_sign`; `client.request(path, body, idempotency_key=...)` sends `Idempotency-Key` and signs it, and rejects a value that is not printable ASCII without surrounding spaces or tabs
- `client.request` signs the percent-decoded path, as the server reads it, and the raw query
- `idempotency_key("k")` sets `Idempotency-Key` for every call made inside the block, service calls included; a key passed to `client.request` wins
- `client.request(path, body, method=...)` signs and sends any HTTP method; `Content-Type` goes out only with a body
- an `api_key` that is empty or only spaces and tabs is rejected by the client, `hmac_v1_sign`, `sign_webhook_v1` and `verify_webhook`
- The request body is compact UTF-8 JSON in the key order of the request value; `None` members of dicts are omitted at any depth; integers are sent exactly; a float with an integral value is sent as an integer
- **Breaking:** webhooks are verified with HMAC-SHA256 v1 over the raw body and the `X-CC-Timestamp`, `X-Webhook-Delivery`, `X-CC-Signature` headers: `verify_webhook(api_key, raw_body, headers, *, tolerance=300, now=None)` raises `WebhookHeadersError`, `WebhookTimestampError` or `WebhookSignatureError` (base `WebhookVerificationError`, `.reason` `"headers"`, `"timestamp"` or `"signature"`); removed `verify_webhook_signature` and `WEBHOOK_HEADER`
- **Breaking:** `parse_webhook_event(api_key, raw_body, headers, *, tolerance, now)` takes the request headers instead of the signature value
- **Breaking:** `WebhookSignatureError` is raised only on a signature mismatch; catch `WebhookVerificationError` for every refusal
- `sign_webhook_v1`, `webhook_v1_string_to_sign`, `WEBHOOK_TIMESTAMP_HEADER`, `WEBHOOK_SIGNATURE_HEADER`, `DEFAULT_WEBHOOK_TOLERANCE`, `WebhookHeaders`
- `ErrorCode.BAD_AUTH_HEADERS`, `INVALID_SIGNATURE`, `SIGNATURE_TIMESTAMP_OUT_OF_RANGE`, `SIGNATURE_REPLAYED`, `PAYLOAD_TOO_LARGE`; `APIError.server_time`
- `APIError.code` is read from `error.details.code` (else `error.name`) of `{"data":null,"error":{...}}` error bodies
