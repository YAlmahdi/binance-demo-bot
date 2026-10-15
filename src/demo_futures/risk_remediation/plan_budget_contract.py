"""M2 supplied-plan compatibility diagnostics, never sizing or admission.

PositionPlan has no source/side/horizon or cost decomposition. Require an explicit
synthetic binding and nonfunding-loss/reserve decomposition; do not infer either.
Exact reconciliation is required: quantity * entry_price = declared notional,
embedded_reserve = notional * frozen 0.001, and nonfunding_loss + reserve =
planned_loss. Then adjusted_loss = nonfunding_loss + M1 allowance. This replaces
the reserve once, without posting costs or changing the existing plan.

Uses M1's 50-digit ceiling context but traps inexact M2 reconciliation instead
of inventing a tolerance for legacy ambient-context rounding. Unsupported plans
are rejected. M1 allowance remains its conditional conservative approximation.
Bindings/decompositions are supplied synthetic assertions, not authenticated plan
provenance or proof of actual future funding. SUFFICIENT means compatible inputs;
EXCEEDS is a valid adverse diagnostic, never permission to admit a position.
No resource threshold, financial parameter, I/O, plan mutation or integration.
"""
from dataclasses import dataclass, field
from decimal import Decimal, DecimalException, Inexact, localcontext

from ..risk import PositionPlan
from ..research_v2.contracts import EvidenceIdentity, Readiness, valid_evidence, valid_identity, valid_time
from .funding_budget import SyntheticFundingStressEnvelope, _context, assess_funding_budget

REASONS = ("INVALID_SCHEMA", "INVALID_NUMBER", "INVALID_BINDING", "INVALID_TIME",
           "INVALID_EVIDENCE", "PLAN_LEVELS_INVALID", "EXPOSURE_MISMATCH",
           "RESERVE_MISMATCH", "DECOMPOSITION_MISMATCH", "ARITHMETIC_UNSUPPORTED",
           "M1_INVALID", "MISSING_BINDING", "MISSING_EVIDENCE", "M1_INSUFFICIENT")
PLAN_FIELDS = ("quantity", "entry_price", "stop_price", "target_price", "budget", "planned_loss", "margin")
TIME_FIELDS = ("decision_time", "as_of", "holding_start", "holding_end", "closure_end")
TEXT_FIELDS = ("symbol", "interval", "side", "source_id", "version")
NUMBER_FIELDS = ("quantity", "entry_price", "entry_notional", "nonfunding_loss", "embedded_reserve")


def reconciliation_context():
    context = _context()
    context.traps[Inexact] = True
    return context


@dataclass(frozen=True, slots=True)
class PlanBudgetBinding:
    symbol: str
    interval: str
    side: str
    source_id: str
    version: str
    decision_time: int
    as_of: int
    holding_start: int
    holding_end: int
    closure_end: int
    quantity: Decimal
    entry_price: Decimal
    entry_notional: Decimal
    nonfunding_loss: Decimal
    embedded_reserve: Decimal
    evidence_identity: EvidenceIdentity | None


@dataclass(frozen=True, slots=True)
class PlanBudgetDiagnostic:
    status: Readiness
    reasons: tuple[str, ...] = ()
    adjusted_loss: Decimal | None = None
    budget: Decimal | None = None
    headroom: Decimal | None = None
    comparison: str | None = None
    evidence: str = field(default="SYNTHETIC_ONLY", init=False)
    authority: str = field(default="SYNTHETIC_DIAGNOSTIC_ONLY", init=False)
    risk_clearance: str = field(default="NOT CLEARED", init=False)

    def __post_init__(self):
        if (type(self.status) is not Readiness or type(self.reasons) is not tuple
                or self.reasons != tuple(r for r in REASONS if r in self.reasons)
                or ((self.status == Readiness.SUFFICIENT) != (not self.reasons))):
            raise ValueError("Ordered diagnostic status required")
        amounts = (self.adjusted_loss, self.budget, self.headroom)
        if self.status != Readiness.SUFFICIENT:
            if any(v is not None for v in amounts) or self.comparison is not None:
                raise ValueError("Failed diagnostics contain no monetary results")
        else:
            if (not all(type(v) is Decimal and v.is_finite() for v in amounts)
                    or self.adjusted_loss <= 0 or self.budget <= 0):
                raise ValueError("Finite diagnostic amounts required")
            with localcontext(reconciliation_context()):
                if (self.headroom != self.budget - self.adjusted_loss
                        or self.comparison != ("WITHIN" if self.headroom >= 0 else "EXCEEDS")):
                    raise ValueError("Diagnostic amounts must reconcile")

    def __bool__(self):
        raise TypeError("Compatibility diagnostics never authorize a position")


def failure(invalid=(), missing=()):
    return PlanBudgetDiagnostic(Readiness.INVALID if invalid else Readiness.INSUFFICIENT,
        tuple(r for r in REASONS if r in (*invalid, *missing)))


def assess_plan_budget(plan, envelope, binding):
    """Check supplied synthetic plan metadata and replace only its declared reserve."""
    if binding is None:
        return failure(missing=("MISSING_BINDING",))
    if (type(plan) is not PositionPlan or type(binding) is not PlanBudgetBinding
            or type(envelope) is not SyntheticFundingStressEnvelope):
        return failure(("INVALID_SCHEMA",))
    try:
        if (any(type(getattr(binding, n)) is not str for n in TEXT_FIELDS)
                or any(type(getattr(binding, n)) is not int for n in TIME_FIELDS)
                or any(type(getattr(binding, n)) is not Decimal for n in NUMBER_FIELDS)
                or any(type(getattr(plan, n)) is not Decimal for n in PLAN_FIELDS)):
            return failure(("INVALID_SCHEMA",))
        if (any(not getattr(plan, n).is_finite() or getattr(plan, n) <= 0 for n in PLAN_FIELDS)
                or any(not getattr(binding, n).is_finite() or getattr(binding, n) < 0 for n in NUMBER_FIELDS)
                or any(getattr(binding, n) <= 0 for n in ("quantity", "entry_price", "entry_notional", "embedded_reserve"))):
            return failure(("INVALID_NUMBER",))
        if any(not valid_time(getattr(binding, n)) for n in TIME_FIELDS):
            return failure(("INVALID_TIME",))
        if (any(getattr(binding, n) != getattr(envelope, n) for n in TEXT_FIELDS + TIME_FIELDS)
                or not valid_identity(binding.source_id) or not valid_identity(binding.version)):
            return failure(("INVALID_BINDING",))
        evidence = binding.evidence_identity
        if evidence is None:
            return failure(missing=("MISSING_EVIDENCE",))
        if (type(evidence) is not EvidenceIdentity or any(type(getattr(evidence, n)) is not str
                for n in ("identity", "source_id", "revision", "assertion", "basis"))
                or not valid_evidence(evidence, "PLAN_BUDGET_DECOMPOSITION", binding.source_id, binding.version)):
            return failure(("INVALID_EVIDENCE",))
        if binding.side not in ("LONG", "SHORT") or not (
                plan.stop_price < plan.entry_price < plan.target_price if binding.side == "LONG"
                else plan.target_price < plan.entry_price < plan.stop_price):
            return failure(("PLAN_LEVELS_INVALID",))
        m1 = assess_funding_budget(envelope)
        if m1.status == Readiness.INVALID:
            return failure(("M1_INVALID",))
        if m1.status != Readiness.SUFFICIENT:
            return failure(missing=("M1_INSUFFICIENT",))
        with localcontext(reconciliation_context()):
            if (plan.quantity != binding.quantity or plan.entry_price != binding.entry_price
                    or plan.entry_price != envelope.entry_price
                    or plan.quantity * plan.entry_price != binding.entry_notional
                    or binding.entry_notional != envelope.entry_notional):
                return failure(("EXPOSURE_MISMATCH",))
            # M1 already pins its floor to the frozen reserve rate; do not add it again.
            if binding.embedded_reserve != m1.reserve_floor:
                return failure(("RESERVE_MISMATCH",))
            if binding.nonfunding_loss + binding.embedded_reserve != plan.planned_loss:
                return failure(("DECOMPOSITION_MISMATCH",))
            adjusted = binding.nonfunding_loss + m1.allowance
            headroom = plan.budget - adjusted
            return PlanBudgetDiagnostic(Readiness.SUFFICIENT, adjusted_loss=adjusted,
                budget=plan.budget, headroom=headroom,
                comparison="WITHIN" if headroom >= 0 else "EXCEEDS")
    except AttributeError:
        return failure(("INVALID_SCHEMA",))
    except (DecimalException, ValueError):
        return failure(("ARITHMETIC_UNSUPPORTED",))
