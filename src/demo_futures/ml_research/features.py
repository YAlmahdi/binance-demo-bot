"""Fixed causal numeric schema. Future-dependent labels never enter this module."""
from dataclasses import dataclass
import math

from ..data import validate_candles
from ..indicators import build_features
from .config import FEATURE_NAMES, SYMBOLS, START, DEV_END


@dataclass(frozen=True)
class FeatureRow:
    row_id: str
    symbol: str
    decision_time: int
    available_at: int
    values: tuple[float, ...]

    def __post_init__(self):
        if (len(self.values) != 16 or any(not math.isfinite(v) for v in self.values)
                or self.available_at > self.decision_time):
            raise ValueError("Invalid feature schema, finite values or availability")


def causal_indicators(candles):
    if any(not START <= c.open_time <= c.close_time < DEV_END for c in candles):
        raise PermissionError("Feature inputs are development-only")
    validate_candles(candles, "5m")
    return build_features(candles)


def feature_at(symbol, candles, indicators, index, side):
    if symbol not in SYMBOLS or side not in ("LONG", "SHORT") or not 0 <= index < len(candles):
        raise ValueError("Invalid causal feature context")
    if not START <= candles[index].open_time <= candles[index].close_time < DEV_END:
        raise PermissionError("Decision feature is outside development")
    if index < 199:
        return None, "WARMUP"
    f, c = indicators[index], candles[index]
    fields = (f.ema20, f.ema50, f.ema200, f.rsi14, f.macd, f.macd_hist, f.atr14, f.relative_volume)
    if any(v is None or not math.isfinite(v) for v in fields) or min(f.ema20, f.ema50, f.ema200, c.close) <= 0:
        return None, "UNAVAILABLE_OR_NONFINITE_FEATURE"
    values = tuple(math.log(c.close / candles[index-k].close) for k in (1, 3, 12, 48)) + (
        c.close/f.ema20-1, f.ema20/f.ema50-1, f.ema50/f.ema200-1,
        (f.rsi14-50)/50, f.macd/c.close, f.macd_hist/c.close, f.atr14/c.close,
        f.relative_volume, (c.high-c.low)/c.close, (c.close-c.open)/c.close,
        float(symbol == "ETHUSDT"), float(side == "LONG"),
    )
    if any(not math.isfinite(v) for v in values):
        return None, "UNAVAILABLE_OR_NONFINITE_FEATURE"
    return FeatureRow(f"{symbol}:{c.close_time}", symbol, c.close_time, c.close_time, values), None
