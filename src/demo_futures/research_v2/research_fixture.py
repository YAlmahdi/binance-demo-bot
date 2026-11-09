"""Fixed invented inputs for the offline V2 integration command."""
import argparse
from dataclasses import asdict
from decimal import Decimal
import json

from ..data import Candle
from .config import HOUR, HORIZON, STEP, SYMBOLS
from .contracts import EvidenceIdentity
from .funding_contracts import CoverageState, FundingClaim, ScheduleEvidence, SettlementObservation
from .historical_scope import (
    CandleScope, CandleVersion, SliceApproval, SnapshotIdentity, VersionEvidence, VersionObservation, row_commitment,
)
from .horizon_coverage import assess_horizon
from .research_workflow import (
    ActionEvidence, FixturePlan, OutcomeInput, PairEvidence, PrefixInput, Verdict, _funding, run_workflow,
)
from .source_contracts import OriginalAvailability, TARGET_START
from .validation import DevelopmentWindow


def _observe(version, assertion):
    proof = VersionEvidence(f"proof-{version.row_id}", assertion, row_commitment(version),
                            version.candle.close_time + 1)
    state = (OriginalAvailability.VERIFIED if assertion == "ORIGINAL_ASOF_RECEIPT"
             else OriginalAvailability.UNKNOWN)
    return VersionObservation(version, proof, state)


def fixture_inputs():
    """Return only invented, materialized declarations. No loader or fitted inputs."""
    origin = TARGET_START + HOUR
    start = origin + 17 * HOUR
    window = DevelopmentWindow(start, start + 11 * HOUR, start + 16 * HOUR)
    cutoff = window.evaluation_end + HORIZON
    sources = tuple(SnapshotIdentity(f"invented-{symbol}", "fixture-snapshot", "revision-1", symbol,
                                     "fixture-source-proof") for symbol in SYMBOLS)
    plan = FixturePlan(window, origin, sources, cutoff, cutoff, cutoff)

    def grant(scope):
        return SliceApproval("fixture-approval", scope, start, cutoff + HOUR, 512)

    versions = {}
    prefixes = []
    for offset, source in enumerate(sources):
        ordered = []
        for i, opened in enumerate(range(origin, window.evaluation_end, STEP)):
            price = 100.0 + 20 * offset + (i % 36) / 8
            candle = Candle(opened, price, price + 2, price - 1, price + 1, 10.0, opened + STEP - 1)
            ordered.append(CandleVersion(source, f"candle-{i}", "version-1", candle))
        versions[source.symbol] = tuple(ordered)
        original = tuple(_observe(version, "ORIGINAL_ASOF_RECEIPT") for version in ordered)
        for boundary in range(start + HOUR, window.evaluation_end + HOUR, HOUR):
            scope = CandleScope("fixture-prefix", source, origin, boundary, boundary - 1)
            prefixes.append(PrefixInput(f"{source.symbol}:{boundary - 1}", scope, grant(scope),
                                        original[:(boundary - origin) // STEP]))
    prefixes = tuple(prefixes)
    causal = run_workflow(plan, prefixes, ()).causal
    by_symbol = {source.symbol: source for source in sources}
    outcomes = []
    for entry in causal:
        if entry.partition != "train" or entry.partition_reason != "ACCEPT" or entry.stage.verdict is not Verdict.READY:
            continue
        row = entry.interval
        source = by_symbol[row.symbol]
        ordered = versions[row.symbol]
        index = (row.label_start - origin) // STEP
        anchor = ordered[index - 1]
        scope = CandleScope("fixture-horizon", source, row.label_start, row.label_end, row.decision_time,
                            anchor_sha256=row_commitment(anchor))
        approval = grant(scope)
        observations = tuple(_observe(version, "AUDIT_OBSERVATION")
                             for version in ordered[index:index + HORIZON // STEP])
        horizon = assess_horizon(scope, approval, anchor, observations, evaluated_at=cutoff, audit_cutoff=cutoff)

        def evidence(assertion):
            return EvidenceIdentity(f"fixture-{assertion}", source.source_id, source.revision, assertion)

        # One event per symbol lies inside every overlapping fixture horizon.
        settlement = start + HORIZON + STEP
        event = SettlementObservation(settlement, Decimal("0.0001"), Decimal("100"),
                                      evidence("SETTLEMENT_TIME_AND_RATE"), evidence("SETTLEMENT_MARK"))
        schedule = ScheduleEvidence(row.symbol, row.label_start, row.label_end, evidence("SETTLEMENT_SCHEDULE"),
                                    (settlement,), True)
        funding = FundingClaim(row.symbol, row.label_start, row.label_end, source.source_id, source.revision,
                               CoverageState.KNOWN_EVENTS, (event,), schedule)
        _, _, funding_sha = _funding(funding, source, row)
        pair = PairEvidence(row.row_id, entry.prefix_sha256, horizon.sha256, funding_sha, "fixture-producer",
                            "fixture-revision", horizon.mature_at,
                            (ActionEvidence("LONG", "fixture-long", True), ActionEvidence("SHORT", "fixture-short", True)))
        outcomes.append(OutcomeInput(row.row_id, scope, approval, observations, funding, pair))
    return plan, prefixes, tuple(outcomes)


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    result = run_workflow(*fixture_inputs())
    print(json.dumps({"evidence": "SYNTHETIC_ONLY", "population_stage": asdict(result.population_stage),
                      **asdict(result)}, indent=2, sort_keys=True))
    return int(result.causal_stage.verdict is not Verdict.READY or result.population_stage.verdict is not Verdict.READY)


if __name__ == "__main__":
    raise SystemExit(main())
