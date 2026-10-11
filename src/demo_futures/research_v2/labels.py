"""Paired synthetic counterfactuals using the unchanged frozen simulator."""
from dataclasses import dataclass
from decimal import Decimal
from ..backtest import BacktestEngine, FundingEvent, Trade
from ..data import validate_candles, DataQualityError
from ..strategy import Signal
from .config import HORIZON, STEP, require_symbol, timestamp, frozen_financial_config
from .features import SyntheticSeries, feature_at
from .opportunities import Opportunity

@dataclass(frozen=True)
class FundingCoverage:
    """Externally asserted fixture coverage, not an inferred settlement schedule."""
    start: int
    end: int
    complete: bool
    events: tuple[FundingEvent, ...] = ()
    uncertain_intervals: tuple[tuple[int, int], ...] = ()
    evidence: str = "SYNTHETIC_ONLY"
    symbol: str = "BTCUSDT"

    def __post_init__(self):
        require_symbol(self.symbol)
        timestamp(self.start); timestamp(self.end)
        if self.start >= self.end or type(self.complete) is not bool or self.evidence != "SYNTHETIC_ONLY":
            raise ValueError("Synthetic funding coverage contract required")
        object.__setattr__(self, "events", tuple(self.events))
        object.__setattr__(self, "uncertain_intervals", tuple(tuple(v) for v in self.uncertain_intervals))
        if any(not isinstance(v, FundingEvent) for v in self.events):
            raise ValueError("FundingEvent records required")
        times = [v.timestamp for v in self.events]
        if times != sorted(set(times)):
            raise ValueError("Unique chronological funding events required")
        for left, right in self.uncertain_intervals:
            timestamp(left); timestamp(right)
            if left >= right: raise ValueError("Nonempty uncertain funding interval required")

@dataclass(frozen=True)
class ActionOutcome:
    side: str
    status: str
    reason: str
    trade: Trade | None = None
    net_r: Decimal | None = None
    budget_breach: bool = False
    funding_reserve_overrun: bool = False

    def __post_init__(self):
        if self.side not in ("LONG", "SHORT"):
            raise ValueError("Counterfactual action required")
        if self.status == "VALID":
            if (self.trade is None or self.trade.side != self.side or not isinstance(self.net_r, Decimal)
                    or not self.net_r.is_finite() or self.net_r != self.trade.net_pnl / Decimal(50)):
                raise ValueError("Valid label must reconcile to the 50-USDT reference budget")
            if (type(self.budget_breach) is not bool or type(self.funding_reserve_overrun) is not bool
                    or self.budget_breach != (-self.trade.net_pnl > self.trade.risk_budget)
                    or self.funding_reserve_overrun != (self.trade.funding_cost > self.trade.quantity * self.trade.entry_price * Decimal(".001"))):
                raise ValueError("Risk flags disagree with uncapped synthetic outcomes")
        elif self.status not in ("CAUSAL_ABSTENTION", "INCOMPLETE_HORIZON",
                                 "DATA_QUALITY", "FUNDING_UNCERTAIN",
                                 "FUNDING_CONTEXT_UNAVAILABLE", "NO_EXECUTABLE_REFERENCE_TRADE"):
            raise ValueError("Unknown excluded label state")
        elif self.trade is not None or self.net_r is not None or self.budget_breach or self.funding_reserve_overrun:
            raise ValueError("Excluded label cannot invent outcomes")

@dataclass(frozen=True)
class PairedOutcome:
    opportunity: Opportunity
    long: ActionOutcome
    short: ActionOutcome

    def __post_init__(self):
        if self.long.side != "LONG" or self.short.side != "SHORT":
            raise ValueError("LONG and SHORT labels must remain distinct")
        for action in (self.long, self.short):
            if action.trade is not None and (action.trade.symbol != self.opportunity.symbol
                    or action.trade.signal_time != self.opportunity.decision_time
                    or action.trade.entry_time != self.opportunity.interval_start
                    or not self.opportunity.interval_start <= action.trade.exit_time < self.opportunity.interval_end):
                raise ValueError("Trade does not match opportunity identity/horizon")

    @property
    def fit_eligible(self):
        return self.long.status == self.short.status == "VALID"

    @property
    def cash_r(self): return Decimal(0)

    def hindsight_action(self):
        """Training-target semantics only, never a portfolio or prediction."""
        if not self.fit_eligible:
            raise ValueError("Invalid/unknown outcomes are exclusions, not NO TRADE")
        a, b = self.long.net_r, self.short.net_r
        if a == b or max(a, b) <= 0:
            return "NO TRADE"
        return "LONG" if a > b else "SHORT"

class _SingleAction:
    version = "v2-synthetic-isolated-v001"
    def __init__(self, side, atr):
        self.signal = Signal(side, "V2 synthetic counterfactual; no baseline eligibility filter", atr)
    def signals(self, bars):
        return [self.signal] + [Signal("NO TRADE", "No further synthetic opportunity") for _ in bars[1:]]

def paired_outcome(opportunity, series, coverage, *, outcome_end):
    """Requires full 48-bar horizon even if an action would exit early."""
    op = opportunity
    require_symbol(op.symbol)
    if not isinstance(series, SyntheticSeries) or series.evidence != "SYNTHETIC_ONLY":
        raise PermissionError("Synthetic fixture series required")
    if op.symbol != series.symbol: raise ValueError("Symbol mismatch")
    if feature_at(series, op.decision_time) != op.features:
        raise ValueError("Opportunity features do not match this causal fixture prefix")
    timestamp(outcome_end)
    start, end = op.interval_start, op.interval_end
    def excluded(status, reason):
        return PairedOutcome(op, ActionOutcome("LONG", status, reason),
                             ActionOutcome("SHORT", status, reason))
    if op.features.status != "READY":
        return excluded("CAUSAL_ABSTENTION", op.features.reason)
    if end > outcome_end:
        return excluded("INCOMPLETE_HORIZON", "Full horizon must stay inside supplied synthetic period")
    observed = [v for v in series.observations
                if op.decision_time - STEP + 1 <= v.candle.open_time < end]
    window = [v.candle for v in observed]
    if len(window) != 49 or any(v.available_at > outcome_end for v in observed):
        return excluded("INCOMPLETE_HORIZON", "Decision bar plus 48 completed outcome bars required")
    try:
        validate_candles(window, "5m", outcome_end, require_contiguous=True)
    except (DataQualityError, ValueError, TypeError):
        return excluded("DATA_QUALITY", "Invalid or gapped outcome window")
    if window[0].close_time != op.decision_time or window[1].open_time != start or window[-1].close_time + 1 != end:
        return excluded("DATA_QUALITY", "Outcome grid mismatch")
    if isinstance(coverage, FundingCoverage) and coverage.symbol != op.symbol:
        raise ValueError("Funding coverage symbol mismatch")
    if (not isinstance(coverage, FundingCoverage) or not coverage.complete
            or coverage.start > start or coverage.end < end
            or any(left < end and right > start for left, right in coverage.uncertain_intervals)):
        return excluded("FUNDING_UNCERTAIN", "Full conservative horizon lacks proven synthetic funding coverage")
    # Real preceding context is allowed; never fabricate a settlement or enable zero-funding override.
    events = tuple(v for v in coverage.events if v.timestamp < end)
    if not events:
        return excluded("FUNDING_CONTEXT_UNAVAILABLE", "Frozen simulator requires real funding context; adapter policy deferred")
    if any(start < v.timestamp < end and v.mark_price is None for v in events):
        return excluded("FUNDING_UNCERTAIN", "Required synthetic settlement mark input unavailable")
    config = frozen_financial_config()
    def simulate(side):
        result = BacktestEngine(config, strategy=_SingleAction(side, op.features.atr14)).run(
            {op.symbol: window}, funding={op.symbol: events})
        if not result.trades:
            return ActionOutcome(side, "NO_EXECUTABLE_REFERENCE_TRADE",
                                 "Frozen sizing refused reference entry; never increase risk")
        if len(result.trades) != 1:
            raise ArithmeticError("Exactly one fresh-account isolated trade required")
        trade = result.trades[0]
        if trade.exit_reason == "end_of_data" or trade.risk_budget != Decimal(50):
            raise ArithmeticError("Full-horizon reference contract violated")
        if abs(trade.gross_pnl - trade.slippage_cost - trade.fees - trade.funding_cost - trade.net_pnl) > Decimal("1e-12"):
            raise ArithmeticError("Synthetic cost accounting mismatch")
        return ActionOutcome(side, "VALID", "Reconciled synthetic payoff; risk NOT CLEARED", trade,
                             trade.net_pnl / Decimal(50),
                             -trade.net_pnl > trade.risk_budget,
                             trade.funding_cost > trade.quantity * trade.entry_price * config.funding_reserve_rate)
    return PairedOutcome(op, simulate("LONG"), simulate("SHORT"))
