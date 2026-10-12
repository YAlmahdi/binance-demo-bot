"""Synthetic documentary quality channels; no repairs or new eligibility filters."""
from dataclasses import dataclass, field
from ..data import Candle, DataQualityError, validate_candles
from .config import HOUR, STEP
from .contracts import ContractResult, result, valid_time
from .features import SyntheticSeries, feature_at


@dataclass(frozen=True)
class CandleFlag:
    index: int
    reason: str


@dataclass(frozen=True)
class QualityAssessment:
    observations: tuple
    structure: ContractResult
    flags: tuple[CandleFlag, ...]
    causal: ContractResult
    existing_feature_status: str
    existing_feature_reason: str
    market_realism: str = field(default="UNKNOWN / NOT CERTIFIED", init=False)


def assess_candles(series, decision_time):
    """Quality over supplied observations; causal channel uses frozen feature_at only."""
    if type(series) is not SyntheticSeries or series.evidence != "SYNTHETIC_ONLY":
        rejected = result(("UNAPPROVED_SCOPE",))
        return QualityAssessment((), rejected, (), rejected, "DATA_QUALITY", "CAUSAL_INPUT_INVALID")
    if not valid_time(decision_time) or (decision_time + 1) % HOUR:
        rejected = result(("INVALID_SCHEMA_OR_TIME",))
        return QualityAssessment(series.observations, rejected, (), rejected, "DATA_QUALITY", "CAUSAL_INPUT_INVALID")
    invalid, missing, flags = [], [], []
    previous = None
    for i, observed in enumerate(series.observations):
        c = observed.candle
        try:
            if (type(c) is not Candle or not valid_time(c.open_time) or not valid_time(c.close_time)
                    or type(c.trades) is not int
                    or any(isinstance(getattr(c, n), bool) for n in
                           ("open", "high", "low", "close", "volume", "quote_volume"))):
                raise DataQualityError("Invalid types")
            validate_candles((c,), "5m", c.close_time + 1)
        except (DataQualityError, ValueError, TypeError, OverflowError):
            invalid.append("INVALID_SCHEMA_OR_TIME")
            flags.append(CandleFlag(i, "STRUCTURALLY_INVALID"))
            continue
        if previous is not None:
            if c.open_time <= previous:
                invalid.append("SOURCE_CONFLICT")
                flags.append(CandleFlag(i, "DUPLICATE_OR_UNORDERED"))
            elif c.open_time - previous != STEP:
                missing.append("CANDLE_GAP")
                flags.append(CandleFlag(i, "DISCONTINUOUS"))
        previous = c.open_time
        if c.volume == 0:
            flags.append(CandleFlag(i, "ZERO_VOLUME_REVIEW"))
        if c.high == c.low:
            flags.append(CandleFlag(i, "FLAT_BAR_REVIEW"))
        if (c.high - c.low) / c.close > .05:
            flags.append(CandleFlag(i, "RANGE_GT_5_PERCENT_REVIEW_ONLY"))
    if not series.observations:
        missing.append("CANDLE_GAP")
    try:
        feature = feature_at(series, decision_time)
        status, reason = feature.status, feature.reason
    except (ValueError, TypeError, OverflowError):
        status, reason = "DATA_QUALITY", "CAUSAL_INPUT_INVALID"
    if status == "READY":
        causal = result()
    elif status == "WARMUP":
        causal = result(insufficient=("INSUFFICIENT_WARMUP",))
    else:
        code = {"NOT_AVAILABLE_AT_DECISION": "RECEIPT_LATE",
                "INVALID_OR_GAPPED_PREFIX": "CANDLE_GAP",
                "MISSING_DECISION_BAR": "CANDLE_GAP"}.get(reason, "CAUSAL_INPUT_INVALID")
        causal = result(insufficient=(code,))
    return QualityAssessment(series.observations, result(invalid, missing), tuple(flags), causal, status, reason)
