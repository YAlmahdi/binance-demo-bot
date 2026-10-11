"""Frozen experiment-001 engineering recipe; standard library only."""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json


def timestamp(iso):
    value = datetime.fromisoformat(iso)
    if value.tzinfo is None or value.utcoffset().total_seconds() != 0:
        raise ValueError("Explicit UTC timestamp required")
    return int(value.timestamp() * 1000)


def utc(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


START = timestamp("2026-07-11T06:50:00+00:00")
DEV_END = timestamp("2026-08-31T00:00:00+00:00")
VALIDATION_END = timestamp("2026-09-15T00:00:00+00:00")
DATA_END = timestamp("2026-10-09T06:50:00+00:00")
STEP = 300_000
HORIZON = 48
BUFFER = 4 * 60 * 60 * 1000
SYMBOLS = ("BTCUSDT", "ETHUSDT")
FEATURE_NAMES = (
    "log_return_1", "log_return_3", "log_return_12", "log_return_48",
    "close_ema20", "ema20_ema50", "ema50_ema200", "rsi14_centered",
    "macd_close", "macd_hist_close", "atr14_close", "relative_volume_20",
    "range_close", "body_close", "symbol_is_ETH", "proposed_side_is_LONG",
)
FOLDS = tuple((timestamp(a), timestamp(b)) for a, b in (
    ("2026-08-01T00:00:00+00:00", "2026-08-11T00:00:00+00:00"),
    ("2026-08-11T00:00:00+00:00", "2026-08-21T00:00:00+00:00"),
    ("2026-08-21T00:00:00+00:00", "2026-08-31T00:00:00+00:00"),
))


@dataclass(frozen=True)
class ExperimentConfig:
    recipe: str = "phase4a-engineering-v001"
    admission_threshold: str = "0.65"
    horizon_bars: int = HORIZON
    buffer_ms: int = BUFFER
    seed: int = 42

    def __post_init__(self):
        if asdict(self) != dict(recipe="phase4a-engineering-v001", admission_threshold="0.65",
                                horizon_bars=48, buffer_ms=14_400_000, seed=42):
            raise ValueError("Approved recipe is frozen; a change needs new approval")

    def manifest(self):
        from ..risk import BacktestConfig, DEFAULT_SPECS
        return {**asdict(self), "feature_order": FEATURE_NAMES, "feature_type": "float64",
                "symbols": SYMBOLS, "interval": "5m", "start": START,
                "development_end": DEV_END, "selection_validation_end": VALIDATION_END,
                "final_end": DATA_END, "folds": FOLDS,
                "risk": asdict(BacktestConfig()),
                "contracts": {s: asdict(DEFAULT_SPECS[s]) for s in SYMBOLS},
                "gates": {"train": [200, 40, 0], "development_evaluation": [100, 20, 30],
                          "selection_validation_and_final": [100, 20, 60],
                          "future_economic": [50, 10]},
                "execution_enabled": False, "model_fitting_approved": False,
                "selection_validation_status": "LOCKED", "final_status": "LOCKED"}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      default=lambda v: str(v) if isinstance(v, Decimal) else _unsupported(v),
                      allow_nan=False)


def _unsupported(value):
    raise TypeError(f"Unsupported artifact type: {type(value).__name__}")


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def require_development(start, end):
    if type(start) is not int or type(end) is not int or not START <= start < end <= DEV_END:
        raise PermissionError("Only the approved development period may be interpreted")
