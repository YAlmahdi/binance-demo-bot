"""Hourly paired scheduling; no baseline filters, labels, inference or I/O."""
from dataclasses import dataclass
from .config import HOUR, HORIZON, SYMBOLS, timestamp
from .features import FeatureRow, feature_at

@dataclass(frozen=True)
class Opportunity:
    features: FeatureRow

    @property
    def row_id(self): return self.features.row_id
    @property
    def symbol(self): return self.features.symbol
    @property
    def decision_time(self): return self.features.decision_time
    @property
    def interval_start(self): return self.decision_time + 1
    @property
    def interval_end(self): return self.interval_start + HORIZON

def hourly_opportunities(markets, start_hour, end_hour, *, available_at):
    """Explicit synthetic UTC calendar; emits BTC then ETH, including abstention reasons."""
    for t in (start_hour, end_hour, available_at): timestamp(t)
    if set(markets) != set(SYMBOLS):
        raise PermissionError("Exactly BTCUSDT and ETHUSDT fixture series required")
    if start_hour >= end_hour or start_hour % HOUR or end_hour % HOUR:
        raise ValueError("Nonempty half-open hourly calendar required")
    for symbol in SYMBOLS:
        if markets[symbol].symbol != symbol:
            raise ValueError("Series symbol does not match dictionary key")
    result = []
    for boundary in range(start_hour, end_hour, HOUR):
        if boundary > available_at:
            break
        for symbol in SYMBOLS:
            result.append(Opportunity(feature_at(markets[symbol], boundary - 1)))
    return tuple(result)
