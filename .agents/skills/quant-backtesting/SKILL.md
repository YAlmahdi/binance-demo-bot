---
name: quant-backtesting
description: "Design and review deterministic, cost-aware futures strategies and historical backtests for Futures AI Lab. Use for baseline signals, fill simulation, metrics, and comparisons, not exchange execution."
---

# Quant Backtesting

## Purpose and use

Build reproducible historical evidence for LONG, SHORT, and NO TRADE decisions. Review the current data and strategy code before changing behavior. Phase 1 currently has no strategy or backtesting engine; this skill guides a later explicitly requested phase rather than implementing it automatically.

## Safety rules

- Binance USD-M Futures Demo is the only exchange environment. No production execution endpoints, live mode, or fallback to real trading.
- Never read `.env`, credential environment values, private keys, or secret stores. Never print, upload, partially reveal, or ask for API secrets. Backtests run offline with no credentials.
- Separate training, validation, historical simulation, paper trading, and Demo execution. Skill setup never places orders or runs order validation requests.
- No live trading or unsupervised self-modifying models. Reject ML promotion without untouched out-of-sample performance and risk tests. Never promise profits.

## Engineering instructions

1. Write a strategy specification before implementation: indicator definitions and warm-up, entry/exit timing, LONG/SHORT/NO TRADE conditions, sizing, stop/take-profit, and rejection reasons. Use EMA20/50/200, RSI, MACD, ATR, and volume only when the hypothesis justifies them.
2. Consume validated closed candles. At decision time t, use only features observable by t; join higher timeframes by their closing/availability timestamps. No centered rolling windows, backward filling, or full-series normalization.
3. A signal calculated at candle close must fill no earlier than the next executable event. If an OHLC bar touches stop and target with unknown order, use a documented conservative assumption or finer data; do not pick the profitable ordering.
4. Model entry and exit fees, side-dependent slippage, funding at actual holding/payment times, contract precision, unavailable margin, and rejected/unfilled orders. Apply the same risk limits to every compared policy.
5. Record immutable inputs/data hash, strategy/config version, UTC range, seed when relevant, each decision and reason, and a fill/cost/equity ledger. Keep market snapshots with availability timestamps; current OI cannot be backfilled into old candles.
6. Compare against no-trade and the indicator baseline on the same dates/capital/costs. Report net returns, turnover, trade count, win rate, profit factor, maximum drawdown and exposure. Distinguish cash/inactive baseline from costs caused by positions.
7. Tune on training windows only; use chronological walk-forward evaluation and an untouched final period. Report sample size and sensitivity to costs and parameters. A day of Demo data is an integration sample, not evidence of profitability.

## Required tests

Use hand-calculated long/short PnL fixtures; entry/exit fees and signed funding; next-event execution; warm-up; simultaneous stop/target; zero trades (undefined metrics represented explicitly); drawdown recovery; missing candles; and multiple-timeframe alignment. Add a future-perturbation test: changing later candles must not change earlier decisions.

## Acceptance criteria

A deterministic offline run is reproducible from saved inputs; every fill has a prior decision; the cost/equity ledger reconciles; baseline/no-trade comparisons use identical assumptions; relevant tests pass. Report weak or negative results and insufficient samples honestly. Backtest approval never enables execution.

## Common mistakes

Filling at the close that produced the signal; leaking a still-open 4h candle into 5m decisions; dropping losing or unfilled trades; assuming stops guarantee fills; ignoring liquidation/margin constraints; optimizing on the reported test period; confusing leverage with permitted loss; treating more indicators as evidence of an edge.
