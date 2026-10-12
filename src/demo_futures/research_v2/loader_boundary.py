"""Inert synthetic contract integration; no loader or access authorization exists."""
from dataclasses import dataclass, field, fields
from decimal import Decimal

from ..data import Candle
from .config import HOUR, STEP, SYMBOLS
from .contracts import ContractResult, EvidenceIdentity, Readiness, result, valid_identity, valid_time
from .features import ObservedCandle, SyntheticSeries
from .funding_contracts import (
    CoverageRequirement, CoverageState, FundingClaim, ScheduleEvidence,
    SettlementObservation, aggregate_funding, assess_funding,
)
from .quality_contracts import CandleFlag, assess_candles
from .source_contracts import (
    AvailabilityMode, OriginalAvailability, PROTECTED, TARGET_END, TARGET_START,
    ScopedHashMetadata, SourceExpectation, SourceMetadata, assess_source,
)


@dataclass(frozen=True)
class BoundaryRequest:
    """Explicit synthetic scope. Bounds cover the entire declared context, not events."""
    symbols: tuple[str, ...]
    start: int
    end: int
    decision_time: int
    scope_id: str
    source_id: str
    revision: str
    mode: AvailabilityMode
    interval: str = "5m"
    evidence: str = "SYNTHETIC_ONLY"

    def __post_init__(self):
        # Do not coerce mutable containers or accept objects carrying capabilities.
        if (type(self.symbols) is not tuple or any(type(s) is not str for s in self.symbols)
                or any(type(v) is not int for v in (self.start, self.end, self.decision_time))
                or any(type(v) is not str for v in
                       (self.scope_id, self.source_id, self.revision, self.interval, self.evidence))
                or type(self.mode) is not AvailabilityMode):
            raise ValueError("Immutable primitive request fields and an explicit availability mode required")


@dataclass(frozen=True)
class SymbolDiagnostics:
    symbol: str
    source: ContractResult
    funding: ContractResult
    structure: ContractResult
    causal: ContractResult
    coverage_state: CoverageState
    flags: tuple[CandleFlag, ...] = ()
    original_availability: OriginalAvailability | None = None
    retrieved_at: int | None = None
    original_receipt: int | None = None
    market_realism: str = field(default="UNKNOWN / NOT CERTIFIED", init=False)

    def __post_init__(self):
        if (type(self.symbol) is not str or self.symbol not in SYMBOLS
                or any(type(v) is not ContractResult for v in
                       (self.source, self.funding, self.structure, self.causal))
                or type(self.coverage_state) is not CoverageState
                or type(self.flags) is not tuple
                or any(type(f) is not CandleFlag or type(f.index) is not int
                       or type(f.reason) is not str for f in self.flags)
                or (self.original_availability is not None
                    and type(self.original_availability) is not OriginalAvailability)
                or any(v is not None and not valid_time(v)
                       for v in (self.retrieved_at, self.original_receipt))):
            raise ValueError("Immutable scalar contract diagnostics only")


@dataclass(frozen=True)
class BoundaryDiagnostics:
    validation: ContractResult
    required_coverage: tuple[CoverageRequirement, ...] = ()
    symbols: tuple[SymbolDiagnostics, ...] = ()
    evidence: str = field(default="SYNTHETIC_ONLY", init=False)
    authority: str = field(default="INERT_VALIDATION_ONLY", init=False)
    historical_evidence: str = field(default="UNAUTHENTICATED / NOT VERIFIED", init=False)
    risk_clearance: str = field(default="NOT CLEARED", init=False)

    def __post_init__(self):
        if (type(self.validation) is not ContractResult
                or type(self.required_coverage) is not tuple
                or any(type(c) is not CoverageRequirement or type(c.symbol) is not str
                       or c.symbol not in SYMBOLS or not valid_time(c.start)
                       or not valid_time(c.end) or c.start >= c.end for c in self.required_coverage)
                or type(self.symbols) is not tuple
                or any(type(d) is not SymbolDiagnostics for d in self.symbols)):
            raise ValueError("Diagnostic results cannot carry payloads or capabilities")

    def __bool__(self):
        raise TypeError("Inspect diagnostics explicitly; validation never authorizes access")


# Explicitly supported, inert input types. Precomputed assessments/results and
# arbitrary dataclasses, handles, callbacks and containers are not evidence inputs.
_INPUT_TYPES = (
    BoundaryRequest, SourceMetadata, ScopedHashMetadata, EvidenceIdentity,
    FundingClaim, ScheduleEvidence, SettlementObservation, SyntheticSeries,
    ObservedCandle, Candle,
)
_ENUM_TYPES = (AvailabilityMode, OriginalAvailability, CoverageState)


def _plain_input(value, depth=0):
    if depth > 12:
        return False
    if value is None or type(value) in (str, int, float, bool, Decimal) + _ENUM_TYPES:
        return True
    if type(value) is tuple:
        return all(_plain_input(v, depth + 1) for v in value)
    if type(value) in _INPUT_TYPES:
        return all(_plain_input(getattr(value, f.name), depth + 1) for f in fields(value))
    return False


def validate_request(request):
    if type(request) is not BoundaryRequest or not _plain_input(request):
        return result(("INVALID_SCHEMA_OR_TIME",))
    if type(request.symbols) is not tuple or type(request.mode) is not AvailabilityMode:
        return result(("INVALID_SCHEMA_OR_TIME",))
    invalid = []
    if request.evidence != "SYNTHETIC_ONLY":
        invalid.append("UNAPPROVED_SCOPE")
    if not request.symbols or len(request.symbols) != len(set(request.symbols)):
        invalid.append("SOURCE_CONFLICT")
    if any(s not in SYMBOLS for s in request.symbols):
        invalid.append("WRONG_SYMBOL")
    if request.interval != "5m":
        invalid.append("WRONG_INTERVAL")
    if not all(valid_identity(v) for v in (request.scope_id, request.source_id, request.revision)):
        invalid.append("SOURCE_IDENTITY_MISMATCH")
    if not all(valid_time(v) for v in (request.start, request.end, request.decision_time)):
        return result(invalid + ["INVALID_SCHEMA_OR_TIME"])
    if any(request.start < end and request.end > start for start, end in PROTECTED):
        invalid.append("PROTECTED_PERIOD")
    if (not TARGET_START <= request.start < request.end <= TARGET_END
            or request.start % STEP or request.end % STEP):
        invalid.append("UNAUTHORIZED_DATES")
    if not request.start <= request.decision_time < request.end or (request.decision_time + 1) % HOUR:
        invalid.append("INVALID_SCHEMA_OR_TIME")
    return result(invalid)


def required_coverage(request):
    """One complete declared interval per requested symbol; no schedule inference."""
    if validate_request(request).status != Readiness.SUFFICIENT:
        raise ValueError("Invalid request cannot produce a coverage inventory")
    return tuple(CoverageRequirement(s, request.start, request.end)
                 for s in SYMBOLS if s in request.symbols)


def _combine(results):
    invalid = tuple(r for c in results if c.status == Readiness.INVALID for r in c.reasons)
    missing = tuple(r for c in results if c.status == Readiness.INSUFFICIENT for r in c.reasons)
    return result(invalid, missing)


def _index(rows, expected_type, request):
    if type(rows) is not tuple:
        return {}, result(("INVALID_SCHEMA_OR_TIME",))
    indexed, invalid = {}, []
    for row in rows:
        if type(row) is not expected_type or not _plain_input(row):
            invalid.append("INVALID_EVIDENCE")
            continue
        if type(row.symbol) is not str:
            invalid.append("INVALID_SCHEMA_OR_TIME")
        elif row.symbol not in SYMBOLS:
            invalid.append("WRONG_SYMBOL")
        elif row.symbol not in request.symbols:
            invalid.append("UNAPPROVED_SCOPE")
        elif row.symbol in indexed:
            # Exactly one complete interval per symbol, not a partition merger.
            invalid.append("SOURCE_CONFLICT")
        else:
            indexed[row.symbol] = row
    return indexed, result(invalid)


def _quality(request, candles):
    if candles is None:
        missing = result(insufficient=("CAUSAL_INPUT_INVALID",))
        return missing, missing, ()
    if candles.fixture_id != request.source_id:
        rejected = result(("SOURCE_IDENTITY_MISMATCH",))
        return rejected, rejected, ()
    try:
        supplied = candles.observations
        if supplied and supplied[0].candle.open_time != request.start:
            # A suffix cannot silently become a new ATR initialization prefix.
            gap = result(insufficient=("CANDLE_GAP",))
            return gap, gap, ()
        quality = assess_candles(candles, request.decision_time)
        structure = quality.structure
        if not supplied or supplied[-1].candle.close_time + 1 != request.end:
            structure = _combine((structure, result(insufficient=("CANDLE_GAP",))))
        if any(not request.start <= o.candle.open_time < request.end
               or o.candle.close_time >= request.end for o in supplied):
            structure = _combine((structure, result(("UNAUTHORIZED_DATES",))))
        return structure, quality.causal, quality.flags
    except (ValueError, TypeError, AttributeError, ArithmeticError):
        rejected = result(("INVALID_SCHEMA_OR_TIME",))
        return rejected, rejected, ()


def assess_boundary(request, *, sources=(), funding=(), series=()):
    """Revalidate raw invented contexts and return diagnostics without payloads."""
    scope = validate_request(request)
    if scope.status != Readiness.SUFFICIENT:
        return BoundaryDiagnostics(scope)
    inventory = required_coverage(request)
    source_rows, source_schema = _index(sources, SourceMetadata, request)
    funding_rows, funding_schema = _index(funding, FundingClaim, request)
    series_rows, series_schema = _index(series, SyntheticSeries, request)
    schemas = _combine((source_schema, funding_schema, series_schema))
    if schemas.status != Readiness.SUFFICIENT:
        return BoundaryDiagnostics(schemas, inventory)

    expected = SourceExpectation(request.scope_id, request.source_id, request.revision,
                                 request.start, request.end)
    diagnostics, assessments, validations = [], [], []
    for cell in inventory:
        symbol = cell.symbol
        metadata = source_rows.get(symbol)
        claim = funding_rows.get(symbol)
        candles = series_rows.get(symbol)
        availability, retrieved_at, original_receipt = None, None, None
        if metadata is None:
            source_result = result(insufficient=("SOURCE_IDENTITY_MISMATCH",))
        else:
            try:
                source_result = assess_source(metadata, expected)
                binding = result(("UNAPPROVED_SCOPE",)) if metadata.mode != request.mode else result()
                if metadata.decision_time != request.decision_time:
                    binding = _combine((binding, result(("INVALID_SCHEMA_OR_TIME",))))
                source_result = _combine((source_result, binding))
                if type(metadata.original_availability) is OriginalAvailability:
                    availability = metadata.original_availability
                if valid_time(metadata.retrieved_at):
                    retrieved_at = metadata.retrieved_at
                if valid_time(metadata.original_receipt):
                    original_receipt = metadata.original_receipt
            except (ValueError, TypeError, AttributeError, ArithmeticError):
                source_result = result(("INVALID_SCHEMA_OR_TIME",))

        coverage = CoverageState.UNKNOWN
        if claim is None:
            funding_result = result(insufficient=("FUNDING_COVERAGE_UNPROVEN",))
        else:
            invalid = []
            if (claim.start, claim.end) != (request.start, request.end):
                invalid.append("UNAUTHORIZED_DATES")
            if claim.source_id != request.source_id:
                invalid.append("SOURCE_IDENTITY_MISMATCH")
            if claim.revision != request.revision:
                invalid.append("REVISION_MISMATCH")
            try:
                assessment = assess_funding(claim)
                funding_result = _combine((assessment.validation, result(invalid)))
                if funding_result.status == Readiness.SUFFICIENT:
                    coverage = assessment.state
                assessments.append(assessment)
            except (ValueError, TypeError, AttributeError, ArithmeticError):
                funding_result = result(("INVALID_SCHEMA_OR_TIME",))

        structure, causal, flags = _quality(request, candles)
        diagnostics.append(SymbolDiagnostics(symbol, source_result, funding_result, structure,
                                             causal, coverage, flags, availability,
                                             retrieved_at, original_receipt))
        validations.extend((source_result, funding_result, structure, causal))
    validations.append(aggregate_funding(tuple(assessments), required=inventory))
    return BoundaryDiagnostics(_combine(validations), inventory, tuple(diagnostics))
