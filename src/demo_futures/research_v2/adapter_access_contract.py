"""Inert synthetic metadata declarations, never a historical adapter or access token.

UTC times are integer milliseconds. All intervals are half-open; context includes
the explicitly declared prefix and horizon. No content hashes are computed here.
"""
from dataclasses import dataclass, field, fields

from .config import HOUR, STEP, SYMBOLS
from .contracts import EvidenceIdentity, REASON_ORDER, Readiness, result, valid_identity
from .source_contracts import (
    AvailabilityMode, OriginalAvailability, PROJECTION, PROTECTED, TARGET_END,
    TARGET_START, ScopedHashMetadata, SourceExpectation, SourceMetadata, assess_source,
)
import re


SCHEMA_ID = "V2_SYNTHETIC_CANDLE_METADATA"
SCHEMA_VERSION = 1
PROVENANCE_ASSERTIONS = ("SOURCE_IDENTITY", "APPROVED_SYNTHETIC_SCOPE", "PINNED_SNAPSHOT")
_TIMES = ("start", "end", "context_start", "context_end", "prefix_start",
          "prefix_end", "horizon_end", "decision_time", "retrieved_at", "schema_version")
_BINDING = ("scope_id", "source_id", "revision", "snapshot_id", "symbols", "interval",
            "start", "end", "context_start", "context_end", "prefix_start", "prefix_end",
            "horizon_end", "decision_time", "projection", "approval_ref", "prefix_basis_ref")


def _shape(value):
    """Only exact builtins; no coercion, foreign objects, mutable or nested payloads."""
    for f in fields(value):
        try:
            v = getattr(value, f.name)
        except AttributeError:
            return False
        if f.name in _TIMES:
            ok = type(v) is int  # bool and int subclasses are intentionally refused.
        elif f.name == "original_receipt":
            ok = v is None or type(v) is int
        elif f.name in ("symbols", "projection"):
            ok = type(v) is tuple and all(type(x) is str for x in v)
        elif f.name in ("expected_scoped_sha256", "scoped_sha256", "provenance_refs"):
            width = 3 if f.name == "provenance_refs" else 2
            ok = (type(v) is tuple and all(type(x) is tuple and len(x) == width
                  and all(type(part) is str for part in x) for x in v))
        else:
            ok = type(v) is str
        if not ok:
            return False
    return True


@dataclass(frozen=True, slots=True)
class _DeclaredScope:
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
    approval_ref: str
    prefix_basis_ref: str

    def __post_init__(self):
        if not _shape(self):
            raise ValueError("Exact immutable primitive metadata required")


@dataclass(frozen=True, slots=True)
class AdapterAccessSpec(_DeclaredScope):
    """Explicit synthetic declaration; approval_ref is an identifier, not authority.

    Prefix=[prefix_start,start), decisions=[start,end), horizon=[end,horizon_end).
    The complete authorized context is [context_start,context_end). These declare
    scope only, not a prefix length convention or a financial-label horizon.
    """
    mode: str
    expected_scoped_sha256: tuple[tuple[str, str], ...]
    evidence: str = field(default="SYNTHETIC_ONLY", init=False)


@dataclass(frozen=True, slots=True)
class PinnedSnapshotManifest(_DeclaredScope):
    """Supplied digest/evidence declarations only; no filename or storage handle.

    provenance_refs contains (assertion, identifier, basis) triples. Supported
    basis SYNTHETIC_ASSERTION certifies internal invented binding only.
    """
    schema_id: str
    schema_version: int
    scoped_sha256: tuple[tuple[str, str], ...]
    provenance_refs: tuple[tuple[str, str, str], ...]
    approval_basis: str
    retrieved_at: int
    original_availability: str
    original_receipt: int | None = None
    availability_ref: str = ""
    hash_algorithm: str = "sha256"
    hash_scope: str = "SYNTHETIC_ROWS_ONLY"
    evidence: str = field(default="SYNTHETIC_ONLY", init=False)


@dataclass(frozen=True, slots=True)
class AdapterDiagnostics:
    status: Readiness
    reasons: tuple[str, ...] = ()
    evidence: str = field(default="SYNTHETIC_ONLY", init=False)
    authority: str = field(default="INERT_VALIDATION_ONLY", init=False)
    historical_evidence: str = field(default="UNAUTHENTICATED / NOT VERIFIED", init=False)
    risk_clearance: str = field(default="NOT CLEARED", init=False)

    def __post_init__(self):
        if (type(self.status) is not Readiness or type(self.reasons) is not tuple
                or any(type(r) is not str or r not in REASON_ORDER for r in self.reasons)
                or self.reasons != tuple(r for r in REASON_ORDER if r in self.reasons)
                or ((self.status == Readiness.SUFFICIENT) != (not self.reasons))):
            raise ValueError("Ordered immutable diagnostics required")

    def __bool__(self):
        raise TypeError("Metadata consistency never authorizes data or research access")


def _diagnostics(invalid=(), insufficient=()):
    checked = result(invalid, insufficient)
    return AdapterDiagnostics(checked.status, checked.reasons)


def _hashes_valid(rows, symbols):
    return (tuple(s for s, _ in rows) == tuple(s for s in SYMBOLS if s in symbols)
            and all(re.fullmatch(r"[0-9a-f]{64}", h) is not None for _, h in rows))


def validate_adapter_access(spec, manifest):
    """Validate declarations only. No I/O, SQL, content hashing or activation.

    Revalidate shapes even after frozen-dataclass tampering. INVALID dominates
    INSUFFICIENT; all reasons use the existing deterministic contract vocabulary.
    """
    if (type(spec) is not AdapterAccessSpec or type(manifest) is not PinnedSnapshotManifest
            or not _shape(spec) or not _shape(manifest)):
        return _diagnostics(("INVALID_SCHEMA_OR_TIME",))
    s, m = spec, manifest
    invalid, missing = [], []
    for v in (s, m):
        if v.evidence != "SYNTHETIC_ONLY":
            invalid.append("UNAPPROVED_SCOPE")
        if not all(valid_identity(getattr(v, name)) for name in
                   ("scope_id", "source_id", "revision", "snapshot_id")):
            invalid.append("SOURCE_IDENTITY_MISMATCH")
        if not v.symbols or len(v.symbols) != len(set(v.symbols)):
            invalid.append("SOURCE_CONFLICT")
        if any(symbol not in SYMBOLS for symbol in v.symbols):
            invalid.append("WRONG_SYMBOL")
        if v.interval != "5m":
            invalid.append("WRONG_INTERVAL")
        if v.projection != PROJECTION:
            invalid.append("INVALID_SCHEMA_OR_TIME")
        for name in ("approval_ref", "prefix_basis_ref"):
            ref = getattr(v, name)
            if not ref:
                missing.append("INVALID_EVIDENCE")
            elif not valid_identity(ref):
                invalid.append("INVALID_EVIDENCE")
        bounds = (v.start, v.end, v.context_start, v.context_end,
                  v.prefix_start, v.prefix_end, v.horizon_end)
        if any(t < 0 or t % STEP for t in bounds):
            invalid.append("INVALID_SCHEMA_OR_TIME")
        # Every declared span is checked independently, not just decision dates.
        spans = ((v.start, v.end), (v.context_start, v.context_end),
                 (v.prefix_start, v.prefix_end), (v.end, v.horizon_end))
        if any(a < p_end and b > p_start for a, b in spans for p_start, p_end in PROTECTED):
            invalid.append("PROTECTED_PERIOD")
        if (any(not TARGET_START <= t <= TARGET_END for t in bounds)
                or not (v.context_start == v.prefix_start < v.prefix_end == v.start
                        < v.end <= v.horizon_end == v.context_end)):
            invalid.append("UNAUTHORIZED_DATES")
        if not v.start <= v.decision_time < v.end or (v.decision_time + 1) % HOUR:
            invalid.append("INVALID_SCHEMA_OR_TIME")
    if s.revision != m.revision:
        invalid.append("REVISION_MISMATCH")
    if any(getattr(s, name) != getattr(m, name) for name in _BINDING if name != "revision"):
        invalid.append("SOURCE_IDENTITY_MISMATCH")
    if m.schema_id != SCHEMA_ID or m.schema_version != SCHEMA_VERSION:
        invalid.append("INVALID_SCHEMA_OR_TIME")
    if (not _hashes_valid(s.expected_scoped_sha256, s.symbols)
            or not _hashes_valid(m.scoped_sha256, m.symbols)
            or s.expected_scoped_sha256 != m.scoped_sha256
            or m.hash_algorithm != "sha256" or m.hash_scope != "SYNTHETIC_ROWS_ONLY"):
        invalid.append("SCOPED_HASH_INVALID")
    if m.approval_basis == "UNKNOWN":
        missing.append("INVALID_EVIDENCE")
    elif m.approval_basis != "SYNTHETIC_ASSERTION":
        invalid.append("INVALID_EVIDENCE")
    refs = {}
    for assertion, identity, basis in m.provenance_refs:
        if assertion not in PROVENANCE_ASSERTIONS or assertion in refs or not valid_identity(identity):
            invalid.append("INVALID_EVIDENCE")
        elif basis == "UNKNOWN":
            missing.append("INVALID_EVIDENCE")
        elif basis != "SYNTHETIC_ASSERTION":
            invalid.append("INVALID_EVIDENCE")
        else:
            refs[assertion] = identity
    if set(refs) != set(PROVENANCE_ASSERTIONS):
        missing.append("INVALID_EVIDENCE")
    if s.mode not in tuple(v.value for v in AvailabilityMode):
        invalid.append("INVALID_SCHEMA_OR_TIME")
    if m.original_availability not in tuple(v.value for v in OriginalAvailability):
        invalid.append("ORIGINAL_AVAILABILITY_UNSUPPORTED")
    if m.retrieved_at < m.context_end:
        invalid.append("INVALID_SCHEMA_OR_TIME")
    if (m.original_receipt is not None and
            not m.decision_time + 1 <= m.original_receipt <= m.retrieved_at):
        invalid.append("INVALID_SCHEMA_OR_TIME")
    if m.availability_ref and not valid_identity(m.availability_ref):
        invalid.append("INVALID_EVIDENCE")
    # Reuse source-contract availability/receipt semantics after shape/scope gates.
    # These invented references do not authenticate their real-world assertions.
    if not invalid and not missing:
        expected = SourceExpectation(s.scope_id, s.source_id, s.revision, s.context_start, s.context_end)
        hashes = dict(m.scoped_sha256)
        for symbol in s.symbols:
            def evidence(assertion, identity):
                return EvidenceIdentity(identity, s.source_id, s.revision, assertion)
            source = SourceMetadata(
                s.scope_id, s.source_id, s.revision, symbol, s.interval,
                s.context_start, s.context_end, s.decision_time, m.retrieved_at,
                AvailabilityMode(s.mode), OriginalAvailability(m.original_availability),
                evidence("SOURCE_IDENTITY", refs["SOURCE_IDENTITY"]),
                evidence("APPROVED_SYNTHETIC_SCOPE", refs["APPROVED_SYNTHETIC_SCOPE"]),
                ScopedHashMetadata(hashes[symbol], s.source_id, s.revision, symbol,
                                   s.interval, s.context_start, s.context_end, s.projection),
                m.original_receipt,
                evidence("ORIGINAL_ASOF_RECEIPT", m.availability_ref) if m.availability_ref else None)
            check = assess_source(source, expected)
            (invalid if check.status == Readiness.INVALID else missing).extend(check.reasons)
    return _diagnostics(invalid, missing)
