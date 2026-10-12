"""Inert coverage claims, deliberately disconnected from labels and the simulator."""
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from .config import SYMBOLS
from .contracts import (ContractResult, EvidenceIdentity, Readiness, result,
                        valid_evidence, valid_identity, valid_time)


class CoverageState(str, Enum):
    KNOWN_EVENTS = "KNOWN_EVENTS"
    KNOWN_NO_SETTLEMENT = "KNOWN_NO_SETTLEMENT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class SettlementObservation:
    timestamp: int
    rate: Decimal
    mark_price: Decimal | None
    timing_evidence: EvidenceIdentity | None
    mark_evidence: EvidenceIdentity | None


@dataclass(frozen=True)
class ScheduleEvidence:
    symbol: str
    start: int
    end: int
    identity: EvidenceIdentity | None
    expected_settlements: tuple[int, ...]
    complete: bool


@dataclass(frozen=True)
class FundingClaim:
    symbol: str
    start: int
    end: int
    source_id: str
    revision: str
    state: CoverageState
    observations: tuple[SettlementObservation, ...] = ()
    schedule: ScheduleEvidence | None = None
    evidence: str = "SYNTHETIC_ONLY"


@dataclass(frozen=True)
class FundingAssessment:
    validation: ContractResult
    state: CoverageState
    symbol: str | None = None
    start: int | None = None
    end: int | None = None

    def __post_init__(self):
        if (type(self.validation) is not ContractResult or type(self.state) is not CoverageState
                or ((self.validation.status == Readiness.SUFFICIENT) != (self.state != CoverageState.UNKNOWN))):
            raise ValueError("Known coverage requires sufficient synthetic evidence")


@dataclass(frozen=True)
class CoverageRequirement:
    symbol: str
    start: int
    end: int


def assess_funding(claim):
    """Reconcile exact supplied obligations. No cadence inference, I/O or zero override."""
    invalid, insufficient = [], []
    if type(claim) is not FundingClaim:
        return FundingAssessment(result(("INVALID_SCHEMA_OR_TIME",)), CoverageState.UNKNOWN)
    if claim.evidence != "SYNTHETIC_ONLY":
        invalid.append("UNAPPROVED_SCOPE")
    if claim.symbol not in SYMBOLS:
        invalid.append("WRONG_SYMBOL")
    if (not valid_time(claim.start) or not valid_time(claim.end) or claim.start >= claim.end
            or type(claim.observations) is not tuple
            or type(claim.state) is not CoverageState):
        return FundingAssessment(result(invalid + ["INVALID_SCHEMA_OR_TIME"]), CoverageState.UNKNOWN,
                                 claim.symbol, claim.start, claim.end)
    if not valid_identity(claim.source_id) or not valid_identity(claim.revision):
        invalid.append("SOURCE_IDENTITY_MISMATCH")
    if claim.state == CoverageState.UNKNOWN:
        insufficient.append("FUNDING_COVERAGE_UNPROVEN")
    observed_times = []
    for event in claim.observations:
        if (type(event) is not SettlementObservation or not valid_time(event.timestamp)
                or not isinstance(event.rate, Decimal) or not event.rate.is_finite()
                or (event.mark_price is not None and
                    (not isinstance(event.mark_price, Decimal) or not event.mark_price.is_finite()
                     or event.mark_price <= 0))):
            invalid.append("INVALID_SCHEMA_OR_TIME")
            continue
        observed_times.append(event.timestamp)
        if not claim.start <= event.timestamp < claim.end:
            invalid.append("UNEXPECTED_SETTLEMENT")
        for evidence, assertion, missing_reason in (
                (event.timing_evidence, "SETTLEMENT_TIME_AND_RATE", "FUNDING_TIME_UNCERTAIN"),
                (event.mark_evidence, "SETTLEMENT_MARK", "MARK_UNSUPPORTED")):
            if evidence is None:
                insufficient.append(missing_reason)
            elif not valid_evidence(evidence, assertion, claim.source_id, claim.revision):
                invalid.append("INVALID_EVIDENCE")
        if event.mark_price is None:
            insufficient.append("MARK_UNSUPPORTED")
    if observed_times != sorted(set(observed_times)):
        invalid.append("SOURCE_CONFLICT")
    schedule = claim.schedule
    supported = False
    if schedule is None:
        insufficient.append("FUNDING_COVERAGE_UNPROVEN")
    elif (type(schedule) is not ScheduleEvidence
          or type(schedule.complete) is not bool
          or not valid_time(schedule.start) or not valid_time(schedule.end)
          or type(schedule.expected_settlements) is not tuple
          or any(not valid_time(t) for t in schedule.expected_settlements)):
        invalid.append("INVALID_EVIDENCE")
    else:
        expected = schedule.expected_settlements
        if (schedule.symbol != claim.symbol or schedule.start != claim.start or schedule.end != claim.end
                or expected != tuple(sorted(set(expected)))
                or any(not claim.start <= t < claim.end for t in expected)):
            invalid.append("INVALID_EVIDENCE")
        assertion = "NO_SETTLEMENT" if claim.state == CoverageState.KNOWN_NO_SETTLEMENT else "SETTLEMENT_SCHEDULE"
        if schedule.identity is None:
            insufficient.append("FUNDING_COVERAGE_UNPROVEN")
        elif not valid_evidence(schedule.identity, assertion, claim.source_id, claim.revision):
            invalid.append("INVALID_EVIDENCE")
        else:
            supported = schedule.complete
        if not schedule.complete:
            insufficient.append("FUNDING_COVERAGE_UNPROVEN")
        if set(expected) - set(observed_times):
            insufficient.append("MISSING_EXPECTED_SETTLEMENT")
        if set(observed_times) - set(expected):
            invalid.append("UNEXPECTED_SETTLEMENT")
        if claim.state == CoverageState.KNOWN_NO_SETTLEMENT and (expected or claim.observations):
            invalid.append("SOURCE_CONFLICT")
    if claim.state == CoverageState.KNOWN_EVENTS and not claim.observations:
        insufficient.append("EMPTY_CONTEXT_UNSUPPORTED")
    if claim.state == CoverageState.KNOWN_NO_SETTLEMENT and claim.observations:
        invalid.append("SOURCE_CONFLICT")
    validation = result(invalid, insufficient)
    state = claim.state if supported and validation.status == Readiness.SUFFICIENT else CoverageState.UNKNOWN
    return FundingAssessment(validation, state, claim.symbol, claim.start, claim.end)


def aggregate_funding(assessments, *, required=()):
    """Every declared symbol/interval must be assessed; no implicit coverage union."""
    if (type(assessments) is not tuple or any(type(a) is not FundingAssessment for a in assessments)
            or type(required) is not tuple or any(type(r) is not CoverageRequirement for r in required)):
        return result(("INVALID_SCHEMA_OR_TIME",))
    invalid = [r for a in assessments if a.validation.status == Readiness.INVALID for r in a.validation.reasons]
    missing = [r for a in assessments if a.validation.status == Readiness.INSUFFICIENT for r in a.validation.reasons]
    keys, wanted = [], []
    for rows, target in ((assessments, keys), (required, wanted)):
        for row in rows:
            if (row.symbol not in SYMBOLS or not valid_time(row.start) or not valid_time(row.end)
                    or row.start >= row.end):
                invalid.append("INVALID_SCHEMA_OR_TIME")
            else:
                target.append((row.symbol, row.start, row.end))
    if len(keys) != len(set(keys)) or len(wanted) != len(set(wanted)):
        invalid.append("SOURCE_CONFLICT")
    if not required or set(wanted) - set(keys):
        missing.append("FUNDING_COVERAGE_UNPROVEN")
    if required and set(keys) - set(wanted):
        invalid.append("SOURCE_CONFLICT")
    return result(invalid, missing)
