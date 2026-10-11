# Phase 2 specification â€” frozen before implementation

Scope: offline historical backtesting only. No credential loading, network, exchange orders, paper/Demo execution, or ML. Existing Phase 1 routes remain unchanged.

## Baseline hypothesis and timing

Use a single chosen timeframe for both BTCUSDT and ETHUSDT on identical contiguous UTC bar times. No higher-timeframe joins in this version. Indicators use only completed bars:

- EMA20/50/200: SMA seed at period-1, then alpha=2/(period+1).
- RSI14: Wilder average gains/losses from 14 price changes; flat=50.
- MACD12/26/9: seeded EMAs, signal from first nine available MACD values.
- ATR14: first true range is high-low; SMA seed, then Wilder smoothing.
- Relative volume: current volume divided by the mean of the preceding 20 bars.

LONG: close > EMA20 > EMA50 > EMA200, RSI in [50,70], positive MACD histogram and MACD line, relative volume >=1. SHORT mirrors trend/MACD with RSI in [30,50]. Otherwise NO TRADE, with reasons. First usable decision has all indicators available. No thresholds will be tuned to this sample.

A decision at bar t close can enter only at bar t+1 open. There is no pyramiding, reversal-on-signal, or same-bar re-entry. Exit by ATR stop/target, time cap (48 bars), daily risk halt, or final-data liquidation.

## Risk and portfolio assumptions

Initial simulated equity 10,000 USDT (not read from the user's account). Maximum budget 0.5% of current equity per entry; leverage <=2x. Default one open position across both symbols; BTCUSDT has deterministic priority if simultaneous signals compete. No loss-streak sizing or Martingale.

Stops use 2x signal ATR; targets 3x signal ATR, anchored to next raw open. Round stops/targets outward and execution prices adversely to assumed ticks. Size down to the lot step using stop loss INCLUDING entry/exit fees, adverse fill prices and a 0.1% notional funding reserve. Refuse insufficient margin, minimum-notional, invalid inputs and risk-limit violations. Risk budget is not a guaranteed loss cap: gaps can exceed it.

Daily loss limit: 2% of marked equity at the first bar open of each UTC day. Include realized/unrealized losses, fees, slippage and funding. Crossing the limit blocks entries for the rest of that day and flattens exposure conservatively. It resets only on a new UTC day; no deposits/resets modeled.

## Fill and accounting assumptions

Fee 0.05% per executed side, adverse slippage 0.02% per fill; explicit research assumptions, not a claim about current Binance fees. Default contract filters are offline assumptions: BTC tick 0.10, ETH tick 0.01; both lot step 0.001; minimum notionals BTC 100 / ETH 20 USDT. They are not verified historical exchange filters.

Open gaps through stops fill at the adverse open. Gap targets get no favorable price improvement. When both stop/target touch in one OHLC candle, stop wins. Intrabar trigger times are unknown: assign exits at candle close. Funding debits within an uncertain exit bar conservatively apply, but uncertain intrabar credits are omitted and counted. Positions held through a known close can receive credits. Daily risk checks ignore deferred credits until survival through the bar is established. Opening-time funding is assessed before new entries, and only when entry_time < funding_time <= exit_time. Funding is signed (long pays positive, short receives positive) using recorded event mark price; missing mark falls back to the last known bar open, explicitly counted. Funding is cost accounting only, never a feature.

Daily loss checks use a conservative simultaneous adverse price path, capped at already-triggered stops; when the daily barrier is hit, surviving positions flatten at adverse bar extremes. This is a conservative OHLC approximation, not tick-level execution. Drawdown includes these adverse-bar marks. Backtest margin is an isolated-style exposure approximation; actual maintenance tiers, liquidation/ADL and order-book liquidity are not replicated. Cap shared entry leverage at 2x; reject planned stop losses that could consume allocated position margin. Effective leverage may change after entry as prices and equity move; continuous deleveraging is not modeled.

Journals separate raw price PnL, adverse fill/slippage+rounding cost, fees, funding and net PnL. Slippage is already embedded in execution-price PnL and must not be subtracted twice. End all positions at the final close and reconcile total trade net PnL to final equity minus initial equity. Decimal operation-order residuals up to 1e-12 USDT are tolerated and reported; material mismatches fail.

## Data and evidence

Read existing SQLite in read-only mode. Reject gaps, duplicate/misaligned markets, invalid candles and nonfinite funding. Record data/config hashes, range, decision/trade/equity journals, performance metrics and NO TRADE comparison. Historical funding events can be used ex post for settlement accounting; later observation timestamps do not make them available as earlier predictive features.

The existing single day is an integration sample. Any positive or negative result is descriptive of this sample AFTER assumed costs, not evidence of general profitability. Undefined win rate/profit factor must be null with an explanation. Synthetic test scenarios must never be labeled market performance.
