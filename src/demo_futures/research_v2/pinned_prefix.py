"""Strict, receipt-bound validation of one explicitly pinned synthetic ATR prefix."""
from dataclasses import dataclass, field

from .contracts import Readiness
from .features import FeatureRow, ObservedCandle, SyntheticSeries, feature_at
from .historical_scope import BoundaryCheck, _time, boundary_check, evidence_errors, grid, preflight, row_commitment
from .quality_contracts import CandleFlag, documentary_flags
from .source_contracts import OriginalAvailability


@dataclass(frozen=True, slots=True)
class PrefixDiagnostics:
    validation: BoundaryCheck
    features: FeatureRow | None = None
    flags: tuple[CandleFlag, ...] = ()
    missing_opens: tuple[int, ...] = ()
    next_open_feasibility: str = field(default="UNVERIFIED", init=False)

    def __bool__(self):
        raise TypeError("Inspect the synthetic prefix diagnostics explicitly")


def assess_pinned_prefix(scope, approval, observations, *, evaluated_at, retrieved_at):
    """Require the exact [P,T) slice and original evidence for every version."""
    access = preflight(scope, approval, evaluated_at=evaluated_at)
    if access.status is not Readiness.SUFFICIENT:
        return PrefixDiagnostics(access)
    boundary = scope.decision_time + 1
    if scope.end != boundary or scope.anchor_sha256 is not None:
        return PrefixDiagnostics(boundary_check(("UNAUTHORIZED_DATES",)))
    if not _time(retrieved_at) or not boundary <= retrieved_at <= evaluated_at:
        return PrefixDiagnostics(boundary_check(("INVALID_SCHEMA_OR_TIME",)))
    invalid, gaps = grid(scope, observations, approval.max_rows)
    if invalid:
        return PrefixDiagnostics(boundary_check(invalid))

    errors, missing, flags, received = [], [], [], []
    if gaps:
        missing.append("CANDLE_GAP")
    for index, observation in enumerate(observations):
        version = observation.version
        flags.extend(documentary_flags(index, version.candle))
        try:
            claim, proof = observation.original_availability, observation.proof
        except AttributeError:
            errors.append("INVALID_SCHEMA_OR_TIME")
            continue
        if type(claim) is not OriginalAvailability:
            errors.append("INVALID_SCHEMA_OR_TIME")
            continue
        proof_errors = () if proof is None else evidence_errors(
            proof, version, "ORIGINAL_ASOF_RECEIPT", row_commitment(version), retrieved_at)
        errors.extend(proof_errors)
        if claim is OriginalAvailability.VERIFIED:
            if proof is None or "INVALID_EVIDENCE" in proof_errors:
                errors.append("ORIGINAL_AVAILABILITY_UNSUPPORTED")
            elif not proof_errors:
                if proof.available_at > boundary:
                    missing.append("RECEIPT_LATE")
                else:
                    received.append(ObservedCandle(version.candle, proof.available_at))
        else:
            missing.append("ORIGINAL_RECEIPT_UNKNOWN")

    check = boundary_check(errors, missing)
    if check.status is not Readiness.SUFFICIENT:
        return PrefixDiagnostics(check, flags=tuple(flags), missing_opens=gaps)
    series = SyntheticSeries(scope.snapshot.symbol, tuple(received), scope.snapshot.snapshot_id)
    row = feature_at(series, scope.decision_time)
    if row.status != "READY":
        reason = "INSUFFICIENT_WARMUP" if row.status == "WARMUP" else "CAUSAL_INPUT_INVALID"
        check = boundary_check(missing=(reason,))
    return PrefixDiagnostics(check, row, tuple(flags))
