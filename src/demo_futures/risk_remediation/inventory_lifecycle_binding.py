"""M5 synthetic raw inventory/lifecycle reconciliation, never risk admission.

An explicit caller association supplies the revision absent from M3. Exact scope,
snapshot ID, evaluation time and inventory snapshot_time/lifecycle observed_at must
match. No revision is inferred from version strings or matching data. This proves
only supplied metadata consistency, not content identity or authentic ownership.

M5 bounds binding metadata and caps EACH declared M3/M4 processing budget before
calling either public assessor. Shallow collection lengths are checked up front;
child deep preflight stays inside unchanged M3/M4. Each assessor runs once, M4
then M3, even when the first returns invalid/insufficient. Work is additive, not a
snapshot-by-position cross-product. Conservative ceiling checks can reject a large
child budget even when its actual input is small. Already allocated inputs, child
Decimal.as_tuple allocation, huge caller limits and hostile concurrent mutation
remain outside OS guarantees. These are processing declarations, not financial caps.

Both FULL results must be sufficient: an active successor cannot override M4's
insufficient overall history. Preserve M3's exact position diagnostics and WITHIN/
EXCEEDS comparisons. No monetary total, reserve calculation, sizing, order token,
real ledger, I/O, engine consumer or external authenticity. Synthetic only.
"""
from dataclasses import dataclass, field, replace

from ..research_v2.contracts import EvidenceIdentity, Readiness, valid_identity, valid_evidence
from .budget_inventory_contract import InventoryDeclaration, InventoryDiagnostic, ResourceBudget, assess_inventory
from .snapshot_lifecycle_contract import LifecycleDeclaration, LifecycleDiagnostic, LifecycleResources, assess_lifecycle

SCOPE = ("owner_id", "source_id", "version")
INVALID = ("INVALID_SCHEMA", "INVALID_IDENTITY", "INVALID_TIME", "INVALID_EVIDENCE",
    "DUPLICATE_IDENTITY", "RESOURCE_BUDGET_EXCEEDED", "SCOPE_MISMATCH", "SNAPSHOT_MISMATCH",
    "REVISION_MISMATCH", "TIME_MISMATCH", "M4_INVALID", "M3_INVALID")
MISSING = ("MISSING_ASSOCIATION", "MISSING_EVIDENCE", "M4_INSUFFICIENT", "M3_INSUFFICIENT")
REASONS = INVALID + MISSING


def _exact(value, fields):
    if any(type(getattr(value, name)) is not kind for name, kind in fields):
        raise ValueError("Exact immutable binding fields required")


def _proof_shape(value):
    if value is not None:
        if type(value) is not EvidenceIdentity:
            raise ValueError("Exact synthetic evidence required")
        _exact(value, tuple((n, str) for n in ("identity", "source_id", "revision", "assertion", "basis")))


@dataclass(frozen=True, slots=True)
class RevisionAssociation:
    owner_id: str
    source_id: str
    version: str
    snapshot_id: str
    revision: int
    snapshot_time: int
    evaluation_time: int
    identity: EvidenceIdentity | None
    provenance: EvidenceIdentity | None

    def __post_init__(self):
        _exact(self, tuple((n, str) for n in SCOPE + ("snapshot_id",)) +
            tuple((n, int) for n in ("revision", "snapshot_time", "evaluation_time")))
        _proof_shape(self.identity)
        _proof_shape(self.provenance)


@dataclass(frozen=True, slots=True)
class BindingResources:
    inventory_ceiling: ResourceBudget
    lifecycle_ceiling: LifecycleResources
    max_text_chars: int
    max_integer_bits: int

    def __post_init__(self):
        _exact(self, (("inventory_ceiling", ResourceBudget), ("lifecycle_ceiling", LifecycleResources),
            ("max_text_chars", int), ("max_integer_bits", int)))
        if self.max_text_chars < 0 or self.max_integer_bits < 0:
            raise ValueError("Nonnegative explicit metadata budgets required")


@dataclass(frozen=True, slots=True)
class BindingDeclaration:
    inventory: InventoryDeclaration
    lifecycle: LifecycleDeclaration
    association: RevisionAssociation | None
    resources: BindingResources

    def __post_init__(self):
        _exact(self, (("inventory", InventoryDeclaration), ("lifecycle", LifecycleDeclaration), ("resources", BindingResources)))
        if self.association is not None and type(self.association) is not RevisionAssociation:
            raise ValueError("Explicit raw revision association required")


def _validate_diagnostic(value, kind):
    if type(value) is not kind:
        raise ValueError("Exact recomputed diagnostic required")
    # replace() resets init=False fields; reject forged original labels first.
    for name, definition in kind.__dataclass_fields__.items():
        if not definition.init:
            actual = getattr(value, name)
            if type(actual) is not str or actual != definition.default:
                raise ValueError("Fixed synthetic authority required")
    replace(value)


def _dependency_reasons(inventory, lifecycle):
    return tuple(reason for reason, present in (
        ("M4_INVALID", lifecycle.status is Readiness.INVALID),
        ("M3_INVALID", inventory.status is Readiness.INVALID),
        ("M4_INSUFFICIENT", lifecycle.status is Readiness.INSUFFICIENT),
        ("M3_INSUFFICIENT", inventory.status is Readiness.INSUFFICIENT)) if present)


@dataclass(frozen=True, slots=True)
class BindingDiagnostic:
    status: Readiness
    reasons: tuple[str, ...] = ()
    inventory: InventoryDiagnostic | None = None
    lifecycle: LifecycleDiagnostic | None = None
    authority: str = field(default="SYNTHETIC_DIAGNOSTIC_ONLY", init=False)
    evidence: str = field(default="SYNTHETIC_ONLY", init=False)
    aggregate_state: str = field(default="BLOCKED", init=False)
    risk_clearance: str = field(default="NOT CLEARED", init=False)

    def __post_init__(self):
        if (type(self.status) is not Readiness or type(self.reasons) is not tuple
                or any(type(r) is not str for r in self.reasons)
                or self.reasons != tuple(r for r in REASONS if r in self.reasons)):
            raise ValueError("Ordered exact binding diagnostic required")
        expected = Readiness.INVALID if any(r in INVALID for r in self.reasons) else Readiness.INSUFFICIENT if self.reasons else Readiness.SUFFICIENT
        if self.status is not expected or ((self.inventory is None) != (self.lifecycle is None)):
            raise ValueError("Binding status and dependency presence must reconcile")
        dependency = tuple(r for r in self.reasons if r.startswith(("M4_", "M3_")))
        if self.inventory is None:
            if not self.reasons or any(r not in ("INVALID_SCHEMA", "INVALID_IDENTITY",
                    "INVALID_TIME", "RESOURCE_BUDGET_EXCEEDED") for r in self.reasons):
                raise ValueError("Only structural preflight failures may omit diagnostics")
        else:
            _validate_diagnostic(self.inventory, InventoryDiagnostic)
            _validate_diagnostic(self.lifecycle, LifecycleDiagnostic)
            if dependency != _dependency_reasons(self.inventory, self.lifecycle):
                raise ValueError("Every dependency failure must be retained")

    @property
    def positions(self):
        return () if self.inventory is None else self.inventory.positions

    def __bool__(self):
        raise TypeError("Binding consistency never authorizes admission")


class _Rejected(Exception):
    pass


class _Meter:
    def __init__(self, resources):
        if type(resources) is not BindingResources:
            raise _Rejected("INVALID_SCHEMA")
        replace(resources)
        self.resources, self.chars = resources, 0

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

    def proof(self, value):
        _proof_shape(value)
        if value is not None:
            for name in ("identity", "source_id", "revision", "assertion", "basis"):
                self.text(getattr(value, name))


def _budget(child, ceiling, kind):
    if type(child) is not kind or type(ceiling) is not kind:
        raise _Rejected("INVALID_SCHEMA")
    for name in kind.__dataclass_fields__:
        actual, limit = getattr(child, name), getattr(ceiling, name)
        if type(actual) is not int or type(limit) is not int or min(actual, limit) < 0:
            raise _Rejected("INVALID_SCHEMA")
        if actual > limit:
            raise _Rejected("RESOURCE_BUDGET_EXCEEDED")


def _failure(reason):
    return BindingDiagnostic(Readiness.INVALID if reason in INVALID else Readiness.INSUFFICIENT, (reason,))


def assess_binding(declaration):
    """Recompute both public raw contracts once; no result is admission authority."""
    if type(declaration) is not BindingDeclaration:
        return _failure("INVALID_SCHEMA")
    d = declaration
    try:
        if type(d.inventory) is not InventoryDeclaration or type(d.lifecycle) is not LifecycleDeclaration:
            return _failure("INVALID_SCHEMA")
        meter = _Meter(d.resources)
        i, l, a = d.inventory, d.lifecycle, d.association
        _budget(i.resources, d.resources.inventory_ceiling, ResourceBudget)
        _budget(l.resources, d.resources.lifecycle_ceiling, LifecycleResources)
        for owner, names, maximum in ((i, ("required_position_ids", "plans", "envelopes", "bindings"), i.resources.max_positions),
                (l, ("snapshots", "evidence"), l.resources.max_snapshots), (l, ("events",), l.resources.max_events)):
            for name in names:
                rows = getattr(owner, name)
                if type(rows) is not tuple:
                    return _failure("INVALID_SCHEMA")
                if len(rows) > maximum:
                    return _failure("RESOURCE_BUDGET_EXCEEDED")
        if a is None:
            # Absence is a semantic insufficiency, not malformed raw input.
            # Preserve both bounded recalculations and any worse child failure.
            lifecycle = assess_lifecycle(l)
            inventory = assess_inventory(i)
            reasons = _dependency_reasons(inventory, lifecycle) + ("MISSING_ASSOCIATION",)
            ordered = tuple(r for r in REASONS if r in reasons)
            status = Readiness.INVALID if any(r in INVALID for r in ordered) else Readiness.INSUFFICIENT
            return BindingDiagnostic(status, ordered, inventory, lifecycle)
        if type(a) is not RevisionAssociation:
            return _failure("INVALID_SCHEMA")
        replace(a)
        for obj in (a, i, l):
            for name in SCOPE:
                meter.text(getattr(obj, name))
            meter.integer(obj.evaluation_time)
        for obj in (a, i):
            meter.text(obj.snapshot_id)
            meter.integer(obj.snapshot_time)
        meter.integer(a.revision)
        meter.proof(a.identity)
        meter.proof(a.provenance)
        # Raw children own deep preflight. No nested product/iteration in M5.
        lifecycle = assess_lifecycle(l)
        inventory = assess_inventory(i)
        reasons = list(_dependency_reasons(inventory, lifecycle))
        if any(tuple(getattr(obj, n) for n in SCOPE) != tuple(getattr(a, n) for n in SCOPE) for obj in (i, l)):
            reasons.append("SCOPE_MISMATCH")
        if a.snapshot_id != i.snapshot_id:
            reasons.append("SNAPSHOT_MISMATCH")
        if a.evaluation_time != i.evaluation_time or a.evaluation_time != l.evaluation_time or a.snapshot_time != i.snapshot_time:
            reasons.append("TIME_MISMATCH")
        for identity, purpose in ((a.identity, "INVENTORY_LIFECYCLE_ASSOCIATION"), (a.provenance, "SYNTHETIC_INVENTORY_PROVENANCE")):
            if identity is None:
                reasons.append("MISSING_EVIDENCE")
            elif not valid_evidence(identity, purpose, a.source_id, a.version):
                reasons.append("INVALID_EVIDENCE")
        if a.identity is not None and a.provenance is not None and a.identity.identity == a.provenance.identity:
            reasons.append("DUPLICATE_IDENTITY")
        # Successful raw M4 validation guarantees exact nested reference shapes.
        # An insufficient overall result is NEVER overridden by an active row.
        if lifecycle.status is Readiness.SUFFICIENT:
            matching = tuple(s for s in l.snapshots if s.ref.snapshot_id == a.snapshot_id)
            if not matching:
                reasons.append("SNAPSHOT_MISMATCH")
            else:
                snapshot = matching[0]
                if snapshot.ref.revision != a.revision:
                    reasons.append("REVISION_MISMATCH")
                if snapshot.observed_at != a.snapshot_time:
                    reasons.append("TIME_MISMATCH")
        ordered = tuple(r for r in REASONS if r in reasons)
        status = Readiness.INVALID if any(r in INVALID for r in ordered) else Readiness.INSUFFICIENT if ordered else Readiness.SUFFICIENT
        return BindingDiagnostic(status, ordered, inventory, lifecycle)
    except _Rejected as error:
        return _failure(error.args[0])
    except (AttributeError, ValueError):
        return _failure("INVALID_SCHEMA")
