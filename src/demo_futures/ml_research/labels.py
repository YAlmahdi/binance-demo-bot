"""Isolated label adapter over the unchanged cost/risk simulator."""
from bisect import bisect_right
from dataclasses import dataclass
from ..backtest import BacktestEngine, Trade
from ..risk import BacktestConfig
from ..strategy import Signal
from .config import START, DEV_END, STEP, HORIZON, SYMBOLS, require_development
from .opportunities import Opportunity


class OneOpportunity:
    version = "isolated-frozen-baseline-v001"

    def __init__(self, signal):
        self.signal = signal

    def signals(self, candles):
        return [self.signal] + [Signal("NO TRADE", "Isolated reference: no additional opportunity")
                                for _ in candles[1:]]


@dataclass(frozen=True)
class LabelResult:
    row_id: str
    symbol: str
    decision_time: int
    interval_start: int
    interval_end: int
    status: str
    reason: str
    y: int | None = None
    trade: Trade | None = None

    def __post_init__(self):
        if (self.symbol not in SYMBOLS or self.row_id != f"{self.symbol}:{self.decision_time}"
                or not START <= self.decision_time < DEV_END
                or self.interval_start != self.decision_time + 1
                or self.interval_end != self.interval_start + HORIZON * STEP
                or self.status not in ("VALID", "INCOMPLETE_HORIZON", "FUNDING_UNCERTAIN", "NO_EXECUTABLE_REFERENCE_TRADE")):
            raise ValueError("Invalid label identity, status or conservative horizon")
        if self.status == "VALID":
            if self.y not in (0, 1) or self.trade is None:
                raise ValueError("A valid label needs an outcome")
            if self.y != int(self.trade.net_pnl > 0):
                raise ValueError("Target disagrees with net PnL")
        elif self.y is not None or self.trade is not None:
            raise ValueError("Excluded labels cannot invent outcomes")


def label_opportunity(opportunity, candles, funding, funding_gaps=(), *, outcome_end=DEV_END):
    op = opportunity
    # Refuse protected periods before touching candles or funding.
    require_development(op.decision_time, outcome_end)
    if op.symbol not in SYMBOLS or op.signal.side not in ("LONG", "SHORT"):
        raise ValueError("Invalid opportunity context")
    i = op.candle_index
    if not 0 <= i < len(candles) or candles[i].close_time != op.decision_time:
        raise ValueError("Opportunity does not match the source decision candle")
    start = op.decision_time + 1
    end = start + HORIZON * STEP

    def excluded(status, reason):
        return LabelResult(op.row_id, op.symbol, op.decision_time, start, end, status, reason)

    if end > outcome_end or i + HORIZON >= len(candles):
        return excluded("INCOMPLETE_HORIZON", "Full 48 future candles required inside permitted outcome period")
    window = candles[i:i + HORIZON + 1]
    if window[1].open_time != start or window[-1].close_time + 1 != end:
        raise ValueError("Label horizon is not the next contiguous 48 candles")
    if any(not START <= event.timestamp < DEV_END for event in funding):
        raise PermissionError("Label funding input must be development-only")
    times = [event.timestamp for event in funding]
    if times != sorted(set(times)):
        raise ValueError("Funding must be chronological and unique")
    if any(start <= gap < end for gap in funding_gaps):
        return excluded("FUNDING_UNCERTAIN", "Conservative full horizon overlaps a potential funding gap")
    # Include one preceding real event, then all actual events in the window.
    # A preceding event does not settle; no dummy event or missing-funding override.
    left = max(0, bisect_right(times, window[0].open_time) - 1)
    right = bisect_right(times, end - 1)
    events = funding[left:right]
    if not events:
        return excluded("FUNDING_UNCERTAIN", "No recorded funding context; zero funding is not assumed")
    result = BacktestEngine(BacktestConfig(), strategy=OneOpportunity(op.signal)).run(
        {op.symbol: window}, funding={op.symbol: events})
    if not result.trades:
        reasons = [d.reason for d in result.decisions if d.action == "REJECTED"]
        return excluded("NO_EXECUTABLE_REFERENCE_TRADE", "; ".join(reasons) or "Reference entry was not filled")
    if len(result.trades) != 1:
        raise ArithmeticError("Isolated adapter must generate exactly one trade")
    trade = result.trades[0]
    if (trade.signal_time != op.decision_time or trade.entry_time != start
            or not start <= trade.exit_time < end or trade.exit_reason == "end_of_data"):
        raise ArithmeticError("Reference label violates next-open/full-horizon timing")
    return LabelResult(op.row_id, op.symbol, op.decision_time, start, end,
                       "VALID", "Net PnL positive" if trade.net_pnl > 0 else "Net PnL nonpositive",
                       int(trade.net_pnl > 0), trade)
