"""M1: conditional funding allowances over explicitly supplied synthetic scenarios.

Each FundingStressScenario is one alternative complete hypothetical settlement
path, not a forecast or a historical record. Reuse FundingClaim/assess_funding
for schedule, signed rate, mark and synthetic evidence validation. Scenarios
must cover the exact integer-millisecond interval [holding_start+1, closure_end+1):
a newly opened position does not own entry-time funding; it owns funding at the
declared final closure timestamp. holding_end <= closure_end explicitly supplies
the closure delay; no duration, rate, mark or scenario is inferred/defaulted.

Exposure is a supplied positive entry_notional at entry_price, held constant in
units through closure. Event marked notional = entry_notional * mark / entry_price.
Scenario debit = sum(marked_notional * max(sign * rate, 0)). Credits never offset
debits. Worst debit = max(scenario debits), NOT the sum of alternative paths.
Allowance = max(worst debit, entry_notional * existing reserve rate 0.001).
Reserve shortfall = max(worst debit - reserve floor, 0). No fees, sizing, PnL,
settlement posting, portfolio admission or no-settlement financial adapter.

All evidence is internally consistent SYNTHETIC_ASSERTION only, not authenticated
funding truth. Empty/UNKNOWN paths cannot prove no settlement. Explicit supported
KNOWN_NO_SETTLEMENT uses the existing validator and still retains the reserve
floor. Every scenario must be available at as_of; the envelope is valid on
[available_at, expires_at), including the owned closure timestamp. No unavailable
scenario payload is evaluated, and failed diagnostics contain no money amounts.

Arithmetic uses an isolated 50-significant-digit, ceiling-rounded Decimal context
(exponent bounds +/-999), independent of ambient/default context settings. All
signal traps are explicit: invalid operations, division by zero, overflow and
underflow trap; inexact/rounded results and exact subnormals remain supported.
Flags start clear, capitals=1 and clamp=0. This gives conditional
conservative arithmetic, not an absolute loss bound. Unsupported arithmetic fails
closed; these precision limits are engineering limits, not market stress policy.
All future stress choices remain explicit caller inputs. No I/O or activation.
"""
from dataclasses import dataclass, field
from decimal import (
    Clamped, Context, Decimal, DecimalException, DivisionByZero, FloatOperation,
    Inexact, InvalidOperation, Overflow, ROUND_CEILING, Rounded, Subnormal,
    Underflow, localcontext,
)

from ..risk import BacktestConfig, dec
from ..research_v2.config import SYMBOLS
from ..research_v2.contracts import EvidenceIdentity, Readiness, valid_evidence, valid_identity, valid_time
from ..research_v2.funding_contracts import (
    CoverageState, FundingClaim, ScheduleEvidence, SettlementObservation, assess_funding,
)

REASON_ORDER = (
    "INVALID_SCHEMA", "UNSUPPORTED_SCOPE", "INVALID_TIME", "INVALID_IDENTITY",
    "INVALID_NUMBER", "INCONSISTENT_SCOPE", "DUPLICATE_SCENARIO", "INVALID_EVIDENCE",
    "FUNDING_CONTRACT_INVALID", "ARITHMETIC_UNSUPPORTED", "REFERENCE_RESERVE_CHANGED",
    "MISSING_EVIDENCE", "STALE_ENVELOPE", "FUTURE_UNAVAILABLE", "HORIZON_UNSUPPORTED",
    "MISSING_SCENARIOS", "FUNDING_CONTRACT_INSUFFICIENT",
)


def _context():
    # Supplying every signal avoids inheritance from mutable DefaultContext.
    return Context(prec=50, rounding=ROUND_CEILING, Emin=-999, Emax=999,
        capitals=1, clamp=0, flags=[], traps={
            InvalidOperation: True, DivisionByZero: True, Overflow: True, Underflow: True,
            Inexact: False, Rounded: False, Subnormal: False, Clamped: False, FloatOperation: False,
        })


def _number(value, positive=False):
    return (type(value) is Decimal and value.is_finite()
            and (value > 0 if positive else value >= 0))


def _evidence_shape(value):
    return value is None or (type(value) is EvidenceIdentity and all(
        type(getattr(value, name)) is str
        for name in ("identity", "source_id", "revision", "assertion", "basis")))


@dataclass(frozen=True, slots=True)
class FundingStressScenario:
    """One hypothetical complete path; availability applies to its whole payload."""
    scenario_id: str
    available_at: int
    claim: FundingClaim

    def __post_init__(self):
        if (type(self.scenario_id) is not str or type(self.available_at) is not int
                or not _claim_shape(self.claim)):
            raise ValueError("Exact immutable synthetic scenario fields required")


@dataclass(frozen=True, slots=True)
class SyntheticFundingStressEnvelope:
    symbol: str
    interval: str
    side: str
    decision_time: int
    as_of: int
    available_at: int
    expires_at: int
    holding_start: int
    holding_end: int
    closure_end: int
    source_id: str
    version: str
    entry_price: Decimal
    entry_notional: Decimal
    evidence_identity: EvidenceIdentity | None
    scenarios: tuple[FundingStressScenario, ...]
    evidence: str = field(default="SYNTHETIC_ONLY", init=False)

    def __post_init__(self):
        if not _envelope_shape(self):
            raise ValueError("Exact immutable envelope fields required")


def _envelope_shape(value):
    return (all(type(getattr(value, name)) is str for name in
                ("symbol", "interval", "side", "source_id", "version", "evidence"))
            and all(type(getattr(value, name)) is int for name in
                    ("decision_time", "as_of", "available_at", "expires_at",
                     "holding_start", "holding_end", "closure_end"))
            and type(value.entry_price) is Decimal and type(value.entry_notional) is Decimal
            and _evidence_shape(value.evidence_identity)
            and type(value.scenarios) is tuple
            and all(type(s) is FundingStressScenario for s in value.scenarios))


@dataclass(frozen=True, slots=True)
class FundingBudgetDiagnostic:
    status: Readiness
    reasons: tuple[str, ...] = ()
    reserve_floor: Decimal | None = None
    scenario_debits: tuple[tuple[str, Decimal], ...] = ()
    worst_case_debit: Decimal | None = None
    allowance: Decimal | None = None
    reserve_shortfall: Decimal | None = None
    evidence: str = field(default="SYNTHETIC_ONLY", init=False)
    authority: str = field(default="SYNTHETIC_DIAGNOSTIC_ONLY", init=False)
    risk_clearance: str = field(default="NOT CLEARED", init=False)

    def __post_init__(self):
        if (type(self.status) is not Readiness or type(self.reasons) is not tuple
                or self.reasons != tuple(r for r in REASON_ORDER if r in self.reasons)
                or ((self.status == Readiness.SUFFICIENT) != (not self.reasons))
                or type(self.scenario_debits) is not tuple):
            raise ValueError("Ordered immutable diagnostic status required")
        money = (self.reserve_floor, self.worst_case_debit, self.allowance, self.reserve_shortfall)
        if self.status != Readiness.SUFFICIENT:
            if any(v is not None for v in money) or self.scenario_debits:
                raise ValueError("Failed diagnostics cannot invent allowances")
            return
        if (not all(_number(v) for v in money) or self.reserve_floor <= 0
                or not self.scenario_debits or any(type(row) is not tuple or len(row) != 2
                or type(row[0]) is not str or not valid_identity(row[0]) or not _number(row[1])
                for row in self.scenario_debits)):
            raise ValueError("Finite nonnegative allowance components required")
        identities = tuple(row[0] for row in self.scenario_debits)
        with localcontext(_context()):
            if (identities != tuple(sorted(set(identities)))
                    or self.worst_case_debit != max(row[1] for row in self.scenario_debits)
                    or self.allowance != max(self.reserve_floor, self.worst_case_debit)
                    or self.reserve_shortfall != max(Decimal(0), self.worst_case_debit - self.reserve_floor)):
                raise ValueError("Allowance components must reconcile")

    def __bool__(self):
        raise TypeError("Funding diagnostics never authorize admission or access")


def _failure(invalid=(), insufficient=()):
    reasons = tuple(r for r in REASON_ORDER if r in (*invalid, *insufficient))
    return FundingBudgetDiagnostic(Readiness.INVALID if invalid else Readiness.INSUFFICIENT, reasons)


def _claim_shape(claim):
    """Refuse mutable/foreign nested inputs before calling the existing validator."""
    if (type(claim) is not FundingClaim or any(type(getattr(claim, n)) is not str for n in
            ("symbol", "source_id", "revision", "evidence"))
            or not valid_time(claim.start) or not valid_time(claim.end)
            or type(claim.state) is not CoverageState or type(claim.observations) is not tuple):
        return False
    for event in claim.observations:
        if (type(event) is not SettlementObservation or not valid_time(event.timestamp)
                or type(event.rate) is not Decimal
                or (event.mark_price is not None and type(event.mark_price) is not Decimal)
                or not _evidence_shape(event.timing_evidence) or not _evidence_shape(event.mark_evidence)):
            return False
    schedule = claim.schedule
    return schedule is None or (type(schedule) is ScheduleEvidence
        and type(schedule.symbol) is str and valid_time(schedule.start) and valid_time(schedule.end)
        and type(schedule.complete) is bool and type(schedule.expected_settlements) is tuple
        and all(valid_time(t) for t in schedule.expected_settlements) and _evidence_shape(schedule.identity))


def assess_funding_budget(envelope):
    """Validate available hypothetical paths and return diagnostic-only allowances."""
    if type(envelope) is not SyntheticFundingStressEnvelope or not _envelope_shape(envelope):
        return _failure(("INVALID_SCHEMA",))
    e = envelope
    invalid, missing = [], []
    if (any(not valid_time(getattr(e, n)) for n in ("decision_time", "as_of", "available_at",
            "expires_at", "holding_start", "holding_end", "closure_end"))
            or not e.decision_time <= e.as_of <= e.holding_start < e.holding_end <= e.closure_end
            or e.available_at >= e.expires_at):
        invalid.append("INVALID_TIME")
    if invalid:
        return _failure(invalid)
    # Availability gates precede payload interpretation, including evidence/rates.
    if e.available_at > e.as_of:
        return _failure(insufficient=("FUTURE_UNAVAILABLE",))
    if e.expires_at <= e.as_of:
        return _failure(insufficient=("STALE_ENVELOPE",))
    if e.symbol not in SYMBOLS or e.interval != "5m" or e.side not in ("LONG", "SHORT") or e.evidence != "SYNTHETIC_ONLY":
        invalid.append("UNSUPPORTED_SCOPE")
    if not all(valid_identity(v) for v in (e.source_id, e.version)):
        invalid.append("INVALID_IDENTITY")
    if not _number(e.entry_price, True) or not _number(e.entry_notional, True):
        invalid.append("INVALID_NUMBER")
    if e.expires_at <= e.closure_end:
        missing.append("HORIZON_UNSUPPORTED")
    if e.evidence_identity is None:
        missing.append("MISSING_EVIDENCE")
    elif not valid_evidence(e.evidence_identity, "FUNDING_STRESS_ENVELOPE", e.source_id, e.version):
        invalid.append("INVALID_EVIDENCE")
    if not e.scenarios:
        missing.append("MISSING_SCENARIOS")
    for scenario in e.scenarios:
        if type(scenario.available_at) is not int or scenario.available_at < 0:
            invalid.append("INVALID_TIME")
        elif scenario.available_at > e.as_of:
            missing.append("FUTURE_UNAVAILABLE")
    if invalid or missing:
        return _failure(invalid, missing)
    ids = tuple(s.scenario_id for s in e.scenarios)
    if any(type(v) is not str or not valid_identity(v) for v in ids):
        invalid.append("INVALID_IDENTITY")
    if invalid:
        return _failure(invalid)
    if len(ids) != len(set(ids)):
        invalid.append("DUPLICATE_SCENARIO")
    for scenario in e.scenarios:
        claim = scenario.claim
        if not _claim_shape(claim):
            invalid.append("INVALID_SCHEMA")
            continue
        if ((claim.symbol, claim.source_id, claim.revision, claim.start, claim.end)
                != (e.symbol, e.source_id, e.version, e.holding_start + 1, e.closure_end + 1)):
            invalid.append("INCONSISTENT_SCOPE")
        assessment = assess_funding(claim)
        if assessment.validation.status == Readiness.INVALID:
            invalid.append("FUNDING_CONTRACT_INVALID")
        elif assessment.validation.status == Readiness.INSUFFICIENT:
            missing.append("FUNDING_CONTRACT_INSUFFICIENT")
    if invalid or missing:
        return _failure(invalid, missing)
    try:
        with localcontext(_context()):
            reserve_rate = BacktestConfig().funding_reserve_rate
            if reserve_rate != dec("0.001"):
                return _failure(("REFERENCE_RESERVE_CHANGED",))
            floor = e.entry_notional * reserve_rate
            if not _number(floor, True):
                return _failure(("ARITHMETIC_UNSUPPORTED",))
            debits = []
            for scenario in sorted(e.scenarios, key=lambda s: s.scenario_id):
                debit = Decimal(0)
                for event in scenario.claim.observations:
                    adverse_rate = event.rate if e.side == "LONG" else event.rate.copy_negate()
                    if adverse_rate > 0:
                        marked_notional = e.entry_notional * event.mark_price / e.entry_price
                        debit += marked_notional * adverse_rate
                if not _number(debit):
                    return _failure(("ARITHMETIC_UNSUPPORTED",))
                debits.append((scenario.scenario_id, debit))
            worst = max(v for _, v in debits)
            allowance = max(floor, worst)
            shortfall = max(Decimal(0), worst - floor)
            if not _number(allowance) or not _number(shortfall):
                return _failure(("ARITHMETIC_UNSUPPORTED",))
            return FundingBudgetDiagnostic(Readiness.SUFFICIENT, reserve_floor=floor,
                scenario_debits=tuple(debits), worst_case_debit=worst, allowance=allowance,
                reserve_shortfall=shortfall)
    except (DecimalException, ValueError):
        return _failure(("ARITHMETIC_UNSUPPORTED",))
