# Phase 2 review and verification

Reviewed on 2026-10-09 in the official project directory, C:\Users\yazan\Development\binance-demo-bot.

## Scope and result

Implemented offline historical simulation only. Reviewed against the existing quant-backtesting, futures-risk-manager and trading-code-review skills. No credentials, Binance calls, order validation, trading execution, ML or Phase 3 work was used. All five existing custom skills remain in place.

The complete suite discovered **80 tests: 79 passed, 0 failed, 0 errors, 1 skipped**. There are 52 new Phase 2 tests; all 27 existing offline tests also pass. The original optional public Demo HTTPS smoke test is skipped because this phase must run offline. This is not a new account/connectivity verification.

Reproduce with the bundled Python interpreter:

```powershell
cd "C:\Users\yazan\Development\binance-demo-bot"
$pythonExe = 'C:\Users\yazan\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $pythonExe scripts/verify_phase2.py
```

This runner blocks Python socket connections/DNS and opening the real project .env, disables the optional network test, runs the full suite, writes reports/phase2-tests.json, and regenerates the default and doubled-cost reports. It verifies the historical SQLite file's SHA-256 is unchanged. This guard is additional verification, not an OS security sandbox.

## Review findings corrected

- Daily risk state is rechecked between same-open fills: entry fees/friction from the first symbol can block a second symbol. A two-position regression verifies this.
- Unknown intrabar funding/exit ordering must not fabricate a funding receipt. Intrabar-exit bars conservatively pay funding debits but omit uncertain credits, with a skipped-credit count in the trade journal. Positions held through a known close and opening-time funding retain signed settlement. Regression tests cover both sides.
- Original Phase 1 CLI accepts arguments through sys.argv. Offline routing now preserves that interface; the backtest path does not import the authenticated CLI. Both help routes are covered without credential loading.
- Financial comparisons permit at most 1e-12 USDT Decimal operation-order roundoff. Reports expose accounting_residual_usdt; material mismatches raise an error.

No remaining blocking implementation defect was identified within the tested offline scope. This is not certification of exchange execution, complete historical realism, or profitability.

## Verified behavior

Hand-calculated fixtures cover EMA20/50/200, RSI, MACD, ATR, relative volume, long/short PnL, fees, signed funding, adverse tick rounding, and slippage counted once. Other checks cover warm-up, next-bar entries, unfilled final-bar signals, stop gaps, ambiguous stop/target priority, holding limits, minimum-notional refusal, shared margin/position limits, fixed risk sizing, daily halt/reset, no pyramiding, reproducibility, drawdown and undefined metrics.

Unmocked baseline integration tests generate long and short trades on clearly labeled synthetic fixtures. Changing future candles cannot change earlier features, decisions, fills or equity. Synthetic results are tests, not market performance.

## Saved historical sample

Input: existing data/market.sqlite3, read-only; BTCUSDT and ETHUSDT, 5m, 288 bars each, UTC 2026-10-08. Three recorded funding events per symbol are available. No new data was downloaded.

| Measurement | Strategy | NO TRADE |
|---|---:|---:|
| Initial simulated equity (USDT) | 10,000 | 10,000 |
| Closed trades | 0 | 0 |
| Net PnL after costs (USDT) | 0 | 0 |
| Fees / slippage / funding paid (USDT) | 0 / 0 / 0 | 0 / 0 / 0 |
| Maximum drawdown | 0% | 0% |
| Win rate / profit factor | Undefined | Undefined |
| Final simulated equity (USDT) | 10,000 | 10,000 |

Each symbol has 199 warm-up candles and 89 candles with complete indicators. BTCUSDT then rejects 61 for volume and 28 for unaligned trend/momentum; ETHUSDT rejects 54 for volume and 35 for trend/momentum. No thresholds were tuned to this dataset.

The doubled-fee/slippage run also has zero trades and zero PnL. With no trades this does not establish cost robustness.

**Profitability is not demonstrated.** This run ties NO TRADE and is far too short for a statistical conclusion. Reports: ../reports/phase2-sample/report.md and ../reports/phase2-cost-stress/report.md. Trade CSVs contain headers only because no trades occurred; decision/equity CSVs contain the complete sample journals.

## Assumptions and limits

Fees (0.05% per side), adverse slippage (0.02% per fill), offline contract filters and 0.1% notional funding reserve are research assumptions, not verified historical Binance conditions. The reserve limits size and is not charged again as a cost. Recorded funding events settle costs; history completeness is not independently verified.

Default sizing limits new entries to a 0.5% planned risk budget and 2x shared portfolio leverage; there is one shared position by default, with deterministic BTC priority. Price movements can change effective leverage afterward. Gaps and unexpected funding can exceed planned risk. The 2% daily rule blocks further entries and flattens exposure conservatively; it does not guarantee losses stop at exactly 2%.

OHLC cannot identify intrabar event order. Stops precede targets when both touch; daily risk/drawdown use conservative adverse-bar liquidation values. Funding debits are included on uncertain exit bars while uncertain credits are omitted. This may overstate costs. Actual maintenance-margin tiers, liquidation/ADL, order-book liquidity and exchange latency are not modeled. Isolated-style margin accounting is not an exchange margin-mode setting.

No restartable execution state, kill switch for exchange positions, ML model or deployment was added. Those belong to later phases.

## Next decision

Stop after Phase 2. Await the user's approval before any further phase. A useful later research step is a larger historical sample with frozen rules and chronological evaluation; collecting it would require separate authorization for Demo public API access.
