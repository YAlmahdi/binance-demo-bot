"""Integration acceptance checks on invented inputs with no payoff production."""
from contextlib import redirect_stdout
from dataclasses import replace
from io import StringIO
import json
import unittest
from unittest.mock import patch

from demo_futures.research_v2.config import HOUR, HORIZON, STEP
from demo_futures.research_v2.contracts import EvidenceIdentity
from demo_futures.research_v2.funding_contracts import CoverageState
from demo_futures.research_v2.historical_scope import row_commitment
from demo_futures.research_v2.research_fixture import fixture_inputs, main
from demo_futures.research_v2.research_workflow import OutcomeInput, Stage, Verdict, _funding, run_workflow, verify_population
from demo_futures.research_v2.source_contracts import AvailabilityMode, PROTECTED


def rewrite_volume(prefix, index):
    observed = prefix.observations[index]
    version = observed.version
    version = replace(version, candle=replace(version.candle, volume=99.0))
    changed = replace(observed, version=version, proof=replace(observed.proof, row_sha256=row_commitment(version)))
    observations = prefix.observations[:index] + (changed,) + prefix.observations[index + 1:]
    return replace(prefix, observations=observations)


class ResearchWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan, cls.prefixes, cls.outcomes = fixture_inputs()
        cls.baseline = run_workflow(cls.plan, cls.prefixes, cls.outcomes)

    def run_case(self, *, plan=None, prefixes=None, outcomes=None):
        return run_workflow(self.plan if plan is None else plan, self.prefixes if prefixes is None else prefixes,
                            self.outcomes if outcomes is None else outcomes)

    def test_complete_ledger_and_separate_candidate_receipt(self):
        result = self.baseline
        self.assertEqual(result.causal_stage, Stage(Verdict.READY))
        self.assertEqual(result.population_stage, Stage(Verdict.READY))
        self.assertEqual(result.prefit, Stage(Verdict.INSUFFICIENT, ("TRAINING_SAMPLE_MINIMUM",)))
        self.assertEqual(result.fit, Stage(Verdict.BLOCKED, ("SYNTHETIC_ONLY",)))
        self.assertEqual(len(result.causal), 32)
        self.assertEqual([row.interval.symbol for row in result.causal], ["BTCUSDT", "ETHUSDT"] * 16)
        self.assertTrue(all(row.decision == "UNSCORED" for row in result.causal))
        receipt = result.population
        self.assertEqual(receipt.eligible_ids, tuple(o.row_id for o in self.outcomes))
        self.assertEqual(len(receipt.eligible_ids), 6)
        self.assertEqual(len(receipt.entries), len(result.causal))
        self.assertEqual(receipt.financial_evidence, "INVENTED_DECLARATIONS_ONLY")
        self.assertEqual(receipt.financial_validity, "NOT ESTABLISHED")
        self.assertTrue(all(row.pair_sha256 and row.mature_at == row.horizon_end for row in receipt.entries[:6]))
        with self.assertRaises(TypeError):
            bool(receipt)

    def test_missing_horizon_funding_and_pair_exclude_only_their_rows(self):
        _, without_funding, without_pair, *rest = self.outcomes
        result = self.run_case(outcomes=(replace(without_funding, funding=None), replace(without_pair, pair=None), *rest))
        self.assertEqual(result.causal, self.baseline.causal)
        self.assertEqual(result.population.eligible_ids, tuple(o.row_id for o in rest))
        self.assertEqual([r.stage.reasons for r in result.population.entries[:3]],
                         [("MISSING_HORIZON",), ("FUNDING_COVERAGE_UNPROVEN",), ("MISSING_PAIR",)])
        self.assertTrue(all(r.pair_sha256 is None for r in result.population.entries[:3]))

    def test_action_pair_incomplete_invalid_or_conflicting(self):
        first, second, third, *rest = self.outcomes
        long, short = first.pair.actions
        altered = (replace(first, pair=replace(first.pair, actions=(long,))),
                   replace(second, pair=replace(second.pair, actions=(long, replace(short, valid=False)))),
                   replace(third, pair=replace(third.pair, actions=(long, long))))
        result = self.run_case(outcomes=(*altered, *rest))
        self.assertEqual(result.causal, self.baseline.causal)
        self.assertEqual(result.population.eligible_ids, tuple(o.row_id for o in rest))
        self.assertEqual([e.stage.reasons for e in result.population.entries[:3]],
                         [("MISSING_ACTION",), ("PAIR_NOT_VALID",), ("ACTION_PAIR_CONFLICT",)])
        self.assertIs(result.prefit.verdict, Verdict.INVALID)

    def test_partition_equalities_and_purge_before_outcome_inspection(self):
        B = self.plan.window.evaluation_start
        E = self.plan.window.evaluation_end
        rows = {entry.interval.row_id: entry for entry in self.baseline.causal}
        row = lambda t: rows[f"BTCUSDT:{t - 1}"]
        equal_train = row(B - 2 * HORIZON)
        too_late = row(B - 2 * HORIZON + HOUR)
        purge_overlap = row(B - HORIZON + HOUR)
        equal_eval = row(E - HORIZON)
        self.assertEqual(equal_train.interval.label_end, B - HORIZON)
        self.assertEqual(equal_train.partition_reason, "ACCEPT")
        self.assertEqual(too_late.partition_reason, "FOUR_HOUR_BUFFER")
        self.assertEqual(purge_overlap.partition_reason, "PURGED_OVERLAP")
        self.assertEqual(equal_eval.partition, "development_evaluation")
        self.assertEqual(equal_eval.partition_reason, "ACCEPT")
        self.assertEqual(row(E - HORIZON + HOUR).partition_reason, "INCOMPLETE_EVALUATION_HORIZON")
        foreign = tuple(OutcomeInput(entry.interval.row_id, object(), object(), object(), object(), object())
                        for entry in (too_late, purge_overlap, equal_eval))
        self.assertEqual(self.run_case(outcomes=self.outcomes + foreign), self.baseline)

    def test_future_only_causal_mutation_does_not_change_training_selection(self):
        latest = self.prefixes[-1]
        altered = rewrite_volume(latest, len(latest.observations) - 1)
        result = self.run_case(prefixes=self.prefixes[:-1] + (altered,))
        self.assertEqual(result.causal[:-1], self.baseline.causal[:-1])
        self.assertNotEqual(result.causal[-1].features, self.baseline.causal[-1].features)
        self.assertEqual(result.population, self.baseline.population)
        self.assertEqual(result.prefit, self.baseline.prefit)

    def test_replay_is_order_independent_and_binds_outcome_revision(self):
        reverse = self.run_case(prefixes=self.prefixes[::-1], outcomes=self.outcomes[::-1])
        self.assertEqual(reverse, self.baseline)
        digest = self.baseline.population.sha256
        self.assertEqual(verify_population(digest, self.plan, self.prefixes, self.outcomes), self.baseline.prefit)
        first = self.outcomes[0]
        changed = (replace(first, pair=replace(first.pair, revision="another-revision")),) + self.outcomes[1:]
        self.assertEqual(self.run_case(outcomes=changed).population.eligible_ids, self.baseline.population.eligible_ids)
        self.assertEqual(verify_population(digest, self.plan, self.prefixes, changed),
                         Stage(Verdict.INVALID, ("TRAINING_RECEIPT_MISMATCH",)))
        stale = (replace(first, pair=replace(first.pair, funding_sha256="0" * 64)),) + self.outcomes[1:]
        self.assertEqual(self.run_case(outcomes=stale).population.entries[0].stage.reasons,
                         ("PAIR_LINEAGE_MISMATCH",))

    def test_overlapping_prefix_conflict_leaves_prior_opportunity_unchanged(self):
        first, second, *rest = self.prefixes
        result = self.run_case(prefixes=(first, rewrite_volume(second, 0), *rest))
        by_id = {e.interval.row_id: e for e in result.causal}
        self.assertEqual(by_id[first.row_id], self.baseline.causal[0])
        self.assertEqual(by_id[second.row_id].stage.reasons, ("PREFIX_LINEAGE_CONFLICT",))
        self.assertEqual(by_id[second.row_id].decision, "NO TRADE")
        self.assertNotIn(second.row_id, result.population.eligible_ids)
        self.assertIs(result.prefit.verdict, Verdict.INVALID)

    def test_late_sealed_or_immature_outcomes_preserve_causal_ledger(self):
        first, second, *rest = self.outcomes
        late = replace(first, pair=replace(first.pair, available_at=self.plan.audit_cutoff + 1))
        sealed = OutcomeInput(second.row_id, object(), object(), object(), object(), object(), sealed=True)
        result = self.run_case(outcomes=(late, sealed, *rest))
        self.assertEqual(result.causal, self.baseline.causal)
        self.assertEqual([e.stage.reasons for e in result.population.entries[:2]],
                         [("PAIR_EVIDENCE_LATE",), ("SEALED_OUTCOME",)])
        immature = self.run_case(plan=replace(self.plan, audit_cutoff=first.pair.available_at - 1))
        self.assertEqual(immature.causal, self.baseline.causal)
        self.assertIn("HORIZON_NOT_MATURE", immature.population.entries[0].stage.reasons)
        invalid = self.run_case(plan=replace(self.plan, audit_cutoff=self.plan.evaluated_at + 1))
        self.assertEqual(invalid.causal, self.baseline.causal)
        self.assertEqual(invalid.prefit, Stage(Verdict.INVALID, ("INVALID_AUDIT_CUTOFF",)))

    def test_horizon_conflicting_version_refuses_without_changing_causal_rows(self):
        first, *rest = self.outcomes
        altered = rewrite_volume(first, 0)
        result = self.run_case(outcomes=(altered, *rest))
        self.assertEqual(result.causal, self.baseline.causal)
        self.assertEqual(result.population.entries[0].stage.reasons, ("HORIZON_LINEAGE_CONFLICT",))
        self.assertIs(result.prefit.verdict, Verdict.INVALID)

    def test_funding_no_settlement_does_not_supply_financial_evidence(self):
        first, *rest = self.outcomes
        funding = first.funding
        proof = EvidenceIdentity("fixture-empty", funding.source_id, funding.revision, "NO_SETTLEMENT")
        empty = replace(funding, state=CoverageState.KNOWN_NO_SETTLEMENT, observations=(),
                        schedule=replace(funding.schedule, identity=proof, expected_settlements=()))
        result = self.run_case(outcomes=(replace(first, funding=empty), *rest))
        self.assertEqual(result.causal, self.baseline.causal)
        row = result.population.entries[0]
        self.assertEqual(row.stage, Stage(Verdict.BLOCKED, ("NO_SETTLEMENT_BRIDGE_DISABLED",)))
        self.assertIs(row.funding_state, CoverageState.KNOWN_NO_SETTLEMENT)
        self.assertIsNone(row.funding_sha256)
        self.assertNotIn(first.row_id, result.population.eligible_ids)

    def test_overlapping_funding_claims_cannot_disagree_under_one_source(self):
        item = self.outcomes[2]
        funding = item.funding
        event = funding.observations[0]
        changed = replace(funding, observations=(replace(event, timestamp=event.timestamp + 1),),
                          schedule=replace(funding.schedule, expected_settlements=(event.timestamp + 1,)))
        _, _, digest = _funding(changed, self.plan.sources[0], self.baseline.causal[2].interval)
        rebound = replace(item, funding=changed, pair=replace(item.pair, funding_sha256=digest))
        result = self.run_case(outcomes=self.outcomes[:2] + (rebound,) + self.outcomes[3:])
        self.assertEqual(result.causal, self.baseline.causal)
        self.assertEqual(result.population.entries[2].stage.reasons, ("FUNDING_LINEAGE_CONFLICT",))
        self.assertIs(result.prefit.verdict, Verdict.INVALID)

    def test_protected_plan_and_injected_protected_timestamp_are_refused_early(self):
        protected = PROTECTED[0][0]
        plan = replace(self.plan, window=replace(self.plan.window, evaluation_end=protected + HOUR))
        with patch("demo_futures.research_v2.research_workflow.assess_pinned_prefix") as prefix:
            result = run_workflow(plan, object(), object())
            self.assertEqual(result.causal_stage, Stage(Verdict.BLOCKED, ("PROTECTED_PERIOD",)))
            self.assertEqual(result.causal, ())
            prefix.assert_not_called()
        first = self.prefixes[0]
        observed = first.observations[0]
        candle = replace(observed.version.candle, open_time=protected, close_time=protected + STEP - 1)
        raw = replace(observed, version=replace(observed.version, candle=candle))
        with patch("demo_futures.research_v2.historical_scope._candle_values") as inspect:
            rejected = self.run_case(prefixes=(replace(first, observations=(raw,)),), outcomes=())
            self.assertEqual(rejected.causal[0].stage.reasons, ("PROTECTED_PERIOD",))
            self.assertEqual(len(rejected.causal), len(self.baseline.causal))
            inspect.assert_not_called()

    def test_strict_refusals_and_inactive_approximation_are_no_trade(self):
        first, second, third, *rest = self.prefixes
        unknown = replace(first.observations[-1], proof=None,
                          original_availability=type(first.observations[-1].original_availability).UNKNOWN)
        final = second.observations[-1]
        late = replace(final, proof=replace(final.proof, available_at=second.scope.end + 1))
        inactive = replace(third.scope, mode=AvailabilityMode.EXPLORATORY_CLOSED_BAR_APPROXIMATION)
        result = self.run_case(prefixes=(replace(first, observations=first.observations[:-1] + (unknown,)),
            replace(second, observations=second.observations[:-1] + (late,)),
            replace(third, scope=inactive, approval=replace(third.approval, scope=inactive)), *rest))
        by_id = {e.interval.row_id: e for e in result.causal}
        for item, reason in ((first, "ORIGINAL_RECEIPT_UNKNOWN"), (second, "RECEIPT_LATE"),
                             (third, "UNAPPROVED_SCOPE")):
            self.assertIn(reason, by_id[item.row_id].stage.reasons)
            self.assertEqual(by_id[item.row_id].decision, "NO TRADE")
            self.assertNotIn(item.row_id, result.population.eligible_ids)
        self.assertEqual(len(result.causal), len(self.baseline.causal))

    def test_entry_point_is_reproducible_and_producers_are_never_called(self):
        output = StringIO()
        with redirect_stdout(output), patch("sys.argv", ["research_fixture"]), \
             patch("demo_futures.research_v2.labels.paired_outcome", side_effect=AssertionError) as producer, \
             patch("demo_futures.backtest.BacktestEngine.run", side_effect=AssertionError) as simulator, \
             patch("demo_futures.research_v2.preprocessing.estimate_preprocessing", side_effect=AssertionError) as fit:
            self.assertEqual(main(), 0)
            for consumer in (producer, simulator, fit):
                consumer.assert_not_called()
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["population"]["sha256"], self.baseline.population.sha256)
        self.assertEqual(payload["fit"]["verdict"], "BLOCKED")
        self.assertEqual(len(payload["causal"]), 32)
