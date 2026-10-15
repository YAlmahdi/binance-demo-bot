"""M4 pure synthetic snapshot lifecycle consistency; no authenticity or admission.

Revisions are nonnegative exact integers, ordered only within declared identical
owner/source/version scope. Snapshot IDs and revisions are unique in one ledger.
Events are ordered by (issued_at, event_id); same-time events on different snapshots
are allowed. A snapshot has at most one terminal event. Supersession requires a
declared higher revision, no merges, and a successor already available when the
event is available. Effective time is inclusive; no reactivation is supported.

Completeness evidence explicitly observes EXACT evaluation_time (no grace). Its
availability must cover that observation and not be future, hence fresh complete
assertions have observed_at == available_at == evaluation_time. Older observations
are insufficient, never proof that later events did not occur. Evidence expiry is
exclusive. Supplied IDs/revisions/evidence prove internal consistency only.

Caller budgets bound records, references, text and integer bits before downstream
walks/sorting. Already allocated inputs, large allowed budgets and hostile mutation
in the same process are not OS resource/security guarantees. No Decimal arithmetic,
M1/M2 reserve recomputation, M3 consumer, external ledger, clock, I/O or execution.
"""
from dataclasses import dataclass, field, replace
from enum import Enum

from ..research_v2.contracts import EvidenceIdentity, Readiness, valid_identity, valid_evidence


class Completeness(str, Enum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    UNKNOWN = "UNKNOWN"


class EventKind(str, Enum):
    REVOKE = "REVOKE"
    SUPERSEDE = "SUPERSEDE"


class SnapshotState(str, Enum):
    ACTIVE = "ACTIVE"
    FUTURE_UNAVAILABLE = "FUTURE_UNAVAILABLE"
    NOT_YET_VALID = "NOT_YET_VALID"
    EXPIRED = "EXPIRED"
    STALE_EVIDENCE = "STALE_EVIDENCE"
    UNKNOWN = "UNKNOWN"
    INCOMPLETE = "INCOMPLETE"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"


def _exact(obj, fields):
    if any(type(getattr(obj, name)) is not kind for name, kind in fields):
        raise ValueError("Exact immutable lifecycle fields required")


SCOPE = ("owner_id", "source_id", "version")


@dataclass(frozen=True, slots=True)
class SnapshotRef:
    owner_id: str
    source_id: str
    version: str
    snapshot_id: str
    revision: int

    def __post_init__(self):
        _exact(self, tuple((n, str) for n in SCOPE + ("snapshot_id",)) + (("revision", int),))


@dataclass(frozen=True, slots=True)
class SnapshotDeclaration:
    ref: SnapshotRef
    valid_from: int
    expires_at: int
    observed_at: int
    available_at: int
    identity: EvidenceIdentity | None

    def __post_init__(self):
        _exact(self, (("ref", SnapshotRef),) + tuple((n, int) for n in
            ("valid_from", "expires_at", "observed_at", "available_at")))
        _identity_shape(self.identity)


@dataclass(frozen=True, slots=True)
class LifecycleEvent:
    event_id: str
    ref: SnapshotRef
    kind: EventKind
    issued_at: int
    available_at: int
    effective_at: int
    replacement: SnapshotRef | None
    identity: EvidenceIdentity | None

    def __post_init__(self):
        _exact(self, (("event_id", str), ("ref", SnapshotRef), ("kind", EventKind)) +
            tuple((n, int) for n in ("issued_at", "available_at", "effective_at")))
        if self.replacement is not None and type(self.replacement) is not SnapshotRef:
            raise ValueError("Exact replacement reference required")
        _identity_shape(self.identity)


@dataclass(frozen=True, slots=True)
class LifecycleEvidence:
    ref: SnapshotRef
    completeness: Completeness
    observed_at: int
    available_at: int
    expires_at: int
    event_ids: tuple[str, ...]
    identity: EvidenceIdentity | None

    def __post_init__(self):
        _exact(self, (("ref", SnapshotRef), ("completeness", Completeness), ("event_ids", tuple)) +
            tuple((n, int) for n in ("observed_at", "available_at", "expires_at")))
        _identity_shape(self.identity)


@dataclass(frozen=True, slots=True)
class LifecycleResources:
    max_snapshots: int
    max_events: int
    max_references: int
    max_text_chars: int
    max_integer_bits: int

    def __post_init__(self):
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError("Explicit nonnegative integer processing budgets required")


@dataclass(frozen=True, slots=True)
class LifecycleDeclaration:
    owner_id: str
    source_id: str
    version: str
    evaluation_time: int
    snapshots: tuple[SnapshotDeclaration, ...]
    events: tuple[LifecycleEvent, ...]
    evidence: tuple[LifecycleEvidence, ...]
    resources: LifecycleResources

    def __post_init__(self):
        _exact(self, tuple((n, str) for n in SCOPE) + (("evaluation_time", int),
            ("snapshots", tuple), ("events", tuple), ("evidence", tuple), ("resources", LifecycleResources)))


INVALID = ("INVALID_SCHEMA", "INVALID_IDENTITY", "INVALID_TIME", "INVALID_EVIDENCE",
    "RESOURCE_BUDGET_EXCEEDED", "SCOPE_MISMATCH", "IDENTITY_REUSE", "REVISION_AMBIGUITY",
    "REPLAY", "UNORDERED_EVENTS", "CONTRADICTORY_EVENT", "REFERENCE_MISMATCH")
MISSING = ("MISSING_SNAPSHOTS", "MISSING_EVIDENCE", "FUTURE_UNAVAILABLE", "NOT_YET_VALID",
    "EXPIRED", "STALE_EVIDENCE", "UNKNOWN", "INCOMPLETE", "REVOKED", "SUPERSEDED")
REASONS = INVALID + MISSING


@dataclass(frozen=True, slots=True)
class SnapshotDiagnostic:
    snapshot_id: str
    revision: int
    state: SnapshotState

    def __post_init__(self):
        if (type(self.snapshot_id) is not str or not valid_identity(self.snapshot_id)
                or type(self.revision) is not int or self.revision < 0 or type(self.state) is not SnapshotState):
            raise ValueError("Exact snapshot diagnostic required")

    def __bool__(self):
        raise TypeError("Lifecycle consistency never grants authority")


@dataclass(frozen=True, slots=True)
class LifecycleDiagnostic:
    status: Readiness
    reasons: tuple[str, ...] = ()
    snapshots: tuple[SnapshotDiagnostic, ...] = ()
    authority: str = field(default="SYNTHETIC_DIAGNOSTIC_ONLY", init=False)
    evidence: str = field(default="SYNTHETIC_ONLY", init=False)
    aggregate_state: str = field(default="BLOCKED", init=False)
    risk_clearance: str = field(default="NOT CLEARED", init=False)

    def __post_init__(self):
        if (type(self.status) is not Readiness or type(self.reasons) is not tuple
                or any(type(r) is not str for r in self.reasons)
                or self.reasons != tuple(r for r in REASONS if r in self.reasons)
                or type(self.snapshots) is not tuple or any(type(s) is not SnapshotDiagnostic for s in self.snapshots)):
            raise ValueError("Exact ordered lifecycle diagnostic required")
        for row in self.snapshots:
            replace(row)
        ids = tuple(s.snapshot_id for s in self.snapshots)
        if ids != tuple(sorted(set(ids))):
            raise ValueError("Unique sorted snapshot diagnostics required")
        revisions = tuple(s.revision for s in self.snapshots)
        if len(set(revisions)) != len(revisions):
            raise ValueError("Diagnostic revisions must remain unambiguous")
        expected = Readiness.INVALID if any(r in INVALID for r in self.reasons) else Readiness.INSUFFICIENT if self.reasons else Readiness.SUFFICIENT
        if self.status != expected or (not self.reasons and not self.snapshots):
            raise ValueError("Lifecycle status must match explicit evidence")
        if not self.snapshots and any(r in self.reasons for r in MISSING[3:]):
            raise ValueError("Snapshot states require explicit snapshot diagnostics")
        if self.snapshots and self.reasons != tuple(r for r in MISSING if any(s.state.value == r for s in self.snapshots)):
            raise ValueError("Every non-active snapshot must be reported")

    def __bool__(self):
        raise TypeError("Lifecycle consistency never grants authority")


def _identity_shape(value):
    if value is not None:
        if type(value) is not EvidenceIdentity:
            raise ValueError("Exact evidence identity required")
        _exact(value, tuple((n, str) for n in ("identity", "source_id", "revision", "assertion", "basis")))


class _Rejected(Exception):
    pass


class _Meter:
    def __init__(self, resources):
        if type(resources) is not LifecycleResources:
            raise _Rejected("INVALID_SCHEMA")
        replace(resources)
        self.resources, self.chars, self.references = resources, 0, 0

    def text(self, value):
        if type(value) is not str:
            raise _Rejected("INVALID_SCHEMA")
        self.chars += len(value)
        if self.chars > self.resources.max_text_chars:
            raise _Rejected("RESOURCE_BUDGET_EXCEEDED")
        if not valid_identity(value):
            raise _Rejected("INVALID_IDENTITY")

    def integer(self, value):
        if type(value) is not int:
            raise _Rejected("INVALID_SCHEMA")
        if value < 0:
            raise _Rejected("INVALID_TIME")
        if value.bit_length() > self.resources.max_integer_bits:
            raise _Rejected("RESOURCE_BUDGET_EXCEEDED")

    def ref(self, value):
        if type(value) is not SnapshotRef:
            raise _Rejected("INVALID_SCHEMA")
        for name in SCOPE + ("snapshot_id",):
            self.text(getattr(value, name))
        self.integer(value.revision)

    def identity(self, value):
        _identity_shape(value)
        if value is not None:
            for name in ("identity", "source_id", "revision", "assertion", "basis"):
                self.text(getattr(value, name))


def _failure(reason):
    return LifecycleDiagnostic(Readiness.INVALID if reason in INVALID else Readiness.INSUFFICIENT, (reason,))


def assess_lifecycle(declaration):
    """Validate a supplied complete synthetic ledger; no consumer is activated."""
    if type(declaration) is not LifecycleDeclaration:
        return _failure("INVALID_SCHEMA")
    d = declaration
    try:
        meter = _Meter(d.resources)
        for name in SCOPE:
            meter.text(getattr(d, name))
        meter.integer(d.evaluation_time)
        if any(type(getattr(d, n)) is not tuple for n in ("snapshots", "events", "evidence")):
            return _failure("INVALID_SCHEMA")
        if (len(d.snapshots) > d.resources.max_snapshots or len(d.evidence) > d.resources.max_snapshots
                or len(d.events) > d.resources.max_events):
            return _failure("RESOURCE_BUDGET_EXCEEDED")
        # Complete exact shape/resource preflight before any raw comparisons/maps.
        for rows, kind in ((d.snapshots, SnapshotDeclaration), (d.events, LifecycleEvent), (d.evidence, LifecycleEvidence)):
            for row in rows:
                if type(row) is not kind:
                    return _failure("INVALID_SCHEMA")
                replace(row)
                meter.ref(row.ref)
                meter.identity(row.identity)
                names = ("valid_from", "expires_at", "observed_at", "available_at") if kind is SnapshotDeclaration else (
                    ("issued_at", "available_at", "effective_at") if kind is LifecycleEvent else ("observed_at", "available_at", "expires_at"))
                for name in names:
                    meter.integer(getattr(row, name))
                if kind is LifecycleEvent:
                    meter.text(row.event_id)
                    if row.replacement is not None:
                        meter.ref(row.replacement)
                if kind is LifecycleEvidence:
                    meter.references += len(row.event_ids)
                    if meter.references > d.resources.max_references:
                        return _failure("RESOURCE_BUDGET_EXCEEDED")
                    for identity in row.event_ids:
                        meter.text(identity)
        scope = tuple(getattr(d, n) for n in SCOPE)
        snapshots, revisions, identities = {}, set(), set()
        def bind(ref):
            if tuple(getattr(ref, n) for n in SCOPE) != scope:
                raise _Rejected("SCOPE_MISMATCH")
        def proof(identity, purpose):
            if identity is None:
                raise _Rejected("MISSING_EVIDENCE")
            if not valid_evidence(identity, purpose, d.source_id, d.version):
                raise _Rejected("INVALID_EVIDENCE")
            if identity.identity in identities:
                raise _Rejected("IDENTITY_REUSE")
            identities.add(identity.identity)
        for s in d.snapshots:
            bind(s.ref)
            if s.ref.snapshot_id in snapshots:
                return _failure("IDENTITY_REUSE")
            if s.ref.revision in revisions:
                return _failure("REVISION_AMBIGUITY")
            if s.valid_from >= s.expires_at or s.observed_at > s.available_at:
                return _failure("INVALID_TIME")
            proof(s.identity, "SNAPSHOT_DECLARATION")
            snapshots[s.ref.snapshot_id] = s
            revisions.add(s.ref.revision)
        if not snapshots:
            return _failure("MISSING_SNAPSHOTS")
        def matched(ref):
            bind(ref)
            if ref.snapshot_id not in snapshots or ref != snapshots[ref.snapshot_id].ref:
                raise _Rejected("REFERENCE_MISMATCH")
            return snapshots[ref.snapshot_id]
        events, terminal, incoming, order = {}, {}, set(), []
        for e in d.events:
            s = matched(e.ref)
            if e.event_id in events:
                return _failure("REPLAY")
            if e.ref.snapshot_id in terminal:
                return _failure("CONTRADICTORY_EVENT")
            if (e.issued_at < s.observed_at or e.issued_at > e.available_at
                    or e.effective_at < max(e.issued_at, s.valid_from)):
                return _failure("INVALID_TIME")
            proof(e.identity, "LIFECYCLE_EVENT")
            if e.kind is EventKind.REVOKE:
                if e.replacement is not None:
                    return _failure("CONTRADICTORY_EVENT")
            else:
                if e.replacement is None:
                    return _failure("REFERENCE_MISMATCH")
                successor = matched(e.replacement)
                if (successor.ref.revision <= e.ref.revision or not successor.valid_from <= e.effective_at < successor.expires_at
                        or successor.available_at > e.available_at or successor.ref.snapshot_id in incoming):
                    return _failure("CONTRADICTORY_EVENT")
                incoming.add(successor.ref.snapshot_id)
            events[e.event_id] = e
            terminal[e.ref.snapshot_id] = e
            order.append((e.issued_at, e.event_id))
        if order != sorted(order):
            return _failure("UNORDERED_EVENTS")
        for e in d.events:
            if e.replacement is not None:
                later = terminal.get(e.replacement.snapshot_id)
                if later is not None and (later.issued_at < e.effective_at or later.effective_at < e.effective_at):
                    return _failure("CONTRADICTORY_EVENT")
        evidence = {}
        for claim in d.evidence:
            s = matched(claim.ref)
            if claim.ref.snapshot_id in evidence:
                return _failure("IDENTITY_REUSE")
            proof(claim.identity, "LIFECYCLE_COMPLETENESS")
            if (claim.observed_at > claim.available_at or claim.available_at >= claim.expires_at
                    or claim.observed_at < s.observed_at or claim.available_at < s.available_at):
                return _failure("INVALID_TIME")
            if claim.event_ids != tuple(sorted(set(claim.event_ids))):
                return _failure("REPLAY")
            expected = (terminal[s.ref.snapshot_id].event_id,) if s.ref.snapshot_id in terminal else ()
            if claim.event_ids != expected:
                return _failure("REFERENCE_MISMATCH")
            evidence[claim.ref.snapshot_id] = claim
        if set(evidence) != set(snapshots):
            return _failure("MISSING_EVIDENCE")
        if any(e.available_at > d.evaluation_time or e.effective_at > d.evaluation_time for e in d.events):
            return _failure("FUTURE_UNAVAILABLE")
        rows = []
        for identity in sorted(snapshots):
            s, claim = snapshots[identity], evidence[identity]
            if s.available_at > d.evaluation_time or claim.available_at > d.evaluation_time:
                state = SnapshotState.FUTURE_UNAVAILABLE
            elif d.evaluation_time < s.valid_from:
                state = SnapshotState.NOT_YET_VALID
            elif d.evaluation_time >= s.expires_at:
                state = SnapshotState.EXPIRED
            elif claim.observed_at != d.evaluation_time or d.evaluation_time >= claim.expires_at:
                state = SnapshotState.STALE_EVIDENCE
            elif claim.completeness is not Completeness.COMPLETE:
                state = SnapshotState[claim.completeness.value]
            elif identity in terminal:
                state = SnapshotState.REVOKED if terminal[identity].kind is EventKind.REVOKE else SnapshotState.SUPERSEDED
            else:
                state = SnapshotState.ACTIVE
            rows.append(SnapshotDiagnostic(identity, s.ref.revision, state))
        reasons = tuple(r for r in MISSING if any(s.state.value == r for s in rows))
        return LifecycleDiagnostic(Readiness.INSUFFICIENT if reasons else Readiness.SUFFICIENT, reasons, tuple(rows))
    except _Rejected as error:
        return _failure(error.args[0])
    except (AttributeError, ValueError):
        return _failure("INVALID_SCHEMA")
