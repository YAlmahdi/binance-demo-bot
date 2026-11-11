import unittest
from dataclasses import replace
from unittest.mock import patch

from demo_futures.research_v2.research_fixture import fixture_inputs
from demo_futures.research_v2.research_workflow import run_workflow, Verdict
from demo_futures.research_v2.source_contracts import PROTECTED
from demo_futures.research_v2.source_integration import bind_source, fixture_binding


class SourceIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan, cls.prefixes, cls.outcomes = fixture_inputs()
        cls.binding = fixture_binding(cls.plan, cls.prefixes, cls.outcomes)

    def run_bound(self, binding=None, plan=None, prefixes=None, outcomes=None):
        return bind_source(self.binding if binding is None else binding,
                           self.plan if plan is None else plan,
                           self.prefixes if prefixes is None else prefixes,
                           self.outcomes if outcomes is None else outcomes)

    def test_success_preserves_receipt_and_denominators(self):
        result = self.run_bound()
        expected = run_workflow(self.plan, self.prefixes, self.outcomes)
        self.assertEqual(result.verdict, "BOUND")
        self.assertEqual(result.workflow, expected)
        self.assertEqual(len(expected.causal), 32)
        self.assertEqual(len(expected.population.eligible_ids), 6)
        self.assertEqual(expected.fit.verdict, Verdict.BLOCKED)
        self.assertEqual(result, self.run_bound())

    def test_authority_isolation_operations_and_schema(self):
        for change in ({"authority_ref": ""}, {"authority_basis": "VERIFIED"},
                       {"isolation": "UNKNOWN"}, {"immutable": False},
                       {"operations": ("OPEN_FILE",)}, {"schema": "other"}):
            with self.subTest(change=change):
                self.assertEqual(self.run_bound(replace(self.binding, **change)).verdict, "BLOCKED")

    def test_scope_identity_revision_projection_origin_and_horizon(self):
        first = self.binding.slices[0]
        changes = (
            replace(first.scope, snapshot=replace(first.scope.snapshot, revision="changed")),
            replace(first.scope, projection=("close",)),
            replace(first.scope, start=first.scope.start + 300000),
        )
        for scope in changes:
            declaration = replace(first, scope=scope, approval=replace(first.approval, scope=scope))
            self.assertEqual(self.run_bound(replace(self.binding, slices=(declaration, *self.binding.slices[1:]))).verdict, "BLOCKED")
        horizon = self.binding.slices[-1]
        scope = replace(horizon.scope, end=horizon.scope.end - 300000)
        altered = replace(horizon, scope=scope, approval=replace(horizon.approval, scope=scope))
        self.assertEqual(self.run_bound(replace(self.binding, slices=(*self.binding.slices[:-1], altered))).verdict, "BLOCKED")

    def test_pre_io_stop_precedes_record_hashing(self):
        first = self.binding.slices[0]
        scope = replace(first.scope, start=PROTECTED[0][0], end=PROTECTED[0][1])
        item = replace(first, scope=scope, approval=replace(first.approval, scope=scope))
        with patch("demo_futures.research_v2.source_integration.row_commitment", side_effect=AssertionError("payload touched")):
            self.assertEqual(self.run_bound(replace(self.binding, slices=(item, *self.binding.slices[1:]))).verdict, "BLOCKED")
            self.assertEqual(self.run_bound(replace(self.binding, authority_ref="")).verdict, "BLOCKED")

    def test_page_budget_duplicates_and_interruption(self):
        for change in ({"max_pages": 1}, {"max_rows": 1}, {"max_rows": True},
                       {"slices": (self.binding.slices[0],) * 2}):
            self.assertEqual(self.run_bound(replace(self.binding, **change)).verdict, "BLOCKED")
        self.assertEqual(self.run_bound(prefixes=self.prefixes[:-1]).verdict, "BLOCKED")

    def test_replay_content_receipt_and_plan_mutations(self):
        first = self.prefixes[0]
        row = first.observations[0]
        changed = replace(row, proof=None)
        prefix = replace(first, observations=(changed, *first.observations[1:]))
        self.assertEqual(self.run_bound(prefixes=(prefix, *self.prefixes[1:])).verdict, "BLOCKED")
        self.assertEqual(self.run_bound(plan=replace(self.plan, audit_cutoff=self.plan.audit_cutoff - 1)).verdict, "BLOCKED")
        version = replace(row.version, version_id="changed")
        prefix = replace(first, observations=(replace(row, version=version), *first.observations[1:]))
        self.assertEqual(self.run_bound(prefixes=(prefix, *self.prefixes[1:])).verdict, "BLOCKED")

    def test_new_pinned_missing_receipt_refuses_causal_use(self):
        first = self.prefixes[0]
        prefix = replace(first, observations=(replace(first.observations[0], proof=None), *first.observations[1:]))
        prefixes = (prefix, *self.prefixes[1:])
        result = self.run_bound(fixture_binding(self.plan, prefixes, self.outcomes), prefixes=prefixes)
        self.assertEqual(result.verdict, "BOUND")
        self.assertEqual(len(result.workflow.causal), 32)
        self.assertNotEqual(result.workflow.causal_stage.verdict, Verdict.READY)

    def test_prefix_gap_and_horizon_gap_are_refused(self):
        for records, channel in ((self.prefixes, "prefix"), (self.outcomes, "horizon")):
            first = replace(records[0], observations=records[0].observations[1:])
            values = (first, *records[1:])
            prefixes = values if channel == "prefix" else self.prefixes
            outcomes = values if channel == "horizon" else self.outcomes
            binding = fixture_binding(self.plan, prefixes, outcomes)
            self.assertEqual(self.run_bound(binding, prefixes=prefixes, outcomes=outcomes).verdict, "BLOCKED")

    def test_funding_mutation_invalidates_binding(self):
        first = replace(self.outcomes[0], funding=None)
        self.assertEqual(self.run_bound(outcomes=(first, *self.outcomes[1:])).verdict, "BLOCKED")

    def test_unknown_source_and_missing_approval(self):
        first = self.binding.slices[0]
        altered = replace(first, approval=None)
        self.assertEqual(self.run_bound(replace(self.binding, slices=(altered, *self.binding.slices[1:]))).verdict, "BLOCKED")
        source = replace(self.plan.sources[0], source_id="other-source")
        self.assertEqual(self.run_bound(plan=replace(self.plan, sources=(source, self.plan.sources[1]))).verdict, "BLOCKED")
