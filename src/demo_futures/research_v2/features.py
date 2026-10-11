"""Point-in-time feature calculation on caller-supplied synthetic candles only."""
from dataclasses import dataclass
import math
import statistics
from ..data import Candle, DataQualityError, validate_candles
from ..indicators import atr
from .config import FEATURES, HOUR, STEP, Recipe, BtcEthEncoder, require_symbol, timestamp

@dataclass(frozen=True)
class ObservedCandle:
    candle: Candle
    available_at: int

    def __post_init__(self):
        timestamp(self.available_at)
        if not isinstance(self.candle, Candle) or self.available_at < self.candle.close_time + 1:
            raise ValueError("Observation cannot precede candle completion")

@dataclass(frozen=True)
class SyntheticSeries:
    symbol: str
    observations: tuple[ObservedCandle, ...]
    fixture_id: str
    evidence: str = "SYNTHETIC_ONLY"

    def __post_init__(self):
        require_symbol(self.symbol)
        if self.evidence != "SYNTHETIC_ONLY" or not self.fixture_id:
            raise PermissionError("Only explicitly identified synthetic fixtures supported")
        object.__setattr__(self, "observations", tuple(self.observations))
        if any(not isinstance(v, ObservedCandle) for v in self.observations):
            raise ValueError("Observed candles required")

@dataclass(frozen=True)
class FeatureRow:
    symbol: str
    decision_time: int
    status: str
    reason: str
    values: tuple[float, ...] | None = None
    atr14: float | None = None

    def __post_init__(self):
        require_symbol(self.symbol)
        timestamp(self.decision_time)
        if (self.decision_time + 1) % HOUR:
            raise ValueError("Decision must be the close immediately before a UTC hour")
        if self.status not in ("READY", "WARMUP", "DATA_QUALITY"):
            raise ValueError("Unknown feature state")
        if self.status == "READY":
            object.__setattr__(self, "values", tuple(self.values or ()))
            if (len(self.values) != len(FEATURES)
                    or any(isinstance(v, bool) or not math.isfinite(v) for v in self.values)
                    or self.values[-1] != BtcEthEncoder().encode(self.symbol)
                    or self.atr14 is None or not math.isfinite(self.atr14) or self.atr14 <= 0):
                raise ValueError("Invalid feature vector")
        elif self.values is not None or self.atr14 is not None:
            raise ValueError("Abstained rows cannot contain usable features")

    @property
    def row_id(self):
        return f"{self.symbol}:{self.decision_time}"

def feature_at(series, decision_time):
    """Do not inspect future values or use candles received after decision completion."""
    require_symbol(series.symbol)
    timestamp(decision_time)
    boundary = decision_time + 1
    if boundary % HOUR:
        raise ValueError("Exact UTC hourly decision required")
    if series.evidence != "SYNTHETIC_ONLY":
        raise PermissionError("Historical access is not implemented")
    def rejected(status, reason):
        return FeatureRow(series.symbol, decision_time, status, reason)
    completed = [v for v in series.observations if v.candle.close_time <= decision_time]
    if not completed or completed[-1].candle.close_time != decision_time:
        return rejected("DATA_QUALITY", "MISSING_DECISION_BAR")
    if any(v.available_at > boundary for v in completed):
        return rejected("DATA_QUALITY", "NOT_AVAILABLE_AT_DECISION")
    bars = [v.candle for v in completed]
    if any(type(c.open_time) is not int or type(c.close_time) is not int or type(c.trades) is not int
           or any(isinstance(getattr(c,n),bool) for n in ("open","high","low","close","volume","quote_volume")) for c in bars):
        return rejected("DATA_QUALITY", "INVALID_CANDLE_TYPES")
    try:
        validate_candles(bars, "5m", boundary, require_contiguous=True)
    except (DataQualityError, ValueError, TypeError, OverflowError):
        return rejected("DATA_QUALITY", "INVALID_OR_GAPPED_PREFIX")
    if len(bars) < Recipe().warmup_bars:
        return rejected("WARMUP", "200_CONTIGUOUS_COMPLETED_BARS_REQUIRED")
    current = bars[-1]
    if current.volume <= 0 or current.high == current.low:
        return rejected("DATA_QUALITY", "ZERO_VOLUME_OR_RANGE_DECISION")
    prior_volume = statistics.fmean(c.volume for c in bars[-21:-1])
    if prior_volume <= 0:
        return rejected("DATA_QUALITY", "NONPOSITIVE_PRIOR_VOLUME")
    closes = [c.close for c in bars]
    try:
        returns = [math.log(closes[i] / closes[i - 1]) for i in range(len(closes) - 48, len(closes))]
        atr14 = atr(bars, 14)[-1]  # Frozen Wilder seed, full supplied contiguous prefix.
        values = tuple(math.log(closes[-1] / closes[-1 - n]) for n in (1, 12, 48)) + (
            statistics.pstdev(returns), atr14 / current.close,
            (current.high - current.low) / current.close,
            (current.close - current.open) / current.close,
            math.log1p(current.volume / prior_volume),
            float(BtcEthEncoder().encode(series.symbol)))
        return FeatureRow(series.symbol, decision_time, "READY", "CAUSAL_INPUTS_VALID", values, atr14)
    except (ValueError, TypeError, OverflowError, ZeroDivisionError):
        return rejected("DATA_QUALITY", "NONFINITE_FEATURE")
