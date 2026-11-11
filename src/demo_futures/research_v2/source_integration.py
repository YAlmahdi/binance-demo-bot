"""Inert source binding for supplied invented records. No reader or activation."""
from dataclasses import dataclass, fields, is_dataclass
from decimal import Decimal
from enum import Enum
import json

from .historical_scope import CandleScope, SliceApproval, commitment, preflight, row_commitment, valid_commitment
from .research_workflow import FixturePlan, PrefixInput, OutcomeInput, Verdict, WorkflowResult, _plan_stage, run_workflow
from .contracts import Readiness
from .config import HORIZON, STEP


@dataclass(frozen=True)
class SliceBinding:
    channel: str
    row_id: str
    scope: CandleScope
    approval: SliceApproval
    row_versions: tuple[str, ...]
    payload_sha256: str


@dataclass(frozen=True)
class SourceBinding:
    authority_ref: str
    authority_basis: str
    immutable: bool
    isolation: str
    operations: tuple[str, ...]
    schema: str
    plan_sha256: str
    slices: tuple[SliceBinding, ...]
    max_pages: int
    max_rows: int


@dataclass(frozen=True)
class BindingResult:
    verdict: str
    reasons: tuple[str, ...]
    workflow: WorkflowResult | None = None
    evidence: str = "SYNTHETIC_ONLY"
    actual_authority: str = "UNVERIFIED"


def _wire(value):
    if value is None or type(value) in (str, int, bool):
        return value
    if isinstance(value, Enum):
        return [type(value).__name__, value.value]
    if type(value) is float:
        return ["float", value.hex()]
    if type(value) is Decimal:
        return ["Decimal", str(value)]
    if type(value) is tuple:
        return [_wire(item) for item in value]
    if is_dataclass(value) and type(value).__module__ in (
        "demo_futures.data", "demo_futures.research_v2.historical_scope",
        "demo_futures.research_v2.research_workflow", "demo_futures.research_v2.funding_contracts",
        "demo_futures.research_v2.contracts", "demo_futures.research_v2.validation",
    ):
        return [type(value).__name__, [[field.name, _wire(getattr(value, field.name))]
                                      for field in fields(value)]]
    raise ValueError("Materialized immutable synthetic records required")


def identity(value):
    return commitment(_wire(value))


def preauthorize(binding, plan):
    """Metadata-only validation, before any supplied record inspection or hash."""
    if type(binding) is not SourceBinding or type(plan) is not FixturePlan:
        return ("INVALID_BINDING",)
    try:
        stage = _plan_stage(plan)
    except (AttributeError, TypeError, ValueError):
        return ("INVALID_PLAN",)
    if stage.verdict is not Verdict.READY:
        return stage.reasons
    if (any(type(value) is not str for value in (
            binding.authority_ref, binding.authority_basis, binding.isolation, binding.schema))
            or type(binding.operations) is not tuple
            or any(type(value) is not str for value in binding.operations)
            or not binding.authority_ref
            or binding.authority_basis != "SYNTHETIC_ASSERTION"
            or binding.immutable is not True or binding.isolation != "DECLARED_PHYSICALLY_ISOLATED"
            or binding.operations != ("BIND_SUPPLIED_RECORDS",)
            or binding.schema != "V2_CANONICAL_CANDLE_V1"):
        return ("AUTHORITY_ISOLATION_OR_OPERATION_MISSING",)
    if (type(binding.max_pages) is not int or type(binding.max_rows) is not int
            or binding.max_pages <= 0 or binding.max_rows <= 0
            or type(binding.slices) is not tuple or not binding.slices
            or len(binding.slices) > binding.max_pages or not valid_commitment(binding.plan_sha256)):
        return ("INVALID_RESOURCE_OR_PLAN_BINDING",)
    keys = set()
    total = 0
    for item in binding.slices:
        if type(item) is not SliceBinding or item.channel not in ("prefix", "horizon") or type(item.row_id) is not str:
            return ("INVALID_SLICE",)
        checked = preflight(item.scope, item.approval, evaluated_at=plan.evaluated_at)
        if checked.status is not Readiness.SUFFICIENT:
            return checked.reasons
        scope = item.scope
        if scope.snapshot not in plan.sources or (item.channel == "prefix" and scope.start != plan.origin):
            return ("SOURCE_OR_ORIGIN_MISMATCH",)
        if (item.channel == "prefix" and scope.end != scope.decision_time + 1
                or item.channel == "horizon" and (
                    scope.start != scope.decision_time + 1 or scope.end - scope.start != HORIZON)):
            return ("DEPENDENCY_SPAN_MISMATCH",)
        key = (item.channel, item.row_id)
        if key in keys:
            return ("DUPLICATE_SLICE",)
        keys.add(key)
        count = (scope.end - scope.start) // STEP
        if (type(item.row_versions) is not tuple or len(item.row_versions) != count
                or any(not valid_commitment(value) for value in item.row_versions)
                or not valid_commitment(item.payload_sha256) or count > item.approval.max_rows):
            return ("ROW_VERSION_OR_SLICE_BUDGET",)
        total += count
    return () if total <= binding.max_rows else ("TOTAL_ROW_BUDGET",)


def bind_source(binding, plan, prefixes, outcomes):
    reasons = preauthorize(binding, plan)
    if reasons:
        return BindingResult("BLOCKED", reasons)
    if type(prefixes) is not tuple or type(outcomes) is not tuple:
        return BindingResult("BLOCKED", ("MATERIALIZED_INPUT_REQUIRED",))
    records = tuple(("prefix", value) for value in prefixes) + tuple(("horizon", value) for value in outcomes)
    if len(records) != len(binding.slices):
        return BindingResult("BLOCKED", ("PAGE_INVENTORY_MISMATCH",))
    try:
        if identity(plan) != binding.plan_sha256:
            return BindingResult("BLOCKED", ("PLAN_MUTATION",))
        for (channel, record), pinned in zip(records, binding.slices):
            expected_type = PrefixInput if channel == "prefix" else OutcomeInput
            if (type(record) is not expected_type or channel != pinned.channel
                    or record.row_id != pinned.row_id or record.scope != pinned.scope
                    or record.approval != pinned.approval):
                return BindingResult("BLOCKED", ("SLICE_BINDING_MISMATCH",))
            if (type(record.observations) is not tuple
                    or len(record.observations) != len(pinned.row_versions)):
                return BindingResult("BLOCKED", ("INCOMPLETE_RECORDS",))
            if (tuple(row_commitment(row.version) for row in record.observations) != pinned.row_versions
                    or identity(record) != pinned.payload_sha256):
                return BindingResult("BLOCKED", ("REPLAY_MUTATION",))
    except (AttributeError, TypeError, ValueError):
        return BindingResult("BLOCKED", ("INVALID_RECORDS",))
    workflow = run_workflow(plan, prefixes, outcomes)
    return BindingResult("BOUND", (), workflow)


def fixture_binding(plan, prefixes, outcomes):
    """Declare commitments over invented fixtures already supplied by the caller."""
    slices = tuple(SliceBinding(channel, record.row_id, record.scope, record.approval,
                               tuple(row_commitment(row.version) for row in record.observations),
                               identity(record))
                   for channel, records in (("prefix", prefixes), ("horizon", outcomes)) for record in records)
    return SourceBinding("invented-authority", "SYNTHETIC_ASSERTION", True,
                         "DECLARED_PHYSICALLY_ISOLATED", ("BIND_SUPPLIED_RECORDS",),
                         "V2_CANONICAL_CANDLE_V1", identity(plan), slices, len(slices),
                         sum(len(item.row_versions) for item in slices))


def main():
    from dataclasses import replace
    from .research_fixture import fixture_inputs
    plan, prefixes, outcomes = fixture_inputs()
    binding = fixture_binding(plan, prefixes, outcomes)
    accepted = bind_source(binding, plan, prefixes, outcomes)
    denied = bind_source(replace(binding, authority_ref=""), plan, prefixes, outcomes)
    print(json.dumps({"evidence": "SYNTHETIC_ONLY", "binding": accepted.verdict,
                      "scheduled": len(accepted.workflow.causal),
                      "eligible_ids": accepted.workflow.population.eligible_ids,
                      "population_sha256": accepted.workflow.population.sha256,
                      "fit": accepted.workflow.fit.verdict,
                      "refusal": denied.reasons}, sort_keys=True))


if __name__ == "__main__":
    main()
