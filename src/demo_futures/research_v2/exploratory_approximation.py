"""Inert completed-bar diagnostics on invented, explicitly approved prefixes."""
from dataclasses import dataclass, field, replace
from statistics import fmean

from .config import STEP, Recipe
from .contracts import Readiness
from .historical_scope import (
    BoundaryCheck, CandleScope, SliceApproval, VersionEvidence, VersionObservation,
    _time, boundary_check, commitment, evidence_errors, grid, preflight,
    row_commitment, valid_commitment,
)
from .quality_contracts import CandleFlag, documentary_flags
from .source_contracts import AvailabilityMode, OriginalAvailability


_MODE = AvailabilityMode.EXPLORATORY_CLOSED_BAR_APPROXIMATION
_BASIS = "PINNED_COMPLETED_BAR_ASSUMPTION"


@dataclass(frozen=True, slots=True)
class ApproximationApproval:
    """Invented grant with independent pins for ordered versions and evidence."""
    grant: SliceApproval
    version_sha256: tuple[str, ...]
    evidence_sha256: str


@dataclass(frozen=True, slots=True)
class ApproximationObservation:
    observation: VersionObservation
    material_correction: VersionEvidence | None = None


@dataclass(frozen=True, slots=True)
class ApproximationDiagnostics:
    validation: BoundaryCheck
    availability: tuple[OriginalAvailability, ...] = ()
    flags: tuple[CandleFlag, ...] = ()
    missing_opens: tuple[int, ...] = ()
    sha256: str | None = None
    mode: AvailabilityMode = field(default=_MODE, init=False)
    assumption_basis: str = field(default=_BASIS, init=False)
    next_open_feasibility: str = field(default="UNVERIFIED", init=False)
    historical_evidence: str = field(default="UNAUTHENTICATED / NOT VERIFIED", init=False)

    def __bool__(self):
        raise TypeError("An approximation diagnostic is never causal or execution authority")


def _access(scope, approval, evaluated_at):
    if type(scope) is not CandleScope:
        return boundary_check(("INVALID_SCHEMA_OR_TIME",))
    if scope.mode is not _MODE:
        return boundary_check(("UNAPPROVED_SCOPE",))
    grant = None
    if approval is not None:
        if type(approval) is not ApproximationApproval or type(approval.grant) is not SliceApproval:
            return boundary_check(("INVALID_SCHEMA_OR_TIME",))
        grant = approval.grant
        if type(grant.scope) is not CandleScope:
            return boundary_check(("INVALID_SCHEMA_OR_TIME",))
        if grant.scope.mode is not _MODE:
            return boundary_check(("APPROVAL_METADATA_MISMATCH",))
        grant = replace(grant, scope=replace(grant.scope, mode=AvailabilityMode.REQUIRE_VERIFIED_ASOF))
    # Reuse the strict preflight's structural and grant checks. Both original
    # declarations must name approximation before taking this private projection.
    # No strict receipt, feature or outcome consumer is invoked.
    return preflight(replace(scope, mode=AvailabilityMode.REQUIRE_VERIFIED_ASOF), grant,
                     evaluated_at=evaluated_at)


def assess_approximation(scope, approval, observations, *, evaluated_at, retrieved_at):
    """Validate exactly one authorized [P,T) view without making feature rows."""
    try:
        return _assess(scope, approval, observations, evaluated_at, retrieved_at)
    except AttributeError:
        return ApproximationDiagnostics(boundary_check(("INVALID_SCHEMA_OR_TIME",)))


def _assess(scope, approval, observations, evaluated_at, retrieved_at):
    access = _access(scope, approval, evaluated_at)
    if access.status is not Readiness.SUFFICIENT:
        return ApproximationDiagnostics(access)
    boundary = scope.decision_time + 1
    if scope.end != boundary or scope.anchor_sha256 is not None:
        return ApproximationDiagnostics(boundary_check(("UNAUTHORIZED_DATES",)))
    if not _time(retrieved_at) or not boundary <= retrieved_at <= evaluated_at:
        return ApproximationDiagnostics(boundary_check(("INVALID_SCHEMA_OR_TIME",)))
    pinned = approval.version_sha256
    if (type(pinned) is not tuple or len(pinned) != (boundary - scope.start) // STEP
            or any(not valid_commitment(value) for value in pinned)
            or not valid_commitment(approval.evidence_sha256)):
        return ApproximationDiagnostics(boundary_check(("SCOPED_HASH_INVALID",)))
    if type(observations) is not tuple:
        return ApproximationDiagnostics(boundary_check(("INVALID_SCHEMA_OR_TIME",)))
    if len(observations) > approval.grant.max_rows:
        return ApproximationDiagnostics(boundary_check(("QUERY_RESOURCE_LIMIT",)))
    if any(type(item) is not ApproximationObservation for item in observations):
        return ApproximationDiagnostics(boundary_check(("INVALID_SCHEMA_OR_TIME",)))
    rows = tuple(item.observation for item in observations)
    errors, gaps = grid(scope, rows, approval.grant.max_rows)
    if errors:
        return ApproximationDiagnostics(boundary_check(errors))
    if gaps:
        return ApproximationDiagnostics(boundary_check(missing=("CANDLE_GAP",)), missing_opens=gaps)
    digests = tuple(row_commitment(row.version) for row in rows)
    if digests != pinned:
        return ApproximationDiagnostics(boundary_check(("SCOPED_HASH_INVALID",)))

    invalid, missing, availability, evidence = [], [], [], []
    for item, digest in zip(observations, digests):
        row = item.observation
        if type(row.original_availability) is not OriginalAvailability:
            invalid.append("INVALID_SCHEMA_OR_TIME")
            continue
        times = {}
        for proof, assertion in ((row.proof, "ORIGINAL_ASOF_RECEIPT"),
                                 (item.material_correction, "MATERIAL_CORRECTION")):
            if proof is None:
                evidence.append(None)
            errors = () if proof is None else evidence_errors(proof, row.version, assertion, digest, retrieved_at)
            invalid.extend(errors)
            if (assertion == "ORIGINAL_ASOF_RECEIPT" and row.original_availability is OriginalAvailability.VERIFIED
                    and (proof is None or "INVALID_EVIDENCE" in errors)):
                invalid.append("ORIGINAL_AVAILABILITY_UNSUPPORTED")
            if proof is not None and not errors:
                times[assertion] = proof.available_at
                if proof.available_at > boundary:
                    missing.append("RECEIPT_LATE")
                evidence.append((proof.evidence_id, proof.assertion, proof.basis, proof.available_at))
        if times.get("ORIGINAL_ASOF_RECEIPT", retrieved_at) < times.get("MATERIAL_CORRECTION", 0):
            invalid.append("INVALID_EVIDENCE")
        availability.append(row.original_availability)

    if invalid or missing:
        return ApproximationDiagnostics(boundary_check(invalid, missing))
    evidence_sha256 = commitment(("v2-synthetic-closed-bar-evidence-v1",
                                  tuple(value.value for value in availability), evidence))
    if evidence_sha256 != approval.evidence_sha256:
        return ApproximationDiagnostics(boundary_check(("SCOPED_HASH_INVALID",)))
    candles = tuple(row.version.candle for row in rows)
    flags = tuple(flag for index, candle in enumerate(candles) for flag in documentary_flags(index, candle))
    if len(candles) < Recipe().warmup_bars:
        return ApproximationDiagnostics(boundary_check(missing=("INSUFFICIENT_WARMUP",)), flags=flags)
    decision = candles[-1]
    try:
        usable = decision.volume > 0 and decision.high > decision.low and fmean(
            candle.volume for candle in candles[-21:-1]) > 0
    except (ValueError, OverflowError):
        usable = False
    if not usable:
        return ApproximationDiagnostics(boundary_check(missing=("CAUSAL_INPUT_INVALID",)), flags=flags)

    snapshot = scope.snapshot
    grant = approval.grant
    sha256 = commitment(("v2-synthetic-closed-bar-approximation-v1", _MODE.value, _BASIS,
                         grant.approval_id, grant.issued_at, grant.expires_at, grant.max_rows,
                         scope.scope_id, snapshot.source_id, snapshot.snapshot_id, snapshot.revision,
                         snapshot.symbol, snapshot.interval, snapshot.source_ref, scope.projection,
                         scope.start, scope.end, scope.decision_time, retrieved_at, digests, evidence_sha256))
    return ApproximationDiagnostics(boundary_check(), tuple(availability), flags, sha256=sha256)


def verify_approximation(expected_sha256, scope, approval, observations, *, evaluated_at, retrieved_at):
    """Reassess invented inputs and compare the complete diagnostic binding."""
    diagnostic = assess_approximation(scope, approval, observations,
                                      evaluated_at=evaluated_at, retrieved_at=retrieved_at)
    if diagnostic.validation.status is not Readiness.SUFFICIENT:
        return diagnostic
    if not valid_commitment(expected_sha256) or expected_sha256 != diagnostic.sha256:
        return ApproximationDiagnostics(boundary_check(("SCOPED_HASH_INVALID",)))
    return diagnostic
