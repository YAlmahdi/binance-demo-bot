"""Offline V2 fixture integration. Results never authorize fitting or execution."""
from dataclasses import dataclass, field
from enum import Enum

from .authorization_binding import MAX_DECLARED_ROWS
from .config import HOUR, HORIZON, STEP, SYMBOLS
from .contracts import Readiness
from .features import FeatureRow
from .funding_contracts import CoverageState, FundingClaim, assess_funding
from .historical_scope import (
    CandleScope, SliceApproval, SnapshotIdentity, VersionObservation, _identity, _snapshot_errors,
    _time, commitment, row_commitment, valid_commitment,
)
from .horizon_coverage import assess_horizon
from .loader_boundary import _plain_input
from .pinned_prefix import assess_pinned_prefix
from .source_contracts import PROTECTED, TARGET_END, TARGET_START
from .validation import DevelopmentWindow, IntervalRow, TrainingReceipt, ids_hash, partition_reason, sample_gate


class Verdict(str, Enum):
    READY = "READY"
    INSUFFICIENT = "INSUFFICIENT"
    INVALID = "INVALID"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class Stage:
    verdict: Verdict
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FixturePlan:
    window: DevelopmentWindow
    origin: int
    sources: tuple[SnapshotIdentity, ...]
    retrieved_at: int
    audit_cutoff: int
    evaluated_at: int


@dataclass(frozen=True, slots=True)
class PrefixInput:
    row_id: str
    scope: CandleScope
    approval: SliceApproval | None
    observations: tuple[VersionObservation, ...]


@dataclass(frozen=True, slots=True)
class ActionEvidence:
    side: str
    reference: str
    valid: bool


@dataclass(frozen=True, slots=True)
class PairEvidence:
    row_id: str
    prefix_sha256: str
    horizon_sha256: str
    funding_sha256: str
    producer: str
    revision: str
    available_at: int
    actions: tuple[ActionEvidence, ...]
    basis: str = field(default="INVENTED_PAIR_VALIDITY_ONLY", init=False)


@dataclass(frozen=True, slots=True)
class OutcomeInput:
    row_id: str
    scope: CandleScope | None = None
    approval: SliceApproval | None = None
    observations: tuple[VersionObservation, ...] = ()
    funding: FundingClaim | None = None
    pair: PairEvidence | None = None
    sealed: bool = False


@dataclass(frozen=True, slots=True)
class CausalEntry:
    interval: IntervalRow
    stage: Stage
    decision: str
    partition: str
    partition_reason: str
    features: FeatureRow | None = None
    prefix_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class PopulationEntry:
    row_id: str
    stage: Stage
    horizon_end: int
    prefix_sha256: str | None = None
    horizon_sha256: str | None = None
    mature_at: int | None = None
    funding_state: CoverageState = CoverageState.UNKNOWN
    funding_sha256: str | None = None
    pair_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class TrainingPopulationReceipt:
    window: DevelopmentWindow
    sources: tuple[SnapshotIdentity, ...]
    origin: int
    audit_cutoff: int
    eligible_ids: tuple[str, ...]
    entries: tuple[PopulationEntry, ...]
    sha256: str
    evidence: str = field(default="SYNTHETIC_ONLY", init=False)
    financial_evidence: str = field(default="INVENTED_DECLARATIONS_ONLY", init=False)
    financial_validity: str = field(default="NOT ESTABLISHED", init=False)

    def __bool__(self):
        raise TypeError("A synthetic population receipt never grants training authority")


@dataclass(frozen=True, slots=True)
class WorkflowResult:
    causal_stage: Stage
    causal: tuple[CausalEntry, ...] = ()
    population: TrainingPopulationReceipt | None = None
    prefit: Stage = Stage(Verdict.BLOCKED, ("NO_TRAINING_RECEIPT",))
    fit: Stage = field(default=Stage(Verdict.BLOCKED, ("SYNTHETIC_ONLY",)), init=False)

    @property
    def population_stage(self):
        if self.population is None:
            return self.prefit
        if self.prefit.verdict is Verdict.INVALID:
            return self.prefit
        if self.population.eligible_ids:
            return Stage(Verdict.READY)
        return Stage(Verdict.INSUFFICIENT, ("NO_ELIGIBLE_PAIRS",))


def _stage(validation):
    return Stage(Verdict.READY if validation.status is Readiness.SUFFICIENT else Verdict(validation.status.value),
                 validation.reasons)


def _plan_stage(plan):
    if type(plan) is not FixturePlan or type(plan.window) is not DevelopmentWindow:
        return Stage(Verdict.INVALID, ("INVALID_SCHEMA_OR_TIME",))
    w = plan.window
    times = (plan.origin, w.train_start, w.evaluation_start, w.evaluation_end,
             plan.retrieved_at, plan.evaluated_at)
    if not all(_time(t) for t in times):
        return Stage(Verdict.INVALID, ("INVALID_SCHEMA_OR_TIME",))
    if any(plan.origin < end and w.evaluation_end > start for start, end in PROTECTED):
        return Stage(Verdict.BLOCKED, ("PROTECTED_PERIOD",))
    if not TARGET_START <= plan.origin <= w.train_start < w.evaluation_start < w.evaluation_end <= TARGET_END:
        return Stage(Verdict.INVALID, ("UNAUTHORIZED_DATES",))
    if (plan.origin % STEP or plan.retrieved_at > plan.evaluated_at
            or type(w.evidence) is not str or w.evidence != "SYNTHETIC_ONLY"
            or any(t % HOUR for t in (w.train_start, w.evaluation_start, w.evaluation_end))):
        return Stage(Verdict.INVALID, ("INVALID_SCHEMA_OR_TIME",))
    if type(plan.sources) is not tuple or len(plan.sources) != len(SYMBOLS):
        return Stage(Verdict.INVALID, ("SOURCE_CONFLICT",))
    errors = tuple(reason for source in plan.sources for reason in _snapshot_errors(source))
    if errors:
        return Stage(Verdict.INVALID, errors)
    if tuple(source.symbol for source in plan.sources) != SYMBOLS:
        return Stage(Verdict.INVALID, ("SOURCE_CONFLICT",))
    return Stage(Verdict.READY)


def _index(inputs, expected_type, ids):
    if type(inputs) is not tuple or len(inputs) > len(ids):
        return None
    indexed = {}
    for entry in inputs:
        if (type(entry) is not expected_type or type(getattr(entry, "row_id", None)) is not str
                or entry.row_id not in ids or entry.row_id in indexed):
            return None
        indexed[entry.row_id] = entry
    return indexed


def _source_wire(source):
    return (source.source_id, source.snapshot_id, source.revision, source.symbol, source.interval, source.source_ref)


def _scope_matches(scope, source, row, start, end):
    return (type(scope) is CandleScope and not _snapshot_errors(scope.snapshot)
            and scope.snapshot == source and all(_time(t) for t in (scope.start, scope.end, scope.decision_time))
            and (scope.start, scope.end, scope.decision_time) == (start, end, row.decision_time))


def _causal(plan, row, source, supplied, previous):
    if supplied is None:
        return Stage(Verdict.INSUFFICIENT, ("MISSING_PREFIX",)), None, None, ()
    if not _scope_matches(supplied.scope, source, row, plan.origin, row.label_start):
        return Stage(Verdict.INVALID, ("PREFIX_SCOPE_MISMATCH",)), None, None, ()
    result = assess_pinned_prefix(supplied.scope, supplied.approval, supplied.observations,
                                  evaluated_at=plan.evaluated_at, retrieved_at=plan.retrieved_at)
    stage = _stage(result.validation)
    if stage.verdict is not Verdict.READY:
        return stage, result.features, None, ()
    wire = tuple((row_commitment(o.version), o.proof.evidence_id, o.proof.available_at)
                 for o in supplied.observations)
    if wire[:len(previous)] != previous:
        return Stage(Verdict.INVALID, ("PREFIX_LINEAGE_CONFLICT",)), None, None, ()
    features = result.features
    grant = supplied.approval
    sha256 = commitment(("v2-fixture-causal-v1", _source_wire(source), plan.origin, row.decision_time,
                         supplied.scope.scope_id, grant.approval_id, grant.issued_at, grant.expires_at,
                         grant.max_rows, plan.retrieved_at, wire,
                         tuple(value.hex() for value in features.values), features.atr14.hex()))
    return stage, features, sha256, wire


def _funding(claim, source, row):
    if claim is None:
        return Stage(Verdict.INSUFFICIENT, ("FUNDING_COVERAGE_UNPROVEN",)), CoverageState.UNKNOWN, None
    if (type(claim) is not FundingClaim or type(claim.observations) is not tuple
            or len(claim.observations) > MAX_DECLARED_ROWS or not _plain_input(claim)):
        return Stage(Verdict.INVALID, ("INVALID_FUNDING_EVIDENCE",)), CoverageState.UNKNOWN, None
    if ((claim.symbol, claim.source_id, claim.revision, claim.start, claim.end) !=
            (row.symbol, source.source_id, source.revision, row.label_start, row.label_end)):
        return Stage(Verdict.INVALID, ("FUNDING_BINDING_MISMATCH",)), CoverageState.UNKNOWN, None
    result = assess_funding(claim)
    if result.state is CoverageState.KNOWN_NO_SETTLEMENT:
        return Stage(Verdict.BLOCKED, ("NO_SETTLEMENT_BRIDGE_DISABLED",)), result.state, None
    if result.state is not CoverageState.KNOWN_EVENTS:
        return _stage(result.validation), result.state, None
    wire = tuple((o.timestamp, str(o.rate), str(o.mark_price), o.timing_evidence.identity, o.mark_evidence.identity)
                 for o in claim.observations)
    digest = commitment(("v2-fixture-funding-v1", _source_wire(source), row.row_id, row.label_end,
                         result.state.value, claim.schedule.identity.identity, wire))
    return Stage(Verdict.READY), result.state, digest


def _pair(pair, row, prefix, horizon, funding_sha, cutoff):
    if pair is None:
        return Stage(Verdict.INSUFFICIENT, ("MISSING_PAIR",)), None
    if (type(pair) is not PairEvidence or type(pair.basis) is not str or pair.basis != "INVENTED_PAIR_VALIDITY_ONLY"
            or not all(_identity(v) for v in (pair.producer, pair.revision))
            or not _time(pair.available_at) or type(pair.actions) is not tuple or len(pair.actions) > 2
            or type(pair.row_id) is not str
            or not all(valid_commitment(v) for v in (pair.prefix_sha256, pair.horizon_sha256, pair.funding_sha256))):
        return Stage(Verdict.INVALID, ("INVALID_PAIR_EVIDENCE",)), None
    if (pair.row_id, pair.prefix_sha256, pair.horizon_sha256, pair.funding_sha256) != (
            row.row_id, prefix, horizon.sha256, funding_sha):
        return Stage(Verdict.INVALID, ("PAIR_LINEAGE_MISMATCH",)), None
    if pair.available_at < horizon.mature_at:
        return Stage(Verdict.INVALID, ("PAIR_PRECEDES_HORIZON_MATURITY",)), None
    if pair.available_at > cutoff:
        return Stage(Verdict.INSUFFICIENT, ("PAIR_EVIDENCE_LATE",)), None
    if any(type(a) is not ActionEvidence or type(a.side) is not str or a.side not in ("LONG", "SHORT")
           or not _identity(a.reference) or type(a.valid) is not bool for a in pair.actions):
        return Stage(Verdict.INVALID, ("INVALID_ACTION_EVIDENCE",)), None
    if len(pair.actions) < 2:
        return Stage(Verdict.INSUFFICIENT, ("MISSING_ACTION",)), None
    if tuple(a.side for a in pair.actions) != ("LONG", "SHORT"):
        return Stage(Verdict.INVALID, ("ACTION_PAIR_CONFLICT",)), None
    if not all(a.valid for a in pair.actions):
        return Stage(Verdict.INSUFFICIENT, ("PAIR_NOT_VALID",)), None
    digest = commitment((pair.basis, pair.row_id, prefix, horizon.sha256, funding_sha, pair.producer,
                         pair.revision, pair.available_at, tuple((a.side, a.reference) for a in pair.actions)))
    return Stage(Verdict.READY), digest


def _outcome(plan, entry, source, anchor, supplied, known, funding_inventory):
    row = entry.interval
    if entry.partition_reason != "ACCEPT":
        return PopulationEntry(row.row_id, Stage(Verdict.BLOCKED, (entry.partition_reason,)), row.label_end)
    if entry.partition != "train":
        return PopulationEntry(row.row_id, Stage(Verdict.BLOCKED, ("DEVELOPMENT_EVALUATION_ONLY",)), row.label_end)
    if entry.stage.verdict is not Verdict.READY:
        return PopulationEntry(row.row_id, entry.stage, row.label_end)
    if supplied is None:
        return PopulationEntry(row.row_id, Stage(Verdict.INSUFFICIENT, ("MISSING_HORIZON",)),
                               row.label_end, entry.prefix_sha256)
    if type(supplied.sealed) is not bool:
        return PopulationEntry(row.row_id, Stage(Verdict.INVALID, ("INVALID_SEAL",)), row.label_end)
    if supplied.sealed:
        return PopulationEntry(row.row_id, Stage(Verdict.BLOCKED, ("SEALED_OUTCOME",)), row.label_end)
    if not _scope_matches(supplied.scope, source, row, row.label_start, row.label_end):
        return PopulationEntry(row.row_id, Stage(Verdict.INVALID, ("HORIZON_SCOPE_MISMATCH",)), row.label_end)
    horizon = assess_horizon(supplied.scope, supplied.approval, anchor, supplied.observations,
                             evaluated_at=plan.evaluated_at, audit_cutoff=plan.audit_cutoff)
    if horizon.validation.status is not Readiness.SUFFICIENT:
        return PopulationEntry(row.row_id, _stage(horizon.validation), row.label_end, entry.prefix_sha256)
    versions = {o.version.candle.open_time: row_commitment(o.version) for o in supplied.observations}
    if any(t in known and known[t] != sha for t, sha in versions.items()):
        return PopulationEntry(row.row_id, Stage(Verdict.INVALID, ("HORIZON_LINEAGE_CONFLICT",)), row.label_end)
    known.update(versions)
    stage, state, funding_sha = _funding(supplied.funding, source, row)
    pair_sha = None
    if stage.verdict is Verdict.READY:
        events = tuple((e.timestamp, str(e.rate), str(e.mark_price)) for e in supplied.funding.observations)
        funding_inventory[:] = [(end, prior) for end, prior in funding_inventory if end > row.label_start]
        if any(tuple(e for e in prior if e[0] >= row.label_start) != tuple(e for e in events if e[0] < end)
               for end, prior in funding_inventory):
            stage = Stage(Verdict.INVALID, ("FUNDING_LINEAGE_CONFLICT",))
        else:
            funding_inventory.append((row.label_end, events))
            stage, pair_sha = _pair(supplied.pair, row, entry.prefix_sha256, horizon, funding_sha, plan.audit_cutoff)
    return PopulationEntry(row.row_id, stage, row.label_end, entry.prefix_sha256, horizon.sha256,
                           horizon.mature_at, state, funding_sha, pair_sha)


def run_workflow(plan, prefixes, outcomes):
    """Rebuild the full paired ledger, then select a separate inert population."""
    try:
        plan_stage = _plan_stage(plan)
    except AttributeError:
        return WorkflowResult(Stage(Verdict.INVALID, ("INVALID_SCHEMA_OR_TIME",)))
    if plan_stage.verdict is not Verdict.READY:
        return WorkflowResult(plan_stage)
    window = plan.window
    slots = tuple(IntervalRow(symbol, t - 1, t + HORIZON)
                  for t in range(window.train_start + HOUR, window.evaluation_end + HOUR, HOUR) for symbol in SYMBOLS)
    ids = {row.row_id for row in slots}
    causal_inputs = _index(prefixes, PrefixInput, ids)
    sources = dict(zip(SYMBOLS, plan.sources))
    lineage = {symbol: () for symbol in SYMBOLS}
    ledger, anchors = [], {}
    for row in slots:
        supplied = None if causal_inputs is None else causal_inputs.get(row.row_id)
        try:
            if causal_inputs is None:
                stage, features, sha, wire = Stage(Verdict.INVALID, ("PREFIX_INVENTORY_CONFLICT",)), None, None, ()
            else:
                stage, features, sha, wire = _causal(plan, row, sources[row.symbol], supplied, lineage[row.symbol])
        except AttributeError:
            stage, features, sha, wire = Stage(Verdict.INVALID, ("INVALID_SCHEMA_OR_TIME",)), None, None, ()
        if wire:
            lineage[row.symbol] = wire
            anchors[row.row_id] = supplied.observations[-1].version
        partition = "train" if row.decision_time < window.evaluation_start else "development_evaluation"
        ledger.append(CausalEntry(row, stage, "UNSCORED" if sha else "NO TRADE", partition,
                                  partition_reason(row, window, partition), features, sha))
    causal = tuple(ledger)
    verdicts = {entry.stage.verdict for entry in causal}
    status = (Stage(Verdict.INVALID, ("CAUSAL_REFUSALS",)) if Verdict.INVALID in verdicts else
              Stage(Verdict.INSUFFICIENT, ("CAUSAL_REFUSALS",)) if Verdict.INSUFFICIENT in verdicts else Stage(Verdict.READY))
    cutoff = getattr(plan, "audit_cutoff", None)
    if not _time(cutoff) or cutoff > plan.evaluated_at:
        return WorkflowResult(status, causal, prefit=Stage(Verdict.INVALID, ("INVALID_AUDIT_CUTOFF",)))
    outcome_inputs = _index(outcomes, OutcomeInput, ids)
    if outcome_inputs is None:
        return WorkflowResult(status, causal, prefit=Stage(Verdict.INVALID, ("OUTCOME_INVENTORY_CONFLICT",)))
    known = {symbol: {plan.origin + i * STEP: item[0] for i, item in enumerate(wire)}
             for symbol, wire in lineage.items()}
    funding_inventory = {symbol: [] for symbol in SYMBOLS}
    entries, selected = [], []
    for entry in causal:
        row = entry.interval
        try:
            result = _outcome(plan, entry, sources[row.symbol], anchors.get(row.row_id),
                              outcome_inputs.get(row.row_id), known[row.symbol], funding_inventory[row.symbol])
        except (AttributeError, ArithmeticError, TypeError, ValueError):
            result = PopulationEntry(row.row_id, Stage(Verdict.INVALID, ("INVALID_OUTCOME_EVIDENCE",)), row.label_end)
        entries.append(result)
        if result.stage.verdict is Verdict.READY:
            selected.append(row)
    eligible = tuple(row.row_id for row in selected)
    wire = tuple((e.row_id, e.stage.verdict.value, e.stage.reasons, e.horizon_end, e.prefix_sha256, e.horizon_sha256,
                  e.mature_at, e.funding_state.value, e.funding_sha256, e.pair_sha256) for e in entries)
    sha = commitment(("v2-fixture-population-v1", tuple(_source_wire(s) for s in plan.sources), plan.origin,
                      (window.train_start, window.evaluation_start, window.evaluation_end), plan.audit_cutoff,
                      eligible, wire, "INVENTED_DECLARATIONS_ONLY"))
    receipt = TrainingPopulationReceipt(window, plan.sources, plan.origin, plan.audit_cutoff, eligible, tuple(entries), sha)
    if any(e.stage.verdict is Verdict.INVALID for e in entries):
        return WorkflowResult(status, causal, receipt, Stage(Verdict.INVALID, ("TRAINING_EVIDENCE_CONFLICT",)))
    if eligible:
        TrainingReceipt(eligible, ids_hash(eligible), window)
    prefit = (Stage(Verdict.READY) if sample_gate(selected, "train")["status"] == "SUFFICIENT" else
              Stage(Verdict.INSUFFICIENT, ("TRAINING_SAMPLE_MINIMUM",)))
    return WorkflowResult(status, causal, receipt, prefit)


def verify_population(expected_sha256, plan, prefixes, outcomes):
    """Replay raw invented inputs and check the candidate receipt commitment."""
    result = run_workflow(plan, prefixes, outcomes)
    if (not valid_commitment(expected_sha256) or result.population is None
            or result.population.sha256 != expected_sha256):
        return Stage(Verdict.INVALID, ("TRAINING_RECEIPT_MISMATCH",))
    return result.prefit
