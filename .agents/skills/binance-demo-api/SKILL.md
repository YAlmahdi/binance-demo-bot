---
name: binance-demo-api
description: "Develop or diagnose this project's Binance USD-M Futures Demo REST, WebSocket, signing, exchange filters, and market-data ingestion. Use for Demo API work, not strategy research or production trading."
---

# Binance Demo Api

## Purpose and scope

Maintain a fail-closed Demo-only API boundary. Start by reading `src/demo_futures/config.py`, `client.py`, and the relevant tests from the project root. Phase 1 allows public reads, signed account reads, and non-executing order validation only. A skill invocation never authorizes order placement.

## Safety rules

- Permit Binance USD-M Futures Demo only: REST `https://demo-fapi.binance.com`; future market streams `wss://demo-fstream.binance.com`, after checking current official documentation. Never add production execution or a live-mode switch.
- Never open or inspect `.env`, secret stores, credential environment values, private-key files, or account screenshots. Never print, partially mask, copy, upload, or request API secrets. Only the existing local application may consume credentials internally for an explicitly requested check; use dummy credentials for development.
- Do not run network requests, account checks, `/order/test`, trades, or cancellations during skill setup. During later API tasks, use offline tests by default; a request to diagnose the connection permits the relevant non-executing check, not trading.
- Keep training, evaluation, paper simulation, and Demo execution separate. No live trading, unattended self-learning, or promotion of an ML model without untouched out-of-sample performance and risk checks.

## Engineering workflow

1. Verify endpoints against [official General Info](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/general-info) and the [REST reference](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data). Record source/date; do not copy Spot or legacy testnet URLs.
2. Review existing behavior before editing. Preserve exact-origin validation on every request, TLS certificate verification, disabled redirects/proxies, and the method/path allowlist. Ping/time/exchangeInfo do not provide a cryptographic `isDemo` account flag; the fixed TLS origin is the boundary.
3. Preserve HMAC signing over exactly the encoded parameters, time synchronization, bounded recvWindow, sanitized errors, and invalidation after failures. Never log signed URLs, request headers, raw credentials, or untrusted raw response bodies.
4. Keep POST single-attempt. Later execution requires durable client order IDs and reconciliation after ambiguous outcomes before any resend. For 429/418, stop or use an explicitly designed bounded cooldown; never loop blindly.
5. Fetch current exchangeInfo filters with Decimal arithmetic. Fail closed on unknown required filters. Do not confuse pricePrecision with tickSize or quantityPrecision with stepSize.
6. Ingestion must paginate, reject malformed/gapped/nonfinite OHLCV, exclude open candles, and persist observation times for funding/OI. Report unsupported optional data; never fall back to a production host. REST suffices for historical ingestion; introduce WebSocket only for a concrete streaming requirement.

## Required tests

Test production/deceptive origins and redirects blocked before network; unverified/expired signed requests blocked; deterministic HMAC; clock skew; missing credentials using dummy values; sanitized errors; one POST attempt on timeout; quantity/price/notional filters; pagination; closed-candle boundaries and SQLite idempotency. Public Demo smoke tests must be opt-in and key-free. Personal account checks are separate from offline test success.

## Acceptance criteria

Relevant offline tests pass, execution routes remain blocked in phase 1, no credential file was read by the agent, and the report clearly separates mock validation from actual Demo connectivity. State API availability limitations and any missing account verification.

## Common mistakes

Using Spot testnet credentials/endpoints for USD-M; accepting arbitrary base URLs; disabling TLS; retrying an unknown POST result; claiming balance proves Demo; treating current OI as historical; requesting secrets in chat; claiming mock tests verify the user's key.
