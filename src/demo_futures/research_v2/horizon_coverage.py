"""Independent 48-bar synthetic coverage and deterministic commitment replay."""
from dataclasses import dataclass, field

from .config import HORIZON, STEP
from .contracts import Readiness
from .historical_scope import (
    BoundaryCheck, _time, boundary_check, commitment, evidence_errors, grid, preflight,
    row_commitment, valid_commitment, version_errors,
)
from .source_contracts import PROTECTED, TARGET_START


@dataclass(frozen=True, slots=True)
class HorizonDiagnostics:
    validation: BoundaryCheck
    missing_opens: tuple[int, ...] = ()
    sha256: str | None = None
    mature_at: int | None = None
    audit_basis: str = field(default="SYNTHETIC_PER_ROW_OBSERVATION", init=False)
    historical_evidence: str = field(default="UNAUTHENTICATED / NOT VERIFIED", init=False)

    def __bool__(self):
        raise TypeError("Synthetic coverage is never authorization or a financial label")


def assess_horizon(scope, approval, anchor, observations, *, evaluated_at, audit_cutoff):
    """Certify the exact [T,E) grid on invented inputs, independently of features."""
    access = preflight(scope, approval, evaluated_at=evaluated_at)
    if access.status is not Readiness.SUFFICIENT:
        return HorizonDiagnostics(access)
    start = scope.decision_time + 1
    end = start + HORIZON
    if any(start - STEP < right and start > left for left, right in PROTECTED):
        return HorizonDiagnostics(boundary_check(("PROTECTED_PERIOD",)))
    if (scope.start, scope.end) != (start, end) or start - STEP < TARGET_START:
        return HorizonDiagnostics(boundary_check(("UNAUTHORIZED_DATES",)))
    if not valid_commitment(scope.anchor_sha256):
        return HorizonDiagnostics(boundary_check(("SCOPED_HASH_INVALID",)))
    if not _time(audit_cutoff) or audit_cutoff > evaluated_at:
        return HorizonDiagnostics(boundary_check(("INVALID_SCHEMA_OR_TIME",)))

    anchor_errors = version_errors(anchor, scope.snapshot, start - STEP, start)
    grid_errors, gaps = grid(scope, observations, approval.max_rows)
    invalid = list(anchor_errors + grid_errors)
    missing = []
    if audit_cutoff < end:
        missing.append("HORIZON_NOT_MATURE")
    if invalid:
        return HorizonDiagnostics(boundary_check(invalid, missing))
    if row_commitment(anchor) != scope.anchor_sha256:
        invalid.append("SCOPED_HASH_INVALID")
    if gaps and audit_cutoff >= end:
        missing.append("CANDLE_GAP")

    witnessed = []
    mature_at = end
    for observation in observations:
        version = observation.version
        if version.row_id == anchor.row_id:
            invalid.append("SOURCE_CONFLICT")
        try:
            proof = observation.proof
        except AttributeError:
            invalid.append("INVALID_SCHEMA_OR_TIME")
            continue
        if proof is None:
            missing.append("HORIZON_OBSERVATION_UNPROVEN")
            continue
        digest = row_commitment(version)
        errors = evidence_errors(proof, version, "AUDIT_OBSERVATION", digest, evaluated_at)
        if errors:
            invalid.extend(errors)
            continue
        mature_at = max(mature_at, proof.available_at)
        if proof.available_at > audit_cutoff:
            missing.append("HORIZON_NOT_MATURE")
        witnessed.append((digest, proof.evidence_id, proof.assertion, proof.basis, proof.available_at))

    check = boundary_check(invalid, missing)
    if check.status is not Readiness.SUFFICIENT:
        return HorizonDiagnostics(check, missing_opens=gaps if audit_cutoff >= end else ())
    snapshot = scope.snapshot
    digest = commitment(("v2-synthetic-horizon-v1", scope.scope_id, approval.approval_id,
                         approval.basis, approval.issued_at, approval.expires_at, approval.max_rows,
                         snapshot.source_id, snapshot.snapshot_id, snapshot.revision, snapshot.symbol,
                         snapshot.interval, snapshot.source_ref, scope.mode.value, scope.projection,
                         scope.decision_time, start, end, audit_cutoff, scope.anchor_sha256, witnessed))
    return HorizonDiagnostics(check, sha256=digest, mature_at=mature_at)


def verify_horizon(expected_sha256, scope, approval, anchor, observations, *, evaluated_at, audit_cutoff):
    """Rebuild from raw declarations; refuse replay under any changed binding."""
    assessed = assess_horizon(scope, approval, anchor, observations,
                              evaluated_at=evaluated_at, audit_cutoff=audit_cutoff)
    if assessed.validation.status is not Readiness.SUFFICIENT:
        return assessed
    if not valid_commitment(expected_sha256) or expected_sha256 != assessed.sha256:
        return HorizonDiagnostics(boundary_check(("SCOPED_HASH_INVALID",)))
    return assessed
