"""Frozen, interpretable indicator baseline; no execution dependencies."""
from dataclasses import dataclass, fields
from .indicators import build_features


@dataclass(frozen=True)
class Signal:
    side: str
    reason: str
    atr: float | None = None


class BaselineStrategy:
    version = "ema-rsi-macd-volume-v1"

    def signals(self, candles):
        result = []
        for candle, f in zip(candles, build_features(candles)):
            if any(getattr(f, item.name) is None for item in fields(f)):
                result.append(Signal("NO TRADE", "Indicator warm-up or unavailable volume"))
                continue
            long_trend = candle.close > f.ema20 > f.ema50 > f.ema200
            short_trend = candle.close < f.ema20 < f.ema50 < f.ema200
            if f.atr14 <= 0:
                result.append(Signal("NO TRADE", "ATR must be positive", f.atr14))
            elif f.relative_volume < 1.0:
                result.append(Signal("NO TRADE", "Volume below preceding 20-bar mean", f.atr14))
            elif long_trend and 50 <= f.rsi14 <= 70 and f.macd > 0 and f.macd_hist > 0:
                result.append(Signal("LONG", "Bullish EMA alignment, RSI, MACD and volume confirmation", f.atr14))
            elif short_trend and 30 <= f.rsi14 <= 50 and f.macd < 0 and f.macd_hist < 0:
                result.append(Signal("SHORT", "Bearish EMA alignment, RSI, MACD and volume confirmation", f.atr14))
            else:
                result.append(Signal("NO TRADE", "Trend/momentum conditions not aligned", f.atr14))
        return result
