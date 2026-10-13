"""Synthetic approval consistency only. No trusted ledger, user grant or access token."""
from dataclasses import dataclass, field, fields

from .adapter_access_contract import validate_adapter_access
from .contracts import REASON_ORDER, Readiness, valid_identity


AUTHORIZATION_REASONS = REASON_ORDER + (
    "APPROVAL_MISSING", "APPROVAL_UNVERIFIED", "APPROVAL_IDENTITY_MISMATCH",
    "APPROVAL_SCOPE_MISMATCH", "APPROVAL_METADATA_MISMATCH",
    "APPROVAL_NOT_YET_VALID", "APPROVAL_EXPIRED", "APPROVAL_REVOKED",
    "APPROVAL_RESOURCE_INVALID",
)
_SCOPE = ("scope_id", "source_id", "snapshot_id", "symbols", "interval", "start", "end",
          "context_start", "context_end", "prefix_start", "prefix_end", "horizon_end",
          "decision_time", "projection", "prefix_basis_ref")
_INTEGERS = ("start", "end", "context_start", "context_end", "prefix_start", "prefix_end",
             "horizon_end", "decision_time", "schema_version", "issued_at", "expires_at", "max_rows")
MAX_DECLARED_ROWS = 4096  # Synthetic engineering bound; not a financial parameter.


def _plain_record(record):
    for f in fields(record):
        try:
            v = getattr(record, f.name)
        except AttributeError:
            return False
        if f.name in _INTEGERS:
            valid = type(v) is int
        elif f.name == "revoked":
            valid = type(v) is bool
        elif f.name in ("symbols", "projection"):
            valid = type(v) is tuple and all(type(x) is str for x in v)
        elif f.name in ("scoped_sha256", "provenance_refs"):
            width = 3 if f.name == "provenance_refs" else 2
            valid = (type(v) is tuple and all(type(x) is tuple and len(x) == width
                     and all(type(part) is str for part in x) for x in v))
        else:
            valid = type(v) is str
        if not valid:
            return False
    return True


@dataclass(frozen=True, slots=True)
class SyntheticApprovalRecord:
    """Independent input declaration, not authenticated independent authorization.

    record_id must match both approval_ref fields. Validity is [issued_at,
    expires_at), evaluated using the explicit caller-supplied UTC milliseconds.
    Revocation is a supplied invented state, not a queried revocation ledger.
    """
    record_id: str
    ledger_ref: str
    approval_basis: str
    ledger_basis: str
    scope_id: str
    source_id: str
    revision: str
    snapshot_id: str
    symbols: tuple[str, ...]
    interval: str
    start: int
    end: int
    context_start: int
    context_end: int
    prefix_start: int
    prefix_end: int
    horizon_end: int
    decision_time: int
    projection: tuple[str, ...]
    prefix_basis_ref: str
    mode: str
    schema_id: str
    schema_version: int
    scoped_sha256: tuple[tuple[str, str], ...]
    provenance_refs: tuple[tuple[str, str, str], ...]
    hash_algorithm: str
    hash_scope: str
    issued_at: int
    expires_at: int
    revoked: bool
    revocation_ref: str
    max_rows: int
    evidence: str = field(default="SYNTHETIC_ONLY", init=False)

    def __post_init__(self):
        if not _plain_record(self):
            raise ValueError("Exact immutable primitive approval declarations required")


@dataclass(frozen=True, slots=True)
class AuthorizationDiagnostics:
    status: Readiness
    reasons: tuple[str, ...] = ()
    evidence: str = field(default="SYNTHETIC_ONLY", init=False)
    authority: str = field(default="SYNTHETIC_CONSISTENCY_ONLY", init=False)
    actual_authorization: str = field(default="NOT VERIFIED", init=False)
    historical_evidence: str = field(default="UNAUTHENTICATED / NOT VERIFIED", init=False)
    risk_clearance: str = field(default="NOT CLEARED", init=False)

    def __post_init__(self):
        if (type(self.status) is not Readiness or type(self.reasons) is not tuple
                or any(type(r) is not str or r not in AUTHORIZATION_REASONS for r in self.reasons)
                or self.reasons != tuple(r for r in AUTHORIZATION_REASONS if r in self.reasons)
                or any(type(getattr(self, name)) is not str or getattr(self, name) != value for name, value in
                       (("evidence", "SYNTHETIC_ONLY"), ("authority", "SYNTHETIC_CONSISTENCY_ONLY"),
                        ("actual_authorization", "NOT VERIFIED"),
                        ("historical_evidence", "UNAUTHENTICATED / NOT VERIFIED"),
                        ("risk_clearance", "NOT CLEARED")))
                or ((self.status == Readiness.SUFFICIENT) != (not self.reasons))):
            raise ValueError("Ordered diagnostics only")

    def __bool__(self):
        raise TypeError("Synthetic approval consistency is never executable authority")


def _result(invalid=(), missing=()):
    reasons = tuple(r for r in AUTHORIZATION_REASONS if r in tuple(invalid) + tuple(missing))
    return AuthorizationDiagnostics(Readiness.INVALID if invalid else
        Readiness.INSUFFICIENT if missing else Readiness.SUFFICIENT, reasons)


def validate_authorization(record, spec, manifest, *, evaluated_at):
    """Revalidate raw inputs, without I/O or accepting successful result objects."""
    metadata = validate_adapter_access(spec, manifest)
    invalid = list(metadata.reasons) if metadata.status == Readiness.INVALID else []
    missing = list(metadata.reasons) if metadata.status == Readiness.INSUFFICIENT else []
    if type(evaluated_at) is not int or evaluated_at < 0:
        invalid.append("INVALID_SCHEMA_OR_TIME")
    if record is None:
        return _result(invalid, missing + ["APPROVAL_MISSING"])
    if type(record) is not SyntheticApprovalRecord or not _plain_record(record):
        return _result(invalid + ["INVALID_SCHEMA_OR_TIME"], missing)
    if record.evidence != "SYNTHETIC_ONLY":
        invalid.append("UNAPPROVED_SCOPE")
    if not record.record_id or not record.ledger_ref:
        missing.append("APPROVAL_MISSING")
    elif not valid_identity(record.record_id) or not valid_identity(record.ledger_ref):
        invalid.append("INVALID_EVIDENCE")
    for basis in (record.approval_basis, record.ledger_basis):
        if basis in ("", "UNKNOWN"):
            missing.append("APPROVAL_UNVERIFIED")
        elif basis != "SYNTHETIC_ASSERTION":
            invalid.append("INVALID_EVIDENCE")
    if record.issued_at < 0 or record.expires_at <= record.issued_at:
        invalid.append("INVALID_SCHEMA_OR_TIME")
    elif type(evaluated_at) is int and evaluated_at >= 0:
        if evaluated_at < record.issued_at:
            invalid.append("APPROVAL_NOT_YET_VALID")
        if evaluated_at >= record.expires_at:
            invalid.append("APPROVAL_EXPIRED")
    if record.revoked:
        invalid.append("APPROVAL_REVOKED")
        if not valid_identity(record.revocation_ref):
            invalid.append("INVALID_EVIDENCE")
    elif record.revocation_ref:
        invalid.append("APPROVAL_METADATA_MISMATCH")
    if not 1 <= record.max_rows <= MAX_DECLARED_ROWS:
        invalid.append("APPROVAL_RESOURCE_INVALID")
    # Never dereference malformed/foreign metadata even for comparison.
    if metadata.status != Readiness.INVALID:
        if record.record_id and record.record_id != spec.approval_ref:
            invalid.append("APPROVAL_IDENTITY_MISMATCH")
        if any(getattr(record, name) != getattr(spec, name) for name in _SCOPE):
            invalid.append("APPROVAL_SCOPE_MISMATCH")
        if record.revision != spec.revision:
            invalid.append("REVISION_MISMATCH")
        if record.mode != spec.mode:
            invalid.append("APPROVAL_METADATA_MISMATCH")
        if record.scoped_sha256 != spec.expected_scoped_sha256:
            invalid.append("SCOPED_HASH_INVALID")
        if not record.provenance_refs:
            missing.append("INVALID_EVIDENCE")
        elif record.provenance_refs != manifest.provenance_refs:
            invalid.append("INVALID_EVIDENCE")
        if any(getattr(record, name) != getattr(manifest, name) for name in
               ("schema_id", "schema_version", "hash_algorithm", "hash_scope")):
            invalid.append("APPROVAL_METADATA_MISMATCH")
    return _result(invalid, missing)
