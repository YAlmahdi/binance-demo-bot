"""Pure synthetic validation vocabulary; results never grant data/research access."""
from dataclasses import dataclass, field
from enum import Enum
import re


class Readiness(str, Enum):
    SUFFICIENT = "SUFFICIENT"
    INSUFFICIENT = "INSUFFICIENT"
    INVALID = "INVALID"


# Fixed ordering makes multi-cause rejection independent of discovery order.
REASON_ORDER = (
    "INVALID_SCHEMA_OR_TIME", "UNAPPROVED_SCOPE", "PROTECTED_PERIOD",
    "WRONG_SYMBOL", "WRONG_INTERVAL", "UNAUTHORIZED_DATES",
    "SOURCE_IDENTITY_MISMATCH", "SOURCE_CONFLICT", "INVALID_EVIDENCE",
    "REVISION_MISMATCH", "SCOPED_HASH_INVALID",
    "ORIGINAL_AVAILABILITY_UNSUPPORTED", "ORIGINAL_RECEIPT_UNKNOWN", "RECEIPT_LATE",
    "FUNDING_COVERAGE_UNPROVEN", "MISSING_EXPECTED_SETTLEMENT",
    "UNEXPECTED_SETTLEMENT", "FUNDING_TIME_UNCERTAIN", "MARK_UNSUPPORTED",
    "EMPTY_CONTEXT_UNSUPPORTED", "CANDLE_GAP", "INSUFFICIENT_WARMUP",
    "CAUSAL_INPUT_INVALID",
)


@dataclass(frozen=True)
class ContractResult:
    status: Readiness
    reasons: tuple[str, ...] = ()
    evidence: str = field(default="SYNTHETIC_ONLY", init=False)
    authority: str = field(default="INERT_VALIDATION_ONLY", init=False)

    def __post_init__(self):
        object.__setattr__(self, "status", Readiness(self.status))
        if any(r not in REASON_ORDER for r in self.reasons):
            raise ValueError("Unknown contract rejection reason")
        reasons = tuple(r for r in REASON_ORDER if r in self.reasons)
        object.__setattr__(self, "reasons", reasons)
        if (self.status == Readiness.SUFFICIENT) != (not reasons):
            raise ValueError("Sufficient validation has no rejection reasons")


def result(invalid=(), insufficient=()):
    reasons = tuple(invalid) + tuple(insufficient)
    return ContractResult(Readiness.INVALID if invalid else
                          Readiness.INSUFFICIENT if insufficient else Readiness.SUFFICIENT,
                          reasons)


def valid_time(value):
    return type(value) is int and value >= 0


def valid_identity(value):
    # Identifiers, not URLs, file paths, credentials or executable references.
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value) is not None


@dataclass(frozen=True)
class EvidenceIdentity:
    identity: str
    source_id: str
    revision: str
    assertion: str
    basis: str = "SYNTHETIC_ASSERTION"


def valid_evidence(value, assertion, source_id=None, revision=None):
    """Check internal identity binding only, never independent real-world truth."""
    return (type(value) is EvidenceIdentity
            and all(valid_identity(v) for v in (value.identity, value.source_id, value.revision))
            and value.basis == "SYNTHETIC_ASSERTION" and value.assertion == assertion
            and (source_id is None or value.source_id == source_id)
            and (revision is None or value.revision == revision))
