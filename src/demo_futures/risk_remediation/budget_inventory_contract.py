"""M3: caller-budgeted synthetic inventory consistency, never portfolio risk.

Three independently keyed raw-input collections must exactly match an explicit
required-position inventory. Owner/source/version/snapshot assertions are checked,
not authenticated. Each raw triple is assessed again by M2. No supplied successful
diagnostic is accepted. Even an explicitly COMPLETE empty inventory proves only
internal consistency of supplied assertions, not absence of actual positions.

Caller resource budgets bound declared positions, total scenarios, total observed
and scheduled funding items, total Decimal coefficient digits, total text chars,
and per-integer bit length. These are explicit processing budgets, not universal
production limits or financial policy. Already-allocated Python inputs and Decimal
as_tuple allocation are not an OS memory sandbox. Preflight is linear in supplied
items/digits; sorting/validation inside existing M1/M2 adds its existing costs.

No combined monetary summary is produced: M1/M2 do not establish a joint stress
model. Every aggregate remains BLOCKED, including caller-declared joint models.
No reserve is recomputed or posted here: M2 alone replaces it once per position.
"""
from dataclasses import dataclass, field, replace
from decimal import Decimal
from enum import Enum

from ..risk import PositionPlan
from ..research_v2.contracts import EvidenceIdentity, Readiness, valid_evidence, valid_identity
from ..research_v2.funding_contracts import FundingClaim, ScheduleEvidence
from .funding_budget import SyntheticFundingStressEnvelope, _envelope_shape, _claim_shape
from .plan_budget_contract import (PlanBudgetBinding, PlanBudgetDiagnostic, PLAN_FIELDS,
    TEXT_FIELDS, TIME_FIELDS, NUMBER_FIELDS, assess_plan_budget)


class Completeness(str, Enum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    UNKNOWN = "UNKNOWN"


class JointKind(str, Enum):
    NO_COMBINED_MODEL = "NO_COMBINED_MODEL"
    INDEPENDENCE_ASSERTION = "INDEPENDENCE_ASSERTION"
    JOINT_MODEL_ASSERTION = "JOINT_MODEL_ASSERTION"


@dataclass(frozen=True, slots=True)
class ResourceBudget:
    max_positions: int
    max_scenarios: int
    max_funding_items: int
    max_decimal_digits: int
    max_text_chars: int
    max_integer_bits: int


@dataclass(frozen=True, slots=True)
class InventoryInput:
    position_id: str
    owner_id: str
    source_id: str
    version: str
    snapshot_id: str
    value: PositionPlan | SyntheticFundingStressEnvelope | PlanBudgetBinding


@dataclass(frozen=True, slots=True)
class CompletenessAssertion:
    owner_id: str
    source_id: str
    version: str
    snapshot_id: str
    snapshot_time: int
    complete: bool
    identity: EvidenceIdentity | None


@dataclass(frozen=True, slots=True)
class JointScenarioAssertion:
    source_id: str
    version: str
    snapshot_id: str
    kind: JointKind
    description: str
    identity: EvidenceIdentity | None


@dataclass(frozen=True, slots=True)
class InventoryDeclaration:
    owner_id: str
    source_id: str
    version: str
    snapshot_id: str
    snapshot_time: int
    evaluation_time: int
    available_at: int
    expires_at: int
    required_position_ids: tuple[str, ...]
    plans: tuple[InventoryInput, ...]
    envelopes: tuple[InventoryInput, ...]
    bindings: tuple[InventoryInput, ...]
    completeness: Completeness
    completeness_assertion: CompletenessAssertion | None
    joint_assertion: JointScenarioAssertion | None
    resources: ResourceBudget


@dataclass(frozen=True, slots=True)
class PositionDiagnostic:
    position_id: str
    result: PlanBudgetDiagnostic

    def __post_init__(self):
        if type(self.position_id) is not str or not valid_identity(self.position_id) or type(self.result) is not PlanBudgetDiagnostic:
            raise ValueError("Exact immutable position diagnostic required")
        replace(self.result)  # Revalidate, never grant authority to a forged result.


REASONS = ("INVALID_SCHEMA", "INVALID_IDENTITY", "INVALID_TIME", "INVALID_NUMBER",
    "INVALID_EVIDENCE", "RESOURCE_BUDGET_EXCEEDED", "CONFLICTING_SCOPE",
    "DUPLICATE_POSITION", "INVENTORY_MISMATCH", "CONTRADICTORY_COMPLETENESS",
    "ENTRY_INVALID", "FUTURE_UNAVAILABLE", "STALE_SNAPSHOT", "MISSING_COMPLETENESS",
    "INVENTORY_INCOMPLETE", "MISSING_JOINT_ASSERTION", "ENTRY_INSUFFICIENT")
SCOPE = ("owner_id", "source_id", "version", "snapshot_id")
COLLECTIONS = ("plans", "envelopes", "bindings")


@dataclass(frozen=True, slots=True)
class InventoryDiagnostic:
    status: Readiness
    reasons: tuple[str, ...] = ()
    positions: tuple[PositionDiagnostic, ...] = ()
    aggregate_state: str = field(default="BLOCKED", init=False)
    aggregate_reason: str = field(default="JOINT_STRESS_UNSUPPORTED", init=False)
    evidence: str = field(default="SYNTHETIC_ONLY", init=False)
    authority: str = field(default="SYNTHETIC_DIAGNOSTIC_ONLY", init=False)
    risk_clearance: str = field(default="NOT CLEARED", init=False)

    def __post_init__(self):
        if (type(self.status) is not Readiness or type(self.reasons) is not tuple
                or any(type(r) is not str for r in self.reasons)
                or self.reasons != tuple(r for r in REASONS if r in self.reasons)
                or ((self.status == Readiness.SUFFICIENT) != (not self.reasons))
                or type(self.positions) is not tuple or any(type(p) is not PositionDiagnostic for p in self.positions)):
            raise ValueError("Ordered immutable inventory diagnostic required")
        for row in self.positions:
            replace(row)
        ids = tuple(p.position_id for p in self.positions)
        if ids != tuple(sorted(set(ids))):
            raise ValueError("Unique sorted diagnostic positions required")
        if not self.positions and any(r in self.reasons for r in ("ENTRY_INVALID", "ENTRY_INSUFFICIENT")):
            raise ValueError("Entry failures require explicit position diagnostics")
        if self.positions:
            invalid = any(p.result.status == Readiness.INVALID for p in self.positions)
            missing = any(p.result.status == Readiness.INSUFFICIENT for p in self.positions)
            expected = tuple(r for r, present in (("ENTRY_INVALID", invalid), ("ENTRY_INSUFFICIENT", missing)) if present)
            if self.reasons != expected or self.status != (Readiness.INVALID if invalid else Readiness.INSUFFICIENT if missing else Readiness.SUFFICIENT):
                raise ValueError("Every failed entry must be reported")

    def __bool__(self):
        raise TypeError("Inventory diagnostics never authorize access or positions")


def _failure(reason, *, missing=False):
    return InventoryDiagnostic(Readiness.INSUFFICIENT if missing else Readiness.INVALID, (reason,))


class _Rejected(Exception):
    pass


class _Meter:
    def __init__(self, budget):
        if (type(budget) is not ResourceBudget or any(type(getattr(budget, n)) is not int
                or getattr(budget, n) < 0 for n in ResourceBudget.__dataclass_fields__)):
            raise _Rejected("INVALID_SCHEMA")
        self.budget = budget
        self.text_chars = self.digits = self.scenarios = self.items = 0

    def text(self, value, *, identity=False):
        if type(value) is not str:
            raise _Rejected("INVALID_SCHEMA")
        self.text_chars += len(value)
        if self.text_chars > self.budget.max_text_chars:
            raise _Rejected("RESOURCE_BUDGET_EXCEEDED")
        if identity and not valid_identity(value):
            raise _Rejected("INVALID_IDENTITY")

    def integer(self, value):
        if type(value) is not int:
            raise _Rejected("INVALID_SCHEMA")
        if value < 0:
            raise _Rejected("INVALID_TIME")
        if value.bit_length() > self.budget.max_integer_bits:
            raise _Rejected("RESOURCE_BUDGET_EXCEEDED")

    def number(self, value):
        if type(value) is not Decimal:
            raise _Rejected("INVALID_SCHEMA")
        if not value.is_finite():
            raise _Rejected("INVALID_NUMBER")
        parts = value.as_tuple()
        self.digits += len(parts.digits)
        if self.digits > self.budget.max_decimal_digits or abs(parts.exponent).bit_length() > self.budget.max_integer_bits:
            raise _Rejected("RESOURCE_BUDGET_EXCEEDED")

    def evidence(self, value):
        if value is None:
            return
        if type(value) is not EvidenceIdentity:
            raise _Rejected("INVALID_SCHEMA")
        for n in ("identity", "source_id", "revision", "assertion", "basis"):
            self.text(getattr(value, n))


def _preflight_raw(value, expected, meter):
    if type(value) is not expected:
        raise _Rejected("INVALID_SCHEMA")
    if expected is PositionPlan:
        for name in PLAN_FIELDS:
            meter.number(getattr(value, name))
    elif expected is PlanBudgetBinding:
        for name in TEXT_FIELDS:
            meter.text(getattr(value, name))
        for name in TIME_FIELDS:
            meter.integer(getattr(value, name))
        for name in NUMBER_FIELDS:
            meter.number(getattr(value, name))
        meter.evidence(value.evidence_identity)
    else:
        if type(value.scenarios) is not tuple:
            raise _Rejected("INVALID_SCHEMA")
        meter.scenarios += len(value.scenarios)
        if meter.scenarios > meter.budget.max_scenarios:
            raise _Rejected("RESOURCE_BUDGET_EXCEEDED")
        if not _envelope_shape(value):
            raise _Rejected("INVALID_SCHEMA")
        for name in TEXT_FIELDS + ("evidence",):
            meter.text(getattr(value, name))
        for name in TIME_FIELDS + ("available_at", "expires_at"):
            meter.integer(getattr(value, name))
        meter.number(value.entry_price)
        meter.number(value.entry_notional)
        meter.evidence(value.evidence_identity)
        for path in value.scenarios:
            meter.text(path.scenario_id, identity=True)
            meter.integer(path.available_at)
            claim = path.claim
            if (type(claim) is not FundingClaim or type(claim.observations) is not tuple
                    or (claim.schedule is not None and (type(claim.schedule) is not ScheduleEvidence
                        or type(claim.schedule.expected_settlements) is not tuple))):
                raise _Rejected("INVALID_SCHEMA")
            meter.items += len(claim.observations) + (len(claim.schedule.expected_settlements) if claim.schedule else 0)
            if meter.items > meter.budget.max_funding_items:
                raise _Rejected("RESOURCE_BUDGET_EXCEEDED")
            if not _claim_shape(claim):
                raise _Rejected("INVALID_SCHEMA")
            for name in ("symbol", "source_id", "revision", "evidence"):
                meter.text(getattr(claim, name))
            meter.integer(claim.start)
            meter.integer(claim.end)
            for event in claim.observations:
                meter.integer(event.timestamp)
                meter.number(event.rate)
                if event.mark_price is not None:
                    meter.number(event.mark_price)
                meter.evidence(event.timing_evidence)
                meter.evidence(event.mark_evidence)
            if claim.schedule is not None:
                meter.text(claim.schedule.symbol)
                meter.integer(claim.schedule.start)
                meter.integer(claim.schedule.end)
                meter.evidence(claim.schedule.identity)
                for timestamp in claim.schedule.expected_settlements:
                    meter.integer(timestamp)


def assess_inventory(inventory):
    """Return sorted per-position M2 diagnostics; every aggregate remains blocked."""
    if type(inventory) is not InventoryDeclaration:
        return _failure("INVALID_SCHEMA")
    d = inventory
    try:
        meter = _Meter(d.resources)
        for name in SCOPE:
            meter.text(getattr(d, name), identity=True)
        for name in ("snapshot_time", "evaluation_time", "available_at", "expires_at"):
            meter.integer(getattr(d, name))
        if not d.snapshot_time <= d.available_at < d.expires_at or d.snapshot_time > d.evaluation_time:
            return _failure("INVALID_TIME")
        if d.available_at > d.evaluation_time:
            return _failure("FUTURE_UNAVAILABLE", missing=True)
        if d.evaluation_time >= d.expires_at:
            return _failure("STALE_SNAPSHOT", missing=True)
        if type(d.completeness) is not Completeness:
            return _failure("INVALID_SCHEMA")
        if d.completeness == Completeness.UNKNOWN or d.completeness_assertion is None:
            return _failure("MISSING_COMPLETENESS", missing=True)
        assertion = d.completeness_assertion
        if type(assertion) is not CompletenessAssertion or type(assertion.complete) is not bool:
            return _failure("INVALID_SCHEMA")
        for name in SCOPE:
            meter.text(getattr(assertion, name), identity=True)
        meter.integer(assertion.snapshot_time)
        meter.evidence(assertion.identity)
        if any(getattr(d, n) != getattr(assertion, n) for n in SCOPE + ("snapshot_time",)):
            return _failure("CONFLICTING_SCOPE")
        if not valid_evidence(assertion.identity, "INVENTORY_COMPLETENESS", d.source_id, d.version):
            return _failure("INVALID_EVIDENCE")
        if assertion.complete != (d.completeness == Completeness.COMPLETE):
            return _failure("CONTRADICTORY_COMPLETENESS")
        if d.completeness == Completeness.INCOMPLETE:
            return _failure("INVENTORY_INCOMPLETE", missing=True)
        joint = d.joint_assertion
        if joint is None:
            return _failure("MISSING_JOINT_ASSERTION", missing=True)
        if type(joint) is not JointScenarioAssertion or type(joint.kind) is not JointKind:
            return _failure("INVALID_SCHEMA")
        for name in ("source_id", "version", "snapshot_id"):
            meter.text(getattr(joint, name), identity=True)
        meter.text(joint.description)
        meter.evidence(joint.identity)
        if not joint.description.strip() or any(getattr(joint, n) != getattr(d, n) for n in ("source_id", "version", "snapshot_id")):
            return _failure("CONFLICTING_SCOPE")
        if not valid_evidence(joint.identity, "JOINT_SCENARIO_ASSUMPTION", d.source_id, d.version):
            return _failure("INVALID_EVIDENCE")
        if type(d.required_position_ids) is not tuple or any(type(getattr(d, n)) is not tuple for n in COLLECTIONS):
            return _failure("INVALID_SCHEMA")
        if any(len(rows) > d.resources.max_positions for rows in (d.required_position_ids, d.plans, d.envelopes, d.bindings)):
            return _failure("RESOURCE_BUDGET_EXCEEDED")
        for identity in d.required_position_ids:
            meter.text(identity, identity=True)
        required = set(d.required_position_ids)
        if len(required) != len(d.required_position_ids):
            return _failure("DUPLICATE_POSITION")
        maps = []
        for rows, expected in zip((d.plans, d.envelopes, d.bindings), (PositionPlan, SyntheticFundingStressEnvelope, PlanBudgetBinding)):
            mapped = {}
            for row in rows:
                if type(row) is not InventoryInput:
                    return _failure("INVALID_SCHEMA")
                meter.text(row.position_id, identity=True)
                for name in SCOPE:
                    meter.text(getattr(row, name), identity=True)
                if any(getattr(row, n) != getattr(d, n) for n in SCOPE):
                    return _failure("CONFLICTING_SCOPE")
                if row.position_id in mapped:
                    return _failure("DUPLICATE_POSITION")
                _preflight_raw(row.value, expected, meter)
                mapped[row.position_id] = row.value
            if set(mapped) != required:
                return _failure("INVENTORY_MISMATCH")
            maps.append(mapped)
        plans, envelopes, bindings = maps
        # Global scope/time binding precedes any per-position assessment.
        for identity in sorted(required):
            e, b = envelopes[identity], bindings[identity]
            if (e.source_id != d.source_id or e.version != d.version
                    or b.source_id != d.source_id or b.version != d.version
                    or e.as_of != d.evaluation_time or b.as_of != d.evaluation_time
                    or e.decision_time > d.snapshot_time):
                return _failure("CONFLICTING_SCOPE")
        positions = tuple(PositionDiagnostic(identity, assess_plan_budget(plans[identity], envelopes[identity], bindings[identity]))
                          for identity in sorted(required))
        invalid = any(p.result.status == Readiness.INVALID for p in positions)
        missing = any(p.result.status == Readiness.INSUFFICIENT for p in positions)
        reasons = tuple(r for r, present in (("ENTRY_INVALID", invalid), ("ENTRY_INSUFFICIENT", missing)) if present)
        return InventoryDiagnostic(Readiness.INVALID if invalid else Readiness.INSUFFICIENT if missing else Readiness.SUFFICIENT,
                                   reasons, positions)
    except _Rejected as error:
        return _failure(error.args[0])
    except (AttributeError, ValueError):
        return _failure("INVALID_SCHEMA")
