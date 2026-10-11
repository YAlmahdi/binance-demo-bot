"""Enumerate the frozen strategy independently of old portfolio admissions."""
from collections import Counter
from dataclasses import dataclass
from .config import START, DEV_END, SYMBOLS
from .features import causal_indicators, feature_at
from ..strategy import BaselineStrategy, Signal


@dataclass(frozen=True)
class Opportunity:
    row_id: str
    symbol: str
    decision_time: int
    candle_index: int
    signal: Signal


def enumerate_opportunities(markets):
    if set(markets) != set(SYMBOLS):
        raise ValueError("Both approved symbols are required")
    opportunities, features, counts = [], [], Counter()
    for symbol in SYMBOLS:
        candles = markets[symbol]
        # Reject locked observations before computing indicators or signals.
        if any(not START <= c.open_time <= c.close_time < DEV_END for c in candles):
            raise PermissionError("Opportunities are development-only")
        indicators = causal_indicators(candles)
        signals = BaselineStrategy().signals(candles)
        for index, signal in enumerate(signals):
            counts[symbol + ":candles"] += 1
            if signal.side == "NO TRADE":
                counts[symbol + ":NO_TRADE:" + signal.reason] += 1
                continue
            row, reason = feature_at(symbol, candles, indicators, index, signal.side)
            if row is None:
                counts[symbol + ":FEATURE_EXCLUDED:" + reason] += 1
                continue
            opportunities.append(Opportunity(row.row_id, symbol, row.decision_time, index, signal))
            features.append(row)
            counts[symbol + ":" + signal.side] += 1
    key = lambda row: (row.decision_time, row.symbol)
    return tuple(sorted(opportunities, key=key)), tuple(sorted(features, key=key)), dict(sorted(counts.items()))
