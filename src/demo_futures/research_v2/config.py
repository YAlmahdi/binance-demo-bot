"""Immutable first V2 recipe; future symbols require a different approved recipe."""
from dataclasses import dataclass, field
from typing import Protocol
from ..risk import BacktestConfig

STEP = 300_000
HOUR = 3_600_000
HORIZON = 48 * STEP
SYMBOLS = ("BTCUSDT", "ETHUSDT")
FEATURES = ("log_return_1", "log_return_12", "log_return_48",
            "volatility_48", "relative_atr_14", "relative_range",
            "relative_body", "relative_volume", "is_eth")
RECIPE_VERSION = "v2-synthetic-foundation-v001"

def timestamp(value):
    if type(value) is not int or value < 0:
        raise ValueError("Nonnegative integer UTC milliseconds required")
    return value

def require_symbol(symbol):
    if symbol not in SYMBOLS:
        raise PermissionError("Inactive symbol: recipe permits BTCUSDT/ETHUSDT only")
    return symbol

class SymbolEncoder(Protocol):
    """Interface for a future separately versioned encoding, not an activation hook."""
    def encode(self, symbol: str) -> int: ...

@dataclass(frozen=True)
class BtcEthEncoder:
    def encode(self, symbol):
        require_symbol(symbol)
        return int(symbol == "ETHUSDT")

@dataclass(frozen=True)
class Recipe:
    version: str = field(default=RECIPE_VERSION, init=False)
    symbols: tuple = field(default=SYMBOLS, init=False)
    feature_names: tuple = field(default=FEATURES, init=False)
    warmup_bars: int = field(default=200, init=False)
    horizon_ms: int = field(default=HORIZON, init=False)
    buffer_ms: int = field(default=HORIZON, init=False)
    evidence: str = field(default="SYNTHETIC_ONLY", init=False)
    risk_clearance: str = field(default="NOT CLEARED", init=False)

def frozen_financial_config():
    """Use V1 defaults unchanged; fail rather than silently adopt financial drift."""
    config = BacktestConfig()
    expected = ("10000", "0.005", "2", "0.02", "0.0005", "0.0002",
                "0.001", "2", "3")
    names = ("initial_equity", "risk_fraction", "leverage", "daily_loss_fraction",
             "fee_rate", "slippage_rate", "funding_reserve_rate", "stop_atr", "target_atr")
    from decimal import Decimal
    if (tuple(getattr(config, n) for n in names) != tuple(map(Decimal, expected))
            or config.max_positions != 1 or config.max_holding_bars != 48
            or config.allow_missing_funding):
        raise ValueError("Frozen financial contract changed; review required")
    return config
