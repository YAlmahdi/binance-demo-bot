"""Deterministic offline OHLC portfolio simulation. No API or credential imports."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
import hashlib
import json

from .data import Candle, validate_candles
from .risk import BacktestConfig, ContractSpec, DEFAULT_SPECS, DailyLossGuard, dec, fill_price, size_position
from .strategy import BaselineStrategy

ZERO = Decimal(0)
ACCOUNTING_TOLERANCE = Decimal("1e-12")  # USDT; Decimal operation-order roundoff only.


@dataclass(frozen=True)
class FundingEvent:
    timestamp: int
    rate: Decimal
    mark_price: Decimal | None = None

    def __post_init__(self):
        if type(self.timestamp) is not int or self.timestamp < 0:
            raise ValueError("Funding timestamp must be a nonnegative integer")
        object.__setattr__(self, "rate", dec(self.rate))
        if self.mark_price is not None:
            object.__setattr__(self, "mark_price", dec(self.mark_price))
            if self.mark_price <= 0:
                raise ValueError("Funding mark price must be positive")


@dataclass
class Position:
    symbol: str
    side: str
    quantity: Decimal
    signal_time: int
    entry_time: int
    entry_index: int
    entry_reference: Decimal
    entry_price: Decimal
    stop_price: Decimal
    target_price: Decimal
    risk_budget: Decimal
    planned_loss: Decimal
    margin: Decimal
    entry_fee: Decimal
    entry_reason: str
    funding_cost: Decimal = ZERO
    funding_fallbacks: int = 0
    funding_credits_skipped: int = 0

    @property
    def sign(self):
        return Decimal(1) if self.side == "LONG" else Decimal(-1)


@dataclass(frozen=True)
class Trade:
    symbol: str
    side: str
    signal_time: int
    entry_time: int
    exit_time: int
    quantity: Decimal
    entry_reference: Decimal
    entry_price: Decimal
    exit_reference: Decimal
    exit_price: Decimal
    stop_price: Decimal
    target_price: Decimal
    risk_budget: Decimal
    planned_loss: Decimal
    margin: Decimal
    gross_pnl: Decimal
    execution_price_pnl: Decimal
    fees: Decimal
    slippage_cost: Decimal
    funding_cost: Decimal
    net_pnl: Decimal
    entry_reason: str
    exit_reason: str
    funding_mark_fallbacks: int
    uncertain_funding_credits_skipped: int = 0


@dataclass(frozen=True)
class Decision:
    symbol: str
    timestamp: int
    side: str
    action: str
    reason: str
    signal_time: int | None = None


@dataclass(frozen=True)
class EquityPoint:
    timestamp: int
    equity: Decimal
    kind: str


@dataclass
class BacktestResult:
    config: BacktestConfig
    specs: dict[str, ContractSpec]
    interval: str
    strategy_version: str
    data_hash: str
    start_time: int
    end_time: int
    bars_per_symbol: int
    trades: list[Trade]
    decisions: list[Decision]
    equity: list[EquityPoint]
    metrics: dict
    no_trade_metrics: dict
    warnings: list[str]


def metrics(trades, equity, initial):
    initial = dec(initial)
    final = equity[-1].equity if equity else initial
    net = sum((t.net_pnl for t in trades), ZERO)
    if abs(final - initial - net) > ACCOUNTING_TOLERANCE:
        raise ArithmeticError("Trade journal does not reconcile to account equity")
    wins = [t.net_pnl for t in trades if t.net_pnl > 0]
    losses = [t.net_pnl for t in trades if t.net_pnl < 0]
    peak, drawdown, drawdown_pct = initial, ZERO, ZERO
    for point in equity:
        peak = max(peak, point.equity)
        drop = peak - point.equity
        drawdown = max(drawdown, drop)
        if peak > 0:
            drawdown_pct = max(drawdown_pct, drop / peak * 100)
    positive, negative = sum(wins, ZERO), -sum(losses, ZERO)
    return {
        "initial_equity": initial, "final_equity": final, "net_pnl": net,
        "accounting_residual_usdt": final - initial - net,
        "net_return_pct": (final / initial - 1) * 100,
        "trades": len(trades), "wins": len(wins), "losses": len(losses),
        "breakeven_trades": len(trades) - len(wins) - len(losses),
        "win_rate_pct": Decimal(len(wins)) / len(trades) * 100 if trades else None,
        "profit_factor": positive / negative if negative else None,
        "profit_factor_status": "finite" if negative else ("no_losses" if trades else "no_trades"),
        "maximum_drawdown": drawdown, "maximum_drawdown_pct": drawdown_pct,
        "gross_pnl": sum((t.gross_pnl for t in trades), ZERO),
        "execution_price_pnl": sum((t.execution_price_pnl for t in trades), ZERO),
        "fees": sum((t.fees for t in trades), ZERO),
        "slippage_cost": sum((t.slippage_cost for t in trades), ZERO),
        "funding_cost": sum((t.funding_cost for t in trades), ZERO),
        "total_costs": sum((t.fees + t.slippage_cost + t.funding_cost for t in trades), ZERO),
        "turnover": sum((t.quantity * (t.entry_price + t.exit_price) for t in trades), ZERO),
        "average_net_trade": net / len(trades) if trades else None,
    }


class BacktestEngine:
    def __init__(self, config=None, specs=None, strategy=None):
        self.config = config or BacktestConfig()
        self.specs = dict(DEFAULT_SPECS if specs is None else specs)
        self.strategy = strategy or BaselineStrategy()

    def run(self, markets, interval="5m", funding=None):
        if not markets or not set(markets) <= {"BTCUSDT", "ETHUSDT"}:
            raise ValueError("Only historical BTCUSDT/ETHUSDT markets are supported")
        symbols = sorted(markets)
        bars = {symbol: validate_candles(markets[symbol], interval) for symbol in symbols}
        if any(not bars[symbol] for symbol in symbols):
            raise ValueError("Empty historical market")
        grid = [c.open_time for c in bars[symbols[0]]]
        if any([c.open_time for c in bars[symbol]] != grid for symbol in symbols):
            raise ValueError("Markets must have exactly aligned contiguous bar times")
        if not set(symbols) <= set(self.specs):
            raise ValueError("Missing explicit offline contract assumptions")
        funding = funding or {}
        events = {symbol: list(funding.get(symbol, [])) for symbol in symbols}
        for symbol in symbols:
            if not events[symbol] and not self.config.allow_missing_funding:
                raise ValueError("Funding history missing; explicit zero-funding assumption is required")
            times = [event.timestamp for event in events[symbol]]
            if times != sorted(set(times)):
                raise ValueError("Funding must be chronological with unique timestamps")
        signals = {symbol: list(self.strategy.signals(bars[symbol])) for symbol in symbols}
        if any(len(signals[symbol]) != len(grid) for symbol in symbols):
            raise ValueError("Strategy must return exactly one signal per candle")
        for series in signals.values():
            if any(s.side not in ("LONG", "SHORT", "NO TRADE") for s in series):
                raise ValueError("Unknown strategy signal")

        config = self.config
        cash = config.initial_equity
        positions = {}
        trades, decisions, curve = [], [], []
        guard = DailyLossGuard(config.daily_loss_fraction)
        pending = {}

        def equity(prices):
            return cash + sum((p.sign * p.quantity * (prices[s] - p.entry_price)
                               for s, p in positions.items()), ZERO)

        def settle_funding(position, left, right, reference, deferred_credits=None):
            nonlocal cash
            for event in events[position.symbol]:
                if left <= event.timestamp <= right and position.entry_time < event.timestamp:
                    mark = event.mark_price if event.mark_price is not None else reference
                    cost = position.sign * position.quantity * mark * event.rate
                    if cost < 0 and deferred_credits is not None:
                        deferred_credits.append((position.symbol, cost, event.mark_price is None))
                        continue
                    cash -= cost
                    position.funding_cost += cost
                    if event.mark_price is None:
                        position.funding_fallbacks += 1

        def close(symbol, timestamp, reference, reason):
            nonlocal cash
            p = positions.pop(symbol)
            price = fill_price(reference, p.side == "SHORT", self.specs[symbol], config)
            exit_fee = p.quantity * price * config.fee_rate
            price_pnl = p.sign * p.quantity * (price - p.entry_price)
            gross = p.sign * p.quantity * (reference - p.entry_reference)
            slippage = p.quantity * (abs(p.entry_price - p.entry_reference) + abs(price - reference))
            fees = p.entry_fee + exit_fee
            net = price_pnl - fees - p.funding_cost
            if abs(gross - slippage - price_pnl) > ACCOUNTING_TOLERANCE:
                raise ArithmeticError("Adverse fill accounting mismatch")
            cash += price_pnl - exit_fee
            trades.append(Trade(symbol, p.side, p.signal_time, p.entry_time, timestamp,
                                p.quantity, p.entry_reference, p.entry_price, reference, price,
                                p.stop_price, p.target_price, p.risk_budget, p.planned_loss, p.margin,
                                gross, price_pnl, fees, slippage, p.funding_cost, net,
                                p.entry_reason, reason, p.funding_fallbacks, p.funding_credits_skipped))

        for i, timestamp in enumerate(grid):
            current = {symbol: bars[symbol][i] for symbol in symbols}
            opens = {symbol: dec(c.open) for symbol, c in current.items()}
            closes = {symbol: dec(c.close) for symbol, c in current.items()}
            close_time = current[symbols[0]].close_time
            guard.begin_day(timestamp // 86_400_000, equity(opens))
            curve.append(EquityPoint(timestamp, equity(opens), "bar_open"))

            for symbol in list(positions):
                p, c = positions[symbol], current[symbol]
                settle_funding(p, timestamp, timestamp, opens[symbol])
                opening = opens[symbol]
                if (p.side == "LONG" and opening <= p.stop_price) or (p.side == "SHORT" and opening >= p.stop_price):
                    close(symbol, timestamp, opening, "stop_gap")
                elif (p.side == "LONG" and opening >= p.target_price) or (p.side == "SHORT" and opening <= p.target_price):
                    close(symbol, timestamp, p.target_price, "target_gap_no_improvement")

            if guard.check(equity(opens)):
                for symbol in list(positions):
                    close(symbol, timestamp, opens[symbol], "daily_loss_open")
            for symbol in symbols:
                # Entry fees/friction from a prior same-open fill can cross the daily limit.
                guard.check(equity(opens))
                signal = pending.get(symbol)
                if signal is None or signal.side == "NO TRADE":
                    continue
                reason = None
                if guard.halted:
                    reason = "UTC daily loss halt; new entries blocked"
                elif symbol in positions:
                    reason = "Position already open; pyramiding prohibited"
                elif len(positions) >= config.max_positions:
                    reason = "Shared portfolio position cap"
                if reason:
                    decisions.append(Decision(symbol, timestamp, signal.side, "REJECTED", reason,
                                              bars[symbol][i - 1].close_time))
                    continue
                reserved = sum((abs(p.quantity * opens[s]) for s, p in positions.items()), ZERO)
                plan, reason = size_position(equity(opens), opens[symbol], signal.atr or 0,
                                             signal.side, self.specs[symbol], config, reserved)
                signal_time = bars[symbol][i - 1].close_time
                if signal_time >= timestamp:
                    raise ArithmeticError("Entry must follow the signal candle")
                if plan is None:
                    decisions.append(Decision(symbol, timestamp, signal.side, "REJECTED", reason, signal_time))
                    continue
                fee = plan.quantity * plan.entry_price * config.fee_rate
                cash -= fee
                positions[symbol] = Position(symbol, signal.side, plan.quantity, signal_time, timestamp, i,
                                             opens[symbol], plan.entry_price, plan.stop_price, plan.target_price,
                                             plan.budget, plan.planned_loss, plan.margin, fee, signal.reason)
                decisions.append(Decision(symbol, timestamp, signal.side, "ENTERED", reason, signal_time))

            candidates, worst_references, deferred_credits = {}, {}, []
            for symbol, p in positions.items():
                c = current[symbol]
                settle_funding(p, timestamp + 1, close_time, opens[symbol], deferred_credits)
                stop_hit = dec(c.low) <= p.stop_price if p.side == "LONG" else dec(c.high) >= p.stop_price
                target_hit = dec(c.high) >= p.target_price if p.side == "LONG" else dec(c.low) <= p.target_price
                if stop_hit:
                    candidates[symbol] = (p.stop_price, "stop_loss_both_touched" if target_hit else "stop_loss")
                elif target_hit:
                    candidates[symbol] = (p.target_price, "take_profit")
                elif i - p.entry_index + 1 >= config.max_holding_bars:
                    candidates[symbol] = (closes[symbol], "holding_time_limit")
                worst_references[symbol] = p.stop_price if stop_hit else dec(c.low if p.side == "LONG" else c.high)

            worst_equity = cash
            for symbol, p in positions.items():
                price = fill_price(worst_references[symbol], p.side == "SHORT", self.specs[symbol], config)
                worst_equity += p.sign * p.quantity * (price - p.entry_price) - p.quantity * price * config.fee_rate
            curve.append(EquityPoint(close_time, worst_equity, "conservative_intrabar_liquidation_value"))
            daily_hit = guard.check(worst_equity)
            # OHLC cannot prove an intrabar exit occurred after a funding credit.
            # Keep uncertain debits, omit uncertain credits; known close-time holds receive credits.
            for symbol, credit, fallback in deferred_credits:
                candidate = candidates.get(symbol)
                uncertain_exit = daily_hit or (candidate and candidate[1] != "holding_time_limit")
                if uncertain_exit:
                    positions[symbol].funding_credits_skipped += 1
                else:
                    cash -= credit
                    positions[symbol].funding_cost += credit
                    positions[symbol].funding_fallbacks += int(fallback)
            for symbol in list(positions):
                candidate = candidates.get(symbol)
                if candidate and candidate[1].startswith("stop_loss"):
                    close(symbol, close_time, *candidate)
                elif daily_hit:
                    close(symbol, close_time, worst_references[symbol], "daily_loss_intrabar_conservative")
                elif candidate:
                    close(symbol, close_time, *candidate)
            curve.append(EquityPoint(close_time, equity(closes), "bar_close"))
            guard.check(equity(closes))
            pending = {}
            for symbol in symbols:
                signal = signals[symbol][i]
                action = "NO_TRADE" if signal.side == "NO TRADE" else ("NO_NEXT_BAR" if i == len(grid) - 1 else "SIGNAL")
                decisions.append(Decision(symbol, close_time, signal.side, action, signal.reason))
                pending[symbol] = signal

        end_time = bars[symbols[0]][-1].close_time
        for symbol in list(positions):
            close(symbol, end_time, dec(bars[symbol][-1].close), "end_of_data")
        curve.append(EquityPoint(end_time, cash, "final_realized_equity"))
        strategy_metrics = metrics(trades, curve, config.initial_equity)
        baseline_curve = [EquityPoint(grid[0], config.initial_equity, "cash"),
                          EquityPoint(end_time, config.initial_equity, "cash")]
        baseline_metrics = metrics([], baseline_curve, config.initial_equity)
        intervals = sorted((t.entry_time, t.exit_time + 1) for t in trades)
        occupied, left, right = 0, None, None
        for start, end in intervals:
            if left is None:
                left, right = start, end
            elif start <= right:
                right = max(right, end)
            else:
                occupied += right - left
                left, right = start, end
        if left is not None:
            occupied += right - left
        strategy_metrics["exposure_time_pct"] = Decimal(occupied) / (end_time + 1 - grid[0]) * 100
        baseline_metrics["exposure_time_pct"] = ZERO
        payload = {"bars": {s: [asdict(c) for c in bars[s]] for s in symbols},
                   "funding": {s: [asdict(e) for e in events[s]] for s in symbols}}
        data_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
        warnings = [
            "Offline fee, slippage and contract filters are research assumptions, not historical Binance guarantees.",
            "OHLC ordering is unknown: stops win ambiguous bars; intrabar exits are assigned to bar close.",
            "Uncertain intrabar exit bars pay funding debits but do not receive funding credits; skipped credits are counted.",
            "Daily halt and drawdown use conservative adverse-bar liquidation values, not a tick-level path.",
            "No maintenance-margin tiers, liquidation/ADL, order-book liquidity or network/exchange execution is simulated.",
            "Recorded historical funding settles costs only; observation timestamps are not used as predictive features.",
            "Funding history completeness is not independently verified; gap losses may exceed planned risk.",
        ]
        if any(not events[s] for s in symbols):
            warnings.append("Explicit missing-funding override: zero funding was assumed for at least one symbol.")
        if len(grid) < 1000:
            warnings.append("Small historical sample: this run cannot establish general profitability.")
        if not trades:
            warnings.append("No trades were executed. Zero PnL is not evidence of a profitable strategy.")
        if any(p.equity <= 0 for p in curve):
            warnings.append("Simulated equity reached zero or below; insolvency occurred under the assumptions.")
        return BacktestResult(config, {s: self.specs[s] for s in symbols}, interval,
                              getattr(self.strategy, "version", type(self.strategy).__name__), data_hash,
                              grid[0], end_time, len(grid), trades, decisions, curve,
                              strategy_metrics, baseline_metrics, warnings)
