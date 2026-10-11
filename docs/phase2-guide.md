# Run Phase 2 safely

Phase 2 uses saved historical candles only. It does not need your .env, does not load credentials and does not contact Binance.

## Run a historical backtest

```powershell
cd "C:\Users\yazan\Development\binance-demo-bot"
$pythonExe = 'C:\Users\yazan\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $pythonExe run.py backtest --db data/market.sqlite3 --output reports/my-backtest
```

Or use your own Python 3.11+ interpreter. No third-party runtime packages are required.

Default markets: BTCUSDT and ETHUSDT together, on 5m candles with a shared 10,000 USDT simulated account. This is independent of your actual Demo balance.

```powershell
# One market, using its existing local history:
& $pythonExe run.py backtest --symbols ETHUSDT --interval 5m --output reports/eth
# Explicit cost stress; the strategy stays fixed:
& $pythonExe run.py backtest --fee-rate 0.001 --slippage-rate 0.0004 --output reports/cost-stress
# Offline verification of all tests and both sample reports:
& $pythonExe scripts/verify_phase2.py
```

Supported intervals are 5m, 15m, 1h and 4h, selected one at a time. The engine refuses gaps and different timestamp grids between symbols. It never downloads missing data. Funding records are required by default. --allow-missing-funding explicitly assumes zero funding for a symbol whose history is absent; the report warns about this assumption.

The saved one-day sample does not contain enough 15m, 1h or 4h bars for EMA200. Even 5m has only 89 fully warmed indicator rows. Do not interpret inactivity on short histories as strong risk-adjusted performance.

## Understand the baseline

LONG requires close > EMA20 > EMA50 > EMA200, RSI14 between 50 and 70, positive MACD line/histogram, and volume at least its preceding 20-bar average. SHORT mirrors the trend and MACD conditions with RSI between 30 and 50. Otherwise the decision is NO TRADE.

Decisions use completed candles. Entries occur at the next candle open with adverse slippage and tick rounding. ATR14 at the signal determines a 2x ATR stop and 3x ATR target from that next open. A position closes on stop, target, the 48-bar holding cap, daily risk halt or the end of data. Signals cannot add to an existing position.

The default maximum risk budget is 0.5% of current marked equity, including estimated stop loss, round-trip costs and a funding buffer. Shared entry leverage is capped at 2x. There is one shared position; simultaneous candidates use BTC priority. A 2% daily loss from the first UTC bar's starting equity halts new entries for that day and closes exposure conservatively. Stops and daily limits cannot guarantee a maximum loss through a gap.

## Read the files

- report.md: summary, strategy versus NO TRADE, and important assumptions.
- report.json: exact configuration, data/config hashes and full metrics.
- trades.csv: entry/exit times, quantity, raw and execution prices, risk budget, PnL, fees, slippage, signed funding and reasons. Uncertain omitted funding credits are counted.
- decisions.csv: every signal, NO TRADE and risk rejection with reasons.
- equity.csv: open/close marks, conservative intrabar liquidation values and final equity.

Net PnL = raw price PnL - slippage/rounding - fees - signed funding cost. Slippage is already included in execution prices, so it is not charged twice. Negative funding cost means a receipt. Undefined win rate/profit factor stay undefined when there are no trades.

The fee and slippage rates are assumptions; no current Binance schedule was fetched. Contract ticks/lots/minimums are explicit offline assumptions, not historically verified filters. Funding completeness and actual market liquidity are not guaranteed. Unknown intrabar exits conservatively omit funding receipts while charging funding debits. See phase2-spec.md and phase2-review.md for all limitations.

## Current result and boundary

The saved 2026-10-08 sample produces zero trades and zero net PnL after all modeled costs, identical to NO TRADE. **The strategy has not been demonstrated profitable.** The default and doubled-cost reports are integration samples, not a forecast.

Phase 2 does not start paper trading, Demo execution, ML or Phase 3. Keep credentials local. Review the result and explicitly approve any later work.
