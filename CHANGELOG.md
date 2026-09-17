# Changelog

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
