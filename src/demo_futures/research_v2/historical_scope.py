"""Inert synthetic candle scope, exact-version evidence and grid validation."""
from dataclasses import dataclass, field
import hashlib
import re

from ..data import Candle, validate_candles
from .artifacts import canonical_json
from .authorization_binding import AUTHORIZATION_REASONS, MAX_DECLARED_ROWS
from .config import HOUR, STEP, SYMBOLS
from .contracts import Readiness, valid_identity, valid_time
from .source_contracts import AvailabilityMode, OriginalAvailability, PROJECTION, PROTECTED, TARGET_END, TARGET_START


_REASONS = AUTHORIZATION_REASONS + (
    "QUERY_PROJECTION_MISMATCH", "QUERY_RESOURCE_LIMIT", "HORIZON_NOT_MATURE",
    "HORIZON_OBSERVATION_UNPROVEN",
)


@dataclass(frozen=True, slots=True)
class SnapshotIdentity:
    source_id: str
    snapshot_id: str
    revision: str
    symbol: str
    source_ref: str
    interval: str = "5m"
    evidence: str = field(default="SYNTHETIC_ONLY", init=False)


@dataclass(frozen=True, slots=True)
class CandleScope:
    scope_id: str
    snapshot: SnapshotIdentity
    start: int
    end: int
    decision_time: int
    projection: tuple[str, ...] = PROJECTION
    mode: AvailabilityMode = AvailabilityMode.REQUIRE_VERIFIED_ASOF
    anchor_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class SliceApproval:
    """Invented independent declaration for exactly one slice, not an access grant."""
    approval_id: str
    scope: CandleScope
    issued_at: int
    expires_at: int
    max_rows: int
    revoked: bool = False
    basis: str = "SYNTHETIC_ASSERTION"


@dataclass(frozen=True, slots=True)
class CandleVersion:
    snapshot: SnapshotIdentity
    row_id: str
    version_id: str
    candle: Candle


@dataclass(frozen=True, slots=True)
class VersionEvidence:
    evidence_id: str
    assertion: str
    row_sha256: str
    available_at: int
    basis: str = "SYNTHETIC_ASSERTION"


@dataclass(frozen=True, slots=True)
class VersionObservation:
    version: CandleVersion
    proof: VersionEvidence | None = None
    original_availability: OriginalAvailability = OriginalAvailability.UNKNOWN


@dataclass(frozen=True, slots=True)
class BoundaryCheck:
    status: Readiness
    reasons: tuple[str, ...] = ()
    evidence: str = field(default="SYNTHETIC_ONLY", init=False)
    authority: str = field(default="INERT_VALIDATION_ONLY", init=False)

    def __bool__(self):
        raise TypeError("Synthetic diagnostics never authorize access")


def boundary_check(invalid=(), missing=()):
    reasons = set(invalid) | set(missing)
    status = Readiness.INVALID if invalid else Readiness.INSUFFICIENT if missing else Readiness.SUFFICIENT
    return BoundaryCheck(status, tuple(reason for reason in _REASONS if reason in reasons))


def _identity(value):
    return type(value) is str and valid_identity(value)


def _time(value):
    return valid_time(value) and value.bit_length() <= 63


def valid_commitment(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _snapshot_errors(snapshot):
    if type(snapshot) is not SnapshotIdentity:
        return ("INVALID_SCHEMA_OR_TIME",)
    invalid = []
    if type(snapshot.evidence) is not str or snapshot.evidence != "SYNTHETIC_ONLY":
        invalid.append("UNAPPROVED_SCOPE")
    if not all(_identity(value) for value in (snapshot.source_id, snapshot.snapshot_id, snapshot.revision)):
        invalid.append("SOURCE_IDENTITY_MISMATCH")
    if not _identity(snapshot.source_ref):
        invalid.append("INVALID_EVIDENCE")
    if type(snapshot.symbol) is not str or snapshot.symbol not in SYMBOLS:
        invalid.append("WRONG_SYMBOL")
    if type(snapshot.interval) is not str or snapshot.interval != "5m":
        invalid.append("WRONG_INTERVAL")
    return tuple(invalid)


def _scope_errors(scope):
    if type(scope) is not CandleScope:
        return ("INVALID_SCHEMA_OR_TIME",)
    invalid = list(_snapshot_errors(scope.snapshot))
    if not _identity(scope.scope_id) or scope.mode is not AvailabilityMode.REQUIRE_VERIFIED_ASOF:
        invalid.append("UNAPPROVED_SCOPE")
    if (type(scope.projection) is not tuple or any(type(p) is not str for p in scope.projection)
            or scope.projection != PROJECTION):
        invalid.append("QUERY_PROJECTION_MISMATCH")
    if scope.anchor_sha256 is not None and not valid_commitment(scope.anchor_sha256):
        invalid.append("SCOPED_HASH_INVALID")
    if not all(_time(t) for t in (scope.start, scope.end, scope.decision_time)):
        return tuple(invalid) + ("INVALID_SCHEMA_OR_TIME",)
    if scope.start % STEP or scope.end % STEP or (scope.decision_time + 1) % HOUR:
        invalid.append("INVALID_SCHEMA_OR_TIME")
    if any(scope.start < right and scope.end > left for left, right in PROTECTED):
        invalid.append("PROTECTED_PERIOD")
    if not TARGET_START <= scope.start < scope.end <= TARGET_END:
        invalid.append("UNAUTHORIZED_DATES")
    return tuple(invalid)


def preflight(scope, approval, *, evaluated_at):
    """Validate declarations before inspecting rows or computing content digests."""
    try:
        return _preflight(scope, approval, evaluated_at)
    except AttributeError:
        return boundary_check(("INVALID_SCHEMA_OR_TIME",))


def _preflight(scope, approval, evaluated_at):
    invalid = list(_scope_errors(scope))
    if not _time(evaluated_at):
        invalid.append("INVALID_SCHEMA_OR_TIME")
    if approval is None:
        return boundary_check(invalid, ("APPROVAL_MISSING",))
    if type(approval) is not SliceApproval:
        return boundary_check(invalid + ["INVALID_SCHEMA_OR_TIME"])

    pinned_errors = _scope_errors(approval.scope)
    if not invalid and not pinned_errors and scope != approval.scope:
        invalid.append("APPROVAL_SCOPE_MISMATCH")
    invalid.extend(pinned_errors)
    if not _identity(approval.approval_id) or type(approval.basis) is not str:
        invalid.append("INVALID_EVIDENCE")
    missing = ()
    if type(approval.basis) is str and approval.basis in ("", "UNKNOWN"):
        missing = ("APPROVAL_UNVERIFIED",)
    elif type(approval.basis) is str and approval.basis != "SYNTHETIC_ASSERTION":
        invalid.append("INVALID_EVIDENCE")
    if type(approval.revoked) is not bool:
        invalid.append("INVALID_SCHEMA_OR_TIME")
    elif approval.revoked:
        invalid.append("APPROVAL_REVOKED")
    if not (_time(approval.issued_at) and _time(approval.expires_at) and approval.issued_at < approval.expires_at):
        invalid.append("INVALID_SCHEMA_OR_TIME")
    elif _time(evaluated_at):
        if evaluated_at < approval.issued_at:
            invalid.append("APPROVAL_NOT_YET_VALID")
        if evaluated_at >= approval.expires_at:
            invalid.append("APPROVAL_EXPIRED")
    if type(approval.max_rows) is not int or not 1 <= approval.max_rows <= MAX_DECLARED_ROWS:
        invalid.append("APPROVAL_RESOURCE_INVALID")
    elif not invalid and (scope.end - scope.start) // STEP > approval.max_rows:
        invalid.append("QUERY_RESOURCE_LIMIT")
    return boundary_check(invalid, missing)


def _candle_values(candle):
    if type(candle) is not Candle:
        raise ValueError("Exact candle record required")
    values = tuple(getattr(candle, name) for name in PROJECTION)
    if not all(_time(v) for v in (candle.open_time, candle.close_time, candle.trades)):
        raise ValueError("Invalid candle time or trade count")
    if any(type(v) not in (int, float) or (type(v) is int and v.bit_length() > 1024) for v in values):
        raise ValueError("Bounded primitive candle values required")
    validate_candles((candle,), "5m", candle.close_time + 1)
    return values


def version_errors(version, snapshot, start, end):
    try:
        if type(version) is not CandleVersion:
            return ("INVALID_SCHEMA_OR_TIME",)
        invalid = list(_snapshot_errors(version.snapshot))
        if invalid:
            return tuple(invalid)
        actual = version.snapshot
        if actual.revision != snapshot.revision:
            invalid.append("REVISION_MISMATCH")
        if (actual.source_id, actual.snapshot_id, actual.source_ref) != (
                snapshot.source_id, snapshot.snapshot_id, snapshot.source_ref):
            invalid.append("SOURCE_IDENTITY_MISMATCH")
        if actual.symbol != snapshot.symbol:
            invalid.append("WRONG_SYMBOL")
        if not _identity(version.row_id) or not _identity(version.version_id):
            invalid.append("INVALID_EVIDENCE")
        if invalid:
            return tuple(invalid)
        candle = version.candle
        if type(candle) is not Candle or not (_time(candle.open_time) and _time(candle.close_time)):
            return ("INVALID_SCHEMA_OR_TIME",)
        if candle.open_time % STEP or candle.close_time != candle.open_time + STEP - 1:
            return ("INVALID_SCHEMA_OR_TIME",)
        # Bounds are checked using timestamps before reading any candle values.
        if any(candle.open_time < right and candle.close_time >= left for left, right in PROTECTED):
            return ("PROTECTED_PERIOD",)
        if not start <= candle.open_time <= candle.close_time < end:
            return ("UNAUTHORIZED_DATES",)
        _candle_values(candle)
    except (AttributeError, ArithmeticError, TypeError, ValueError):
        return ("INVALID_SCHEMA_OR_TIME",)
    return ()


def commitment(value):
    return hashlib.sha256(canonical_json(value).encode("ascii")).hexdigest()


def row_commitment(version):
    """Commit to an invented version's exact content, including numeric types."""
    if type(version) is not CandleVersion or version_errors(
            version, getattr(version, "snapshot", None), TARGET_START, TARGET_END):
        raise ValueError("Valid in-envelope synthetic candle version required")
    snapshot = version.snapshot
    values = tuple(value.hex() if type(value) is float else value for value in _candle_values(version.candle))
    return commitment(("v2-synthetic-candle-version-v1", snapshot.source_id, snapshot.snapshot_id,
                       snapshot.revision, snapshot.symbol, snapshot.interval, snapshot.source_ref,
                       PROJECTION, version.row_id, version.version_id, values))


def grid(scope, observations, max_rows):
    """Inspect a bounded, materialized slice without ordering, coercion or repair."""
    if type(observations) is not tuple:
        return ("INVALID_SCHEMA_OR_TIME",), ()
    if len(observations) > max_rows:
        return ("QUERY_RESOURCE_LIMIT",), ()
    invalid, seen, opens = [], set(), set()
    previous = -1
    for observation in observations:
        try:
            if type(observation) is not VersionObservation:
                invalid.append("INVALID_SCHEMA_OR_TIME")
                continue
            version = observation.version
        except AttributeError:
            invalid.append("INVALID_SCHEMA_OR_TIME")
            continue
        errors = version_errors(version, scope.snapshot, scope.start, scope.end)
        invalid.extend(errors)
        if errors:
            continue
        opened = version.candle.open_time
        if opened <= previous or version.row_id in seen:
            invalid.append("SOURCE_CONFLICT")
        previous = opened
        seen.add(version.row_id)
        opens.add(opened)
    if invalid:
        return tuple(invalid), ()
    return (), tuple(t for t in range(scope.start, scope.end, STEP) if t not in opens)


def evidence_errors(proof, version, assertion, digest, latest):
    try:
        if (type(proof) is not VersionEvidence or not _identity(proof.evidence_id)
                or type(proof.assertion) is not str or proof.assertion != assertion
                or type(proof.basis) is not str or proof.basis != "SYNTHETIC_ASSERTION"
                or not valid_commitment(proof.row_sha256) or proof.row_sha256 != digest):
            return ("INVALID_EVIDENCE",)
        if not _time(proof.available_at) or not version.candle.close_time + 1 <= proof.available_at <= latest:
            return ("INVALID_SCHEMA_OR_TIME",)
    except AttributeError:
        return ("INVALID_EVIDENCE",)
    return ()
