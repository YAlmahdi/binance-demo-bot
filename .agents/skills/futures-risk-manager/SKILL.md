---
name: futures-risk-manager
description: "Design and review Demo futures position sizing, loss limits, exposure caps, protective orders, and kill-switch behavior. Use when risk controls or execution safety change; does not authorize trading."
---

# Futures Risk Manager

## Purpose and use

Provide a deterministic risk gate independent of the strategy or model. Review the existing implementation and document missing controls before changing it. Phase 1 has no execution or risk engine; creating this skill must not enable either.

## Safety rules

- Only Binance USD-M Futures Demo is permitted. Never add a production executable endpoint, a live flag, or an automatic environment fallback.
- Never inspect `.env`, credential environment values, private-key files, or secret stores. Do not print, partially reveal, upload, copy, or request API secrets. Use dummy values in tests; only the reviewed local application consumes Demo credentials internally when later authorized.
- Keep training, tests, paper simulation and Demo execution separate. No orders, cancellations, close-outs or order-validation API calls while setting up skills.
- No live trading, Martingale, loss-recovery doubling, unattended self-learning, or ML promotion without independent out-of-sample performance/risk tests. Model confidence cannot override a risk rejection.

## Engineering instructions

1. Preserve default per-trade risk ceiling 0.5% of current Demo equity, leverage 2x, and Isolated Margin when supported. An unsupported margin mode must be reported and block execution until the explicitly approved policy is known; never silently use cross margin.
2. Calculate maximum size from stop distance plus estimated round-trip fees, slippage and funding buffer, using Decimal. Round quantity down to the lot step and recalculate total risk. Leverage affects margin availability, not the acceptable loss budget.
3. Refuse zero/invalid equity, nonfinite inputs, invalid stop sides, tiny/zero stop distance, stale prices, unavailable margin, incompatible filters, or a rounded order below minimum notional. Never round UP or increase risk to satisfy exchange minimums; choose NO TRADE.
4. Use ATR or another documented volatility measure for SL/TP. Stops are not guaranteed fill prices: include gap/slippage stress and liquidation distance checks. Do not report the sizing budget as a guaranteed maximum realized loss.
5. Block new entries at a daily loss of 2% or more. Explicitly define day boundary (default UTC), starting equity, treatment of realized/unrealized PnL, fees/funding and deposits/resets. Persist the daily anchor and stop state across restarts; continue protective exits when new entries are blocked.
6. Require a finite reviewed maximum-open-position limit before execution. Count exchange positions, pending entries and correlated BTC/ETH exposure. An unspecified limit must not become unlimited. Reserve risk atomically to prevent simultaneous signals exceeding caps.
7. Design a persistent kill switch: halt new entries first, cancel Demo entry orders, reconcile, close Demo positions with compatible reduce-only/position-side semantics, and verify the final state. If offline, remain halted and report unresolved exposure; never claim closure without exchange confirmation. Never cancel a protective exit before accounting for the exposed position.
8. No increase in size solely because previous trades lost. Log every approval/rejection with nonsecret inputs and reasons, including manual overrides and reset events. Never auto-resume after an unresolved risk failure.

## Required tests

Test exact 0.5% budget and 2% daily threshold; fees/slippage buffer; rounding down; minimum-notional rejection; stale prices; zero equity; ATR extremes; margin and liquidation bounds; concurrent reservations; position/pending-order caps; restart persistence; and kill-switch failure mid-sequence. Test reduce-only behavior and one-way/hedge-mode differences in mocks before any authorized Demo trial.

## Acceptance criteria

All risk decisions are deterministic, reasoned and tested; limit breaches prevent entries; restarts preserve halts; kill-switch status reflects confirmed exchange state. Evidence must distinguish simulated safety from a Demo account trial. Risk controls remain active for every baseline/ML policy.

## Common mistakes

Sizing from leverage; ignoring exit fees; rounding up to meet minimums; resetting daily losses on restart; counting only filled positions; interpreting a stop as a guarantee; enlarging exposure after losses; failing to halt while the exchange is unreachable; letting a high model score bypass limits.
