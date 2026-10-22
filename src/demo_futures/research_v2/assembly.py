"""Bounded feature-only synthetic assembly. No labels, I/O or training authority.

Wire v1: ASCII JSON, sorted keys, compact separators, no NaN. Integers use
decimal strings tagged i; floats use Python float.hex tagged f (signed zero
preserved); strings use tagged s and JSON escaping; tuples use tagged t.
Records use tagged r plus exact class name and dataclass field order. Only the
explicit types below are accepted. SHA256 commits this encoding, not authenticity.

Budgets count input nodes (records, tuples and scalar occurrences), string
codepoints, numeric representation characters, rows, observations and encoded
bytes. work = nodes + sum(source_observation_count + 1 per row) + 16 * training_count;
this conservatively accounts delegated linear feature/validation passes. Budget
checks precede delegation; limits are caller choices, not scientific thresholds
or OS memory/time guarantees. Existing already allocated input memory is excluded.
"""
from dataclasses import dataclass, field, fields
import hashlib
import json
import math

from ..data import Candle
from .config import FEATURES, HOUR, HORIZON, STEP, SYMBOLS
from .features import FeatureRow, ObservedCandle, SyntheticSeries, feature_at
from .validation import (DevelopmentWindow, TrainingReceipt, TransformContract,
                         IntervalRow, validate_partition, check_training_statistics,
                         apply_transform, RangeDecision, partition_reason)


@dataclass(frozen=True)
class Budgets:
    rows: int
    observations: int
    nodes: int
    text: int
    numeric_chars: int
    encoded_bytes: int
    work: int


@dataclass(frozen=True)
class Source:
    identity: str
    revision: str
    series: SyntheticSeries


@dataclass(frozen=True)
class Declaration:
    sources: tuple[Source, ...]
    rows: tuple[FeatureRow, ...]
    train_ids: tuple[str, ...]
    evaluation_ids: tuple[str, ...]
    window: DevelopmentWindow
    receipt: TrainingReceipt
    transform: TransformContract
    budgets: Budgets
    feature_names: tuple[str, ...] = FEATURES
    version: str = "v2-feature-assembly-1"


@dataclass(frozen=True)
class Payload:
    canonical: bytes
    sha256: str
    # Every scheduled row remains present, including causal/range exclusions.
    coverage: tuple[RangeDecision, ...]
    transformed: tuple[tuple[str, str, tuple | None], ...]
    usage: tuple[tuple[str, int], ...]
    partition_exclusions: tuple[tuple[str, str], ...]
    label_eligibility: str = field(default="UNVERIFIED", init=False)
    financial_label_validity: str = field(default="UNVERIFIED", init=False)
    historical_authenticity: str = field(default="UNVERIFIED", init=False)
    source_completeness: str = field(default="UNVERIFIED", init=False)
    training_readiness: str = field(default="UNVERIFIED", init=False)
    training_authorization: str = field(default="NOT AUTHORIZED", init=False)


@dataclass(frozen=True)
class Result:
    status: str
    reasons: tuple[str, ...]
    payload: Payload | None = None

    def __post_init__(self):
        if (self.status not in ("FEATURE_ASSEMBLY_VALID", "INVALID", "INSUFFICIENT")
                or (self.status == "FEATURE_ASSEMBLY_VALID") != (self.payload is not None)
                or (self.status == "FEATURE_ASSEMBLY_VALID") != (not self.reasons)):
            raise ValueError("Unsuccessful assembly cannot expose payload")

    def __bool__(self):
        raise TypeError("Assembly grants no training or execution authority")


class _Reject(ValueError):
    pass


_RECORDS = (Budgets, Source, Declaration, FeatureRow, ObservedCandle,
            SyntheticSeries, Candle, DevelopmentWindow, TrainingReceipt, TransformContract)


def assemble(declaration):
    """Capture exact typed inputs, verify causal reconstruction, then bind content.

    Partitions must explicitly account for every READY row; causal exclusions
    remain in inventory but cannot enter partitions. Evaluation inventory covers
    each BTC/ETH hourly slot in the declared window, including exclusions.
    Unknown future-label eligibility never changes that inventory/denominator.
    """
    def fail(reason, status="INVALID"):
        return Result(status, (reason,))

    if type(declaration) is not Declaration or type(getattr(declaration, "budgets", None)) is not Budgets:
        return fail("INVALID_SCHEMA")
    budget = declaration.budgets
    if any(type(getattr(budget, f.name, None)) is not int or getattr(budget, f.name) < 0
           for f in fields(budget)):
        return fail("INVALID_BUDGET")
    used = dict.fromkeys((f.name for f in fields(budget)), 0)

    def charge(name, count):
        used[name] += count
        if used[name] > getattr(budget, name):
            raise _Reject("RESOURCE_" + name.upper())

    def capture(value, depth=0):
        if depth > 16:
            raise _Reject("INVALID_DEPTH")
        charge("nodes", 1)
        charge("work", 1)
        kind = type(value)
        if value is None:
            return None, ["n"]
        if kind is str:
            charge("text", len(value))
            return value, ["s", value]
        if kind in (int, float):
            if kind is float:
                if not math.isfinite(value):
                    raise _Reject("INVALID_NUMBER")
                text = value.hex()
            else:
                # Check width before decimal conversion (including timestamps).
                if value.bit_length() > budget.numeric_chars * 4:
                    raise _Reject("RESOURCE_NUMERIC_CHARS")
                text = str(value)
            charge("numeric_chars", len(text))
            return value, ["i" if kind is int else "f", text]
        if kind is tuple:
            if len(value) > budget.nodes - used["nodes"]:
                raise _Reject("RESOURCE_NODES")
            pairs = tuple(capture(v, depth + 1) for v in value)
            return tuple(p[0] for p in pairs), ["t", [p[1] for p in pairs]]
        if kind in _RECORDS:
            pairs = tuple((f.name, capture(getattr(value, f.name), depth + 1)) for f in fields(value))
            # Reconstruct records to reject manually altered frozen instances.
            owned = kind(**{name: p[0] for name, p in pairs if next(f for f in fields(value) if f.name == name).init})
            return owned, ["r", kind.__name__, [[name, p[1]] for name, p in pairs]]
        raise _Reject("INVALID_TYPE")

    try:
        d, wire = capture(declaration)
        charge("rows", len(d.rows))
        if d.version != "v2-feature-assembly-1" or d.feature_names != FEATURES:
            return fail("SCHEMA_MISMATCH")
        if d.receipt.window != d.window:
            return fail("ASSEMBLY_RECEIPT_WINDOW_MISMATCH")
        if not d.rows or len(d.sources) != 2:
            return fail("MISSING_INVENTORY", "INSUFFICIENT")
        sources = {}
        for source in d.sources:
            if (any(type(v) is not str or not v for v in
                    (source.identity, source.revision, source.series.fixture_id))
                    or source.series.symbol in sources or source.series.evidence != "SYNTHETIC_ONLY"):
                return fail("SOURCE_CONFLICT")
            observations = source.series.observations
            charge("observations", len(observations))
            if any(observations[i].candle.open_time >= observations[i+1].candle.open_time
                   for i in range(len(observations)-1)):
                return fail("OBSERVATION_ORDER")
            sources[source.series.symbol] = source
        if tuple(sources) != SYMBOLS:
            return fail("SOURCE_ORDER_OR_SYMBOL")
        if tuple(sorted(d.rows, key=lambda r: (r.decision_time, r.symbol))) != d.rows:
            return fail("ROW_ORDER")
        by_id = {r.row_id: r for r in d.rows}
        if len(by_id) != len(d.rows):
            return fail("DUPLICATE_ID")
        if len(set(d.train_ids + d.evaluation_ids)) != len(d.train_ids + d.evaluation_ids):
            return fail("PARTITION_CONFLICT")
        cutoff = {r.row_id for r in d.rows if r.status == "READY"
                  and d.window.evaluation_start <= r.decision_time < d.window.evaluation_end
                  and partition_reason(IntervalRow(r.symbol, r.decision_time, r.decision_time+1+HORIZON),
                                       d.window, "development_evaluation") == "INCOMPLETE_EVALUATION_HORIZON"}
        if set(d.train_ids + d.evaluation_ids) != {r.row_id for r in d.rows if r.status == "READY"} - cutoff:
            return fail("PARTITION_INVENTORY")
        train = tuple(by_id[i] for i in d.train_ids)
        evaluation = tuple(by_id[i] for i in d.evaluation_ids)
        interval = lambda r: IntervalRow(r.symbol, r.decision_time, r.decision_time + 1 + HORIZON)
        validate_partition(tuple(map(interval, train)), tuple(map(interval, evaluation)), d.window)
        # Bound complete scheduled evaluation inventory before building a range.
        slots = (d.window.evaluation_end - d.window.evaluation_start) // HOUR
        if slots * 2 > budget.rows:
            raise _Reject("RESOURCE_ROWS")
        expected = {(s, t-1) for t in range(d.window.evaluation_start + HOUR,
                    d.window.evaluation_end + HOUR, HOUR) for s in SYMBOLS}
        actual = {(r.symbol, r.decision_time) for r in d.rows
                  if d.window.evaluation_start <= r.decision_time < d.window.evaluation_end}
        if actual != expected:
            return fail("MISSING_EVALUATION_SLOTS")
        for row in d.rows:
            observations = sources[row.symbol].series.observations
            charge("work", len(observations) + 1)
        charge("work", 16 * len(train))
        # Streaming encoder enforces the byte budget without constructing one huge string.
        chunks = []
        for chunk in json.JSONEncoder(ensure_ascii=True, separators=(",", ":"), sort_keys=True,
                                     allow_nan=False).iterencode(wire):
            encoded = chunk.encode("ascii")
            charge("encoded_bytes", len(encoded))
            chunks.append(encoded)
        canonical = b"".join(chunks)
        for row in d.rows:
            rebuilt = feature_at(sources[row.symbol].series, row.decision_time)
            if rebuilt != row:
                return fail("CAUSAL_CONTENT_MISMATCH")
            if row.reason == "NOT_AVAILABLE_AT_DECISION":
                return fail("UNAVAILABLE_OBSERVATIONS", "INSUFFICIENT")
        check = check_training_statistics(train, d.transform, d.receipt)
        if check.status != "CONSISTENT":
            return Result(check.status, check.reasons)
        transformed, coverage = [], []
        for row in d.rows:
            out = apply_transform(row, d.transform, d.receipt)
            transformed.append((row.row_id, out.status, out.values))
            coverage.append(RangeDecision(row.symbol, row.decision_time, row.status == "READY",
                                         out.status == "OUT_OF_RANGE", out.breaches))
        return Result("FEATURE_ASSEMBLY_VALID", (), Payload(canonical, hashlib.sha256(canonical).hexdigest(),
                      tuple(coverage), tuple(transformed), tuple(used.items()),
                      tuple((r.row_id, "INCOMPLETE_EVALUATION_HORIZON") for r in d.rows if r.row_id in cutoff)))
    except _Reject as error:
        return fail(str(error))
    except (ValueError, TypeError, AttributeError, KeyError, OverflowError, PermissionError):
        return fail("INVALID_INPUT")
