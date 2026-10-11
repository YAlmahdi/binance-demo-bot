# Larger historical evaluation of the frozen baseline

Research completed on 2026-10-09 in C:\Users\yazan\Development\binance-demo-bot. This continues Phase 2 only. Reviewed with quant-backtesting, futures-risk-manager and trading-code-review.

## Outcome

The current strategy generates trades on longer Demo history, but **is not profitable on this dataset after the assumed costs**. The default simulation loses 7,516.50 USDT out of 10,000; doubled costs lose 8,222.31 USDT. NO TRADE ends at 10,000.

| Metric | Default | Doubled costs |
|---|---:|---:|
| Trades | 851 | 723 |
| LONG / SHORT | 458 / 393 | 389 / 334 |
| PnL after fees/slippage, before funding | -7,521.61 USDT | -8,223.55 USDT |
| Net PnL including recorded funding | -7,516.50 USDT | -8,222.31 USDT |
| Win rate | 34.20% | 21.72% |
| Profit factor | 0.297 | 0.093 |
| Maximum drawdown | 75.39% | 82.24% |
| Average duration | 66.10 minutes | 63.21 minutes |
| Final equity | 2,483.50 USDT | 1,777.69 USDT |

Default raw price PnL is already negative (-693.32 USDT). Fees of 4,866.15 and slippage/rounding of 1,962.14 deepen the loss; recorded net funding is a small receipt of 5.12 USDT. This is descriptive simulation evidence conditional on the provided data and cost assumptions, not a prediction of actual Binance execution.

## Data audit and availability

The original data/market.sqlite3 remains unchanged. Both symbols contain exactly UTC 2026-10-08 00:00:00 through 23:59:59.999: 288 five-minute candles, 96 fifteen-minute, 24 hourly and 6 four-hour candles each. Integrity and OHLCV/timestamp validation pass; no internal missing intervals exist. Each symbol has funding at 00:00, 08:00 and 16:00.

Only these public GET routes were used for this research:

- https://demo-fapi.binance.com/fapi/v1/time
- https://demo-fapi.binance.com/fapi/v1/klines
- https://demo-fapi.binance.com/fapi/v1/fundingRate

The [official General Info](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/general-info) documents the Demo origin. The [official market-data reference](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data) defines candle and funding-history queries. Its production examples were not used. No guaranteed Demo retention period was assumed.

Dated probes at 90/60/30/7/1 days back succeeded for both symbols. The complete collected snapshot covers **2026-07-11 06:50:00 UTC through 2026-10-09 06:49:59.999 UTC**, with an exclusive end of 06:50:00. It contains **25,920 completed 5m candles per symbol**, identical contiguous grids, zero missing candle intervals, and 268 available funding records per symbol.

The snapshot is data/research-90d.sqlite3. It is a separate market dataset, not a moved or duplicated project. All 576 overlapping original 5m rows match it exactly. No 15m/1h/4h history was collected into this new 5m-only snapshot; original intervals are preserved.

The first collection attempt stopped without adequate original error detail. Both adjacent pages subsequently passed independent rechecks. Public GET recovery is now bounded to three attempts for temporary network/500/502/503/504 failures only; 429/418, redirects and invalid data stop immediately. Validated pages are checkpointed under data/history-checkpoints. The final successful collection log contains 67 responses and no recorded transient failures. No missing bars were fabricated.

## Method

Hashes in collection.json prove strategy.py, indicators.py, risk.py, backtest.py and the original reporting.py remained unchanged. The original indicator definitions, entry thresholds, ATR exits, position cap and risk limits were preserved. No parameters were searched or optimized.

Two continuous chronological backtests start with separate simulated 10,000 USDT accounts: the default cost scenario and doubled fee/slippage scenario. No actual Demo balance is loaded. Risk remains 0.5% planned per entry, leverage capped at 2x on new entries, one shared position across symbols and a 2% UTC daily loss halt. BTC priority for competing entries is unchanged.

Each run warms up its first 199 candles, makes decisions on closed data and enters at the following open. Default fees are 0.05% per side, adverse slippage 0.02% per fill; stress uses 0.10% and 0.04%. Higher costs change sizing and can change daily halts/trade counts through the existing risk gate. Funding and other parameters stay the same.

Monthly reporting slices these continuous runs. Positions, capital, indicator state and daily halts are carried forward. Closed trades and their full costs are attributed to exit month; marked-equity changes are reported separately. July and October are partial months. All four subperiods lose money under both scenarios. Default net PnL by exit month:

| Month | Trades | Net PnL (USDT) |
|---|---:|---:|
| July 11-31 | 196 | -2,698.18 |
| August | 276 | -2,899.60 |
| September | 295 | -1,586.91 |
| October 1-9 | 84 | -331.82 |

Full monthly LONG/SHORT counts, win rate, profit factor, duration and drawdown for both scenarios appear in the report/CSV/JSON.

## Rejections

Default risk rejections: 1,125 portfolio-cap conflicts, 1,609 attempts while a position was already open, and 814 daily-halt rejections. Stress: 915, 1,300 and 1,461 respectively.

Both scenarios share the same baseline filters: 398 warm-up/unavailable-volume decisions, 15,992 trend/momentum failures and 31,051 below-average-volume decisions. These are the first logged rejection reasons, not independent counts of every failed condition. No final-bar signal was left unfilled in this dataset.

## Funding and other limitations

The observed modal funding spacing is eight hours. Thirty-one records per symbol occur one millisecond after the nominal grid; diagnostics match that jitter while settlement retains the original event timestamps. Under the modal schedule there are two absent timestamps per symbol: 2026-08-17 08:00 UTC and 2026-09-01 08:00 UTC.

Narrow official Demo funding queries confirmed no 08:00 record on those dates. The historical schedule is not independently verified, so these are potential gaps, not proof of a missing financial obligation. One trade in each scenario overlaps the August 17 timestamp. Rates/signs are unknown; no rates or zero-cost guarantees were invented. Exact overall net PnL therefore remains conditional on the available funding records.

There are three zero-volume/zero-range bars per symbol. BTC has four bars with >5% high/low range, ETH eight; the largest ranges are 13.47% and 12.08%. They pass structural validation and were not deleted to improve results. Demo data may differ from economically representative real-market conditions.

Stops win ambiguous stop/target bars; gap stops use adverse opens; gap targets receive no favorable improvement. Intrabar exits are assigned to close, uncertain funding credits are omitted while debits are charged, and drawdown/daily halts use conservative adverse-bar liquidation values. Average duration is approximate because intrabar timing is unknown.

Contract filters, fees and slippage are research assumptions, not verified historical exchange terms. SQLite/indicator values use floating-point storage/arithmetic; financial accounting uses Decimal with a 1e-12 USDT tolerance. Real order-book depth, latency, maintenance tiers, liquidation/ADL and outages are not modeled. Planned risk limits are not guaranteed realized-loss ceilings.

This is one descriptive historical evaluation with no optimization or independent holdout certification. It does not establish general profitability, nor does the report enable execution.

## Tests and review

**105 discovered: 104 passed, 0 failed, 0 errors, 1 skipped.** The optional network smoke test is intentionally skipped while the suite runs under the offline guard. The requested public collection was verified separately using real public Demo responses.

Independent checks reconcile all 851/723 trade journals: prior signal timestamps, positive quantities, planned risk/entry leverage, fees, signed funding, nonoverlapping shared positions, account equity and monthly PnL. Source/database hashes are unchanged. See journal-checks.json and tests.json.

Twenty-five new tests cover public-only URLs, unsigned GETs, redirects, bans, pagination, incomplete/open candles, funding validation, checkpoints/retries, audits, 1ms funding diagnostics, durations, monthly carry, rejection classification, potential funding exposure and the credential/network guard. All existing offline tests still pass.

Review found no unresolved blocking defect in the tested research workflow. Data realism and exact funding completeness remain limitations. The severe negative performance does not support promoting the baseline to execution.

## Reproduce offline

```powershell
cd "C:\Users\yazan\Development\binance-demo-bot"
$pythonExe = 'C:\Users\yazan\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $pythonExe scripts/research_history.py
```

Without --collect, the runner blocks network, verifies frozen source/data hashes and regenerates the reports from the saved snapshot. Do not run --collect to reproduce this existing report: a populated snapshot is deliberately protected from overwrite. --days and --end-utc apply to explicit collection, not offline slicing.

No packages beyond Python 3.11+ standard library are required. Credentials are unnecessary and the research runner rejects authenticated configuration/client imports and real .env reads. The guard supplements ordinary reviewed code; it is not an OS security sandbox.

## Changed files and artifacts

Added:

- src/demo_futures/public_history.py
- src/demo_futures/history_audit.py
- src/demo_futures/research_evaluation.py
- scripts/research_history.py
- tests/test_public_history.py
- tests/test_research_evaluation.py
- docs/historical-research.md

Updated README.md and AGENTS.md to explain this explicitly authorized public-data research. All five skills remain intact. No strategy, indicator, risk, backtest or original report-generation rules were modified.

Added market data/checkpoints under data/ (already ignored by Git), and reports/historical-90d/ containing original/research audits, collection manifests, raw funding, full default/stress journals, monthly CSVs, evaluation.json, tests, funding-gap confirmation, overlap comparison and independent journal checks.

**Stop here. No ML, strategy optimization, orders or Phase 3. Await explicit user approval.**
