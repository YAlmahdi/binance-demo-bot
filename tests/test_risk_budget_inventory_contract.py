"""M3 invented 2010 inventories only. No account, saved market or portfolio runs."""
import ast
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal as D, DefaultContext, Inexact, getcontext, localcontext, ROUND_DOWN
from pathlib import Path
import unittest
from unittest.mock import patch

from demo_futures.research_v2.contracts import Readiness
from demo_futures.research_v2.funding_contracts import CoverageState
from demo_futures.risk_remediation.budget_inventory_contract import (
    Completeness, JointKind, ResourceBudget, InventoryInput, CompletenessAssertion,
    JointScenarioAssertion, InventoryDeclaration, InventoryDiagnostic, PositionDiagnostic,
    assess_inventory,
)
from test_risk_funding_budget import BASE, HOUR, envelope, evidence, scenario
from test_risk_plan_budget_contract import plan, binding


def inventory(count=2, **changes):
    scope = ("invented-owner", "invented-source", "v1", "snapshot-a")
    ids = tuple(f"position-{i:03d}" for i in range(count))
    e = envelope()
    def row(identity, value):
        return InventoryInput(identity, *scope, value)
    value = InventoryDeclaration(*scope, BASE, BASE, BASE, BASE + 1,
        ids, tuple(row(i, plan()) for i in ids), tuple(row(i, e) for i in ids),
        tuple(row(i, binding(e)) for i in ids), Completeness.COMPLETE,
        CompletenessAssertion(*scope, BASE, True, evidence("INVENTORY_COMPLETENESS")),
        JointScenarioAssertion(scope[1], scope[2], scope[3], JointKind.NO_COMBINED_MODEL,
            "Independent invented paths; no combined financial model claimed.", evidence("JOINT_SCENARIO_ASSUMPTION")),
        ResourceBudget(count, count * 2, count * 4, 10000, 100000, 128))
    return replace(value, **changes)


def change_raw(d, collection, index, **changes):
    rows = list(getattr(d, collection))
    rows[index] = replace(rows[index], value=replace(rows[index].value, **changes))
    return replace(d, **{collection: tuple(rows)})


class InventoryTests(unittest.TestCase):
    def test_constructor_structural_reason_requires_matching_readiness(self):
        for status, reason in ((Readiness.INSUFFICIENT, "INVALID_SCHEMA"),
                (Readiness.INVALID, "STALE_SNAPSHOT")):
            with self.subTest(reason=reason), self.assertRaises(ValueError):
                InventoryDiagnostic(status, (reason,))

    def test_nested_result_foreign_reason_never_compared(self):
        class Foreign:
            def __eq__(self, other):
                raise AssertionError("foreign diagnostic reason compared")
        result = assess_inventory(change_raw(inventory(1), "plans", 0, quantity=D(11))).positions[0].result
        object.__setattr__(result, "reasons", (Foreign(),))
        with self.assertRaises(ValueError):
            PositionDiagnostic("position-000", result)

    def test_nested_result_foreign_comparison_never_compared(self):
        class Foreign:
            def __ne__(self, other):
                raise AssertionError("foreign monetary comparison dispatched")
        result = assess_inventory(inventory(1)).positions[0].result
        object.__setattr__(result, "comparison", Foreign())
        with self.assertRaises(ValueError):
            PositionDiagnostic("position-000", result)

    def test_nested_tampered_authority_is_not_retained(self):
        for name in ("evidence", "authority", "risk_clearance"):
            with self.subTest(field=name):
                row = assess_inventory(inventory(1)).positions[0]
                object.__setattr__(row.result, name, "FORGED")
                with self.assertRaises(ValueError):
                    replace(row)
                with self.assertRaises(ValueError):
                    InventoryDiagnostic(Readiness.SUFFICIENT, positions=(row,))

    def test_deleted_nested_fields_fail_closed_before_m2(self):
        for target in ("identity", "event", "schedule", "claim", "binding"):
            d = inventory(1)
            e = d.envelopes[0].value
            obj, name = {"identity": (e.evidence_identity, "assertion"),
                "event": (e.scenarios[0].claim.observations[0], "rate"),
                "schedule": (e.scenarios[0].claim.schedule, "complete"),
                "claim": (e.scenarios[0].claim, "state"),
                "binding": (d.bindings[0].value, "quantity")}[target]
            object.__delattr__(obj, name)
            with self.subTest(target=target), patch(
                    "demo_futures.risk_remediation.budget_inventory_contract.assess_plan_budget",
                    side_effect=AssertionError("M2 called for malformed input")):
                self.rejected(d, "INVALID_SCHEMA")

    def test_nested_evidence_foreign_fields_never_compared(self):
        class Foreign:
            def __eq__(self, other):
                raise AssertionError("foreign evidence compared")
            __ne__ = __eq__
        for target in ("completeness", "joint", "envelope", "timing", "mark", "schedule", "binding"):
            d = inventory(1)
            e = d.envelopes[0].value
            event = e.scenarios[0].claim.observations[0]
            obj = {"completeness": d.completeness_assertion.identity, "joint": d.joint_assertion.identity,
                "envelope": e.evidence_identity, "timing": event.timing_evidence,
                "mark": event.mark_evidence, "schedule": e.scenarios[0].claim.schedule.identity,
                "binding": d.bindings[0].value.evidence_identity}[target]
            object.__setattr__(obj, "basis", Foreign())
            with self.subTest(target=target):
                self.rejected(d, "INVALID_SCHEMA")

    def test_exact_text_and_decimal_digit_boundaries(self):
        # Observe actual charged work, then use the same input at equality/-1.
        from demo_futures.risk_remediation import budget_inventory_contract as module
        original = module._Meter
        captured = []
        class Meter(original):
            def __init__(self, budget):
                super().__init__(budget)
                captured.append(self)
        d = inventory(1)
        with patch.object(module, "_Meter", Meter):
            self.assertEqual(assess_inventory(d).status, Readiness.SUFFICIENT)
        meter = captured[0]
        exact = replace(d.resources, max_text_chars=meter.text_chars, max_decimal_digits=meter.digits)
        self.assertEqual(assess_inventory(replace(d, resources=exact)).status, Readiness.SUFFICIENT)
        for name in ("max_text_chars", "max_decimal_digits"):
            with self.subTest(budget=name):
                self.rejected(replace(d, resources=replace(exact, **{name: getattr(exact, name) - 1})),
                    "RESOURCE_BUDGET_EXCEEDED")

    def test_repeated_raw_aliases_are_charged_per_position(self):
        d = inventory(4)
        self.assertIs(d.envelopes[0].value, d.envelopes[3].value)
        self.assertEqual(assess_inventory(replace(d, resources=replace(d.resources,
            max_scenarios=4, max_funding_items=8))).status, Readiness.SUFFICIENT)
        self.rejected(replace(d, resources=replace(d.resources, max_funding_items=7)), "RESOURCE_BUDGET_EXCEEDED")

    def test_large_nested_tuple_rejected_before_shape_walk(self):
        d = inventory(1)
        e = d.envelopes[0].value
        object.__setattr__(e.scenarios[0].claim, "observations", (object(),) * 256)
        with patch("demo_futures.risk_remediation.budget_inventory_contract._claim_shape",
                side_effect=AssertionError("unbudgeted nested traversal")):
            self.rejected(d, "RESOURCE_BUDGET_EXCEEDED")

    def test_invalid_numeric_and_text_shapes_reject_without_coercion(self):
        for value in (True, 1, 1.0, "1", None):
            with self.subTest(value=value):
                self.rejected(change_raw(inventory(1), "plans", 0, quantity=value), "INVALID_SCHEMA")
        for value in (True, None, [], 1):
            self.rejected(inventory(owner_id=value), "INVALID_SCHEMA")

    def test_extreme_exponent_budget_fails_before_m2(self):
        d = change_raw(inventory(1), "plans", 0, quantity=D("1e1000000000000000"))
        with patch("demo_futures.risk_remediation.budget_inventory_contract.assess_plan_budget",
                side_effect=AssertionError("M2 before exponent budget")):
            self.rejected(replace(d, resources=replace(d.resources, max_integer_bits=48)),
                "RESOURCE_BUDGET_EXCEEDED")

    def test_entry_failure_diagnostic_cannot_omit_all_entries(self):
        with self.assertRaises(ValueError):
            InventoryDiagnostic(Readiness.INVALID, ("ENTRY_INVALID",))
        with self.assertRaises(ValueError):
            InventoryDiagnostic(Readiness.INSUFFICIENT, ("ENTRY_INSUFFICIENT",))

    def rejected(self, value, reason, status=None):
        out = assess_inventory(value)
        self.assertIn(reason, out.reasons)
        if status is not None:
            self.assertEqual(out.status, status)
        self.assertEqual(out.aggregate_state, "BLOCKED")
        self.assertFalse(hasattr(out, "total_loss"))
        return out

    def test_complete_two_position_inventory_recomputes_raw_m2(self):
        out = assess_inventory(inventory())
        self.assertEqual(out.status, Readiness.SUFFICIENT)
        self.assertEqual(tuple(p.position_id for p in out.positions), ("position-000", "position-001"))
        self.assertEqual(tuple(p.result.adjusted_loss for p in out.positions), (D(51), D(51)))
        self.assertEqual(tuple(p.result.comparison for p in out.positions), ("EXCEEDS", "EXCEEDS"))

    def test_empty_is_valid_only_with_explicit_complete_assertions(self):
        out = assess_inventory(inventory(0))
        self.assertEqual(out.status, Readiness.SUFFICIENT)
        self.assertEqual(out.positions, ())
        self.assertEqual(out.aggregate_state, "BLOCKED")
        self.rejected(inventory(0, completeness=Completeness.UNKNOWN), "MISSING_COMPLETENESS")

    def test_missing_or_extra_collection_rows(self):
        for collection in ("plans", "envelopes", "bindings"):
            d = inventory()
            with self.subTest(collection=collection):
                self.rejected(replace(d, **{collection: getattr(d, collection)[:-1]}), "INVENTORY_MISMATCH")
                rows = getattr(d, collection)
                self.rejected(replace(d, **{collection: (replace(rows[0], position_id="extra"), rows[1])}), "INVENTORY_MISMATCH")

    def test_missing_required_identity_does_not_infer_inventory(self):
        d = inventory()
        self.rejected(replace(d, required_position_ids=d.required_position_ids[:-1]), "INVENTORY_MISMATCH")

    def test_duplicate_expected_ids_and_component_ids(self):
        d = inventory()
        self.rejected(replace(d, required_position_ids=("position-000",) * 2), "DUPLICATE_POSITION")
        for collection in ("plans", "envelopes", "bindings"):
            rows = getattr(d, collection)
            self.rejected(replace(d, **{collection: (rows[0], rows[0])}), "DUPLICATE_POSITION")

    def test_reordering_all_inputs_is_canonical(self):
        d = inventory(3)
        other = replace(d, required_position_ids=d.required_position_ids[::-1], plans=d.plans[::-1],
                        envelopes=d.envelopes[::-1], bindings=d.bindings[::-1])
        self.assertEqual(assess_inventory(d), assess_inventory(other))

    def test_each_component_scope_field_is_bound(self):
        d = inventory()
        for collection in ("plans", "envelopes", "bindings"):
            for name in ("owner_id", "source_id", "version", "snapshot_id"):
                with self.subTest(collection=collection, field=name):
                    rows = getattr(d, collection)
                    changed = replace(rows[0], **{name: "other"})
                    self.rejected(replace(d, **{collection: (changed,) + rows[1:]}), "CONFLICTING_SCOPE")

    def test_completeness_assertion_scope_and_snapshot_binding(self):
        d = inventory()
        for name, value in (("owner_id", "other"), ("source_id", "other"), ("version", "other"),
                            ("snapshot_id", "other"), ("snapshot_time", BASE - 1)):
            self.rejected(replace(d, completeness_assertion=replace(d.completeness_assertion,
                **{name: value})), "CONFLICTING_SCOPE")

    def test_unknown_missing_incomplete_and_contradictory_completeness(self):
        d = inventory()
        self.rejected(replace(d, completeness=Completeness.UNKNOWN), "MISSING_COMPLETENESS", Readiness.INSUFFICIENT)
        self.rejected(replace(d, completeness_assertion=None), "MISSING_COMPLETENESS", Readiness.INSUFFICIENT)
        self.rejected(replace(d, completeness_assertion=replace(d.completeness_assertion, complete=False)), "CONTRADICTORY_COMPLETENESS")
        self.rejected(replace(d, completeness=Completeness.INCOMPLETE,
            completeness_assertion=replace(d.completeness_assertion, complete=False)), "INVENTORY_INCOMPLETE", Readiness.INSUFFICIENT)

    def test_missing_wrong_and_unauthenticated_evidence(self):
        d = inventory()
        for identity in (None, evidence("NO_SETTLEMENT"), replace(evidence("INVENTORY_COMPLETENESS"), basis="AUTHENTICATED")):
            self.rejected(replace(d, completeness_assertion=replace(d.completeness_assertion, identity=identity)), "INVALID_EVIDENCE")

    def test_snapshot_availability_and_exclusive_expiry(self):
        d = inventory()
        self.rejected(replace(d, available_at=BASE + 1, expires_at=BASE + 2), "FUTURE_UNAVAILABLE", Readiness.INSUFFICIENT)
        self.rejected(replace(d, evaluation_time=BASE + 1), "STALE_SNAPSHOT", Readiness.INSUFFICIENT)
        self.assertEqual(assess_inventory(d).status, Readiness.SUFFICIENT)

    def test_ambiguous_invalid_and_boolean_times(self):
        for changes, reason in (({"snapshot_time": BASE + 1}, "INVALID_TIME"),
                ({"available_at": BASE - 1}, "INVALID_TIME"), ({"expires_at": BASE}, "INVALID_TIME"),
                ({"evaluation_time": -1}, "INVALID_TIME"), ({"evaluation_time": True}, "INVALID_SCHEMA")):
            self.rejected(inventory(**changes), reason)

    def test_entry_as_of_and_source_must_match_snapshot_context(self):
        for collection in ("envelopes", "bindings"):
            for changes in ({"as_of": BASE - 1}, {"source_id": "other"}, {"version": "v2"}):
                self.rejected(change_raw(inventory(), collection, 0, **changes), "CONFLICTING_SCOPE")

    def test_entry_decision_after_snapshot_is_rejected(self):
        d = change_raw(inventory(), "envelopes", 0, decision_time=BASE + 1)
        self.rejected(d, "CONFLICTING_SCOPE")

    def test_cross_position_binding_substitution_is_not_trusted(self):
        d = change_raw(inventory(), "plans", 1, quantity=D(20))
        d = change_raw(d, "envelopes", 1, entry_notional=D(2000))
        d = change_raw(d, "bindings", 1, quantity=D(20), entry_notional=D(2000), embedded_reserve=D(2), nonfunding_loss=D(48))
        self.assertEqual(assess_inventory(d).status, Readiness.SUFFICIENT)
        # Keep wrapper IDs but substitute a different position's raw binding.
        substituted = replace(d.bindings[0], value=d.bindings[1].value)
        out = self.rejected(replace(d, bindings=(substituted, d.bindings[1])), "ENTRY_INVALID")
        self.assertEqual(out.positions[0].result.reasons, ("EXPOSURE_MISMATCH",))

    def test_all_failed_entries_reported_with_invalid_dominance(self):
        d = change_raw(inventory(), "plans", 0, quantity=D(11))
        e = envelope((scenario((), state=CoverageState.UNKNOWN),))
        d = replace(d, envelopes=(d.envelopes[0], replace(d.envelopes[1], value=e)))
        out = self.rejected(d, "ENTRY_INVALID", Readiness.INVALID)
        self.assertEqual(out.reasons, ("ENTRY_INVALID", "ENTRY_INSUFFICIENT"))
        self.assertEqual(tuple(p.result.status for p in out.positions), (Readiness.INVALID, Readiness.INSUFFICIENT))

    def test_per_position_unknown_coverage_is_not_zero(self):
        d = inventory(1)
        e = envelope((scenario((), state=CoverageState.UNKNOWN),))
        out = self.rejected(replace(d, envelopes=(replace(d.envelopes[0], value=e),)), "ENTRY_INSUFFICIENT", Readiness.INSUFFICIENT)
        self.assertIsNone(out.positions[0].result.adjusted_loss)

    def test_no_caller_supplied_successful_result_is_accepted(self):
        d = inventory(1)
        result = assess_inventory(d).positions[0].result
        self.rejected(replace(d, bindings=(replace(d.bindings[0], value=result),)), "INVALID_SCHEMA")

    def test_missing_joint_declaration_is_insufficient(self):
        self.rejected(inventory(joint_assertion=None), "MISSING_JOINT_ASSERTION", Readiness.INSUFFICIENT)

    def test_all_declared_joint_models_remain_blocked(self):
        d = inventory()
        for kind in JointKind:
            out = assess_inventory(replace(d, joint_assertion=replace(d.joint_assertion, kind=kind)))
            self.assertEqual(out.status, Readiness.SUFFICIENT)
            self.assertEqual(out.aggregate_state, "BLOCKED")
            self.assertEqual(out.aggregate_reason, "JOINT_STRESS_UNSUPPORTED")
            for name in ("total_loss", "portfolio_budget", "joint_worst_case", "approved"):
                self.assertFalse(hasattr(out, name))

    def test_joint_scope_identity_and_description_are_required(self):
        d = inventory()
        for changes, reason in (({"snapshot_id": "other"}, "CONFLICTING_SCOPE"),
                ({"identity": None}, "INVALID_EVIDENCE"), ({"description": " "}, "CONFLICTING_SCOPE"),
                ({"kind": "JOINT_MODEL_ASSERTION"}, "INVALID_SCHEMA")):
            self.rejected(replace(d, joint_assertion=replace(d.joint_assertion, **changes)), reason)

    def test_mutable_collections_and_foreign_components_rejected(self):
        d = inventory()
        for name in ("required_position_ids", "plans", "envelopes", "bindings"):
            self.rejected(replace(d, **{name: list(getattr(d, name))}), "INVALID_SCHEMA")
        self.rejected(replace(d, plans=(object(),) + d.plans[1:]), "INVALID_SCHEMA")

    def test_foreign_objects_never_dispatch_comparison(self):
        class Foreign:
            def __eq__(self, other):
                raise AssertionError("foreign comparison")
            __ne__ = __eq__
        d = inventory()
        self.rejected(replace(d, owner_id=Foreign()), "INVALID_SCHEMA")
        self.rejected(replace(d, plans=(replace(d.plans[0], position_id=Foreign()),) + d.plans[1:]), "INVALID_SCHEMA")
        e = envelope()
        object.__setattr__(e, "source_id", Foreign())
        self.rejected(replace(d, envelopes=(replace(d.envelopes[0], value=e),) + d.envelopes[1:]), "INVALID_SCHEMA")

    def test_deleted_input_field_fails_closed(self):
        d = inventory()
        object.__delattr__(d, "snapshot_id")
        self.rejected(d, "INVALID_SCHEMA")

    def test_resource_budgets_are_explicit_typed_nonnegative(self):
        d = inventory()
        for budget in (None, [], replace(d.resources, max_positions=True), replace(d.resources, max_scenarios=-1)):
            self.rejected(replace(d, resources=budget), "INVALID_SCHEMA")

    def test_each_processing_budget_is_enforced_before_m2(self):
        d = inventory()
        for name in ("max_positions", "max_scenarios", "max_funding_items", "max_decimal_digits", "max_text_chars", "max_integer_bits"):
            with self.subTest(budget=name), patch("demo_futures.risk_remediation.budget_inventory_contract.assess_plan_budget", side_effect=AssertionError("M2 called before budget gate")):
                self.rejected(replace(d, resources=replace(d.resources, **{name: 0})), "RESOURCE_BUDGET_EXCEEDED")

    def test_exact_scenario_and_funding_item_budget_boundaries(self):
        d = inventory()
        exact = replace(d.resources, max_scenarios=2, max_funding_items=4)
        self.assertEqual(assess_inventory(replace(d, resources=exact)).status, Readiness.SUFFICIENT)
        self.rejected(replace(d, resources=replace(exact, max_scenarios=1)), "RESOURCE_BUDGET_EXCEEDED")
        self.rejected(replace(d, resources=replace(exact, max_funding_items=3)), "RESOURCE_BUDGET_EXCEEDED")

    def test_exact_integer_bit_budget_boundary(self):
        d = inventory()
        bits = (BASE + 3 * HOUR + 1).bit_length()
        self.assertEqual(assess_inventory(replace(d, resources=replace(d.resources, max_integer_bits=bits))).status, Readiness.SUFFICIENT)
        self.rejected(replace(d, resources=replace(d.resources, max_integer_bits=bits - 1)), "RESOURCE_BUDGET_EXCEEDED")

    def test_bounded_large_inventory_has_no_inherited_position_cap(self):
        d = inventory(32)
        self.assertEqual(len(assess_inventory(d).positions), 32)
        self.rejected(replace(d, resources=replace(d.resources, max_positions=31)), "RESOURCE_BUDGET_EXCEEDED")

    def test_nonfinite_numeric_inputs_produce_no_positions(self):
        for value in (D("NaN"), D("sNaN"), D("Infinity")):
            out = self.rejected(change_raw(inventory(), "plans", 0, quantity=value), "INVALID_NUMBER")
            self.assertEqual(out.positions, ())

    def test_exact_budget_equality_and_reserve_replacement_per_position(self):
        d = change_raw(inventory(1), "plans", 0, budget=D(51))
        out = assess_inventory(d)
        self.assertEqual(out.positions[0].result.adjusted_loss, D(51))
        self.assertEqual(out.positions[0].result.headroom, 0)
        self.assertEqual(out.positions[0].result.comparison, "WITHIN")
        self.assertEqual(out.aggregate_state, "BLOCKED")

    def test_decimal_overflow_and_underflow_propagate_per_position(self):
        for value in (D("1e1001"), D("1e-1100")):
            d = change_raw(inventory(1), "envelopes", 0, entry_notional=value)
            out = self.rejected(d, "ENTRY_INVALID")
            self.assertIsNone(out.positions[0].result.adjusted_loss)

    def test_exact_subnormal_position_is_supported(self):
        d = inventory(1)
        p = plan(quantity=D("1e-1002"), planned_loss=D("5e-1003"), budget=D("5e-1003"), margin=D("5e-1001"))
        e = envelope(entry_notional=D("1e-1000"))
        b = binding(e, quantity=p.quantity, entry_notional=e.entry_notional, nonfunding_loss=D("4e-1003"), embedded_reserve=D("1e-1003"))
        d = replace(d, plans=(replace(d.plans[0], value=p),), envelopes=(replace(d.envelopes[0], value=e),), bindings=(replace(d.bindings[0], value=b),))
        self.assertEqual(assess_inventory(d).positions[0].result.adjusted_loss, D("6e-1003"))

    def test_context_and_default_settings_are_preserved(self):
        expected = assess_inventory(inventory())
        saved = DefaultContext.copy()
        try:
            DefaultContext.traps[Inexact] = True
            with localcontext() as context:
                context.prec, context.rounding = 2, ROUND_DOWN
                before = context.copy()
                self.assertEqual(assess_inventory(inventory()), expected)
                self.assertEqual(getcontext().prec, 2)
                self.assertEqual(dict(getcontext().flags), dict(before.flags))
        finally:
            DefaultContext.traps.update(saved.traps)

    def test_inputs_outputs_immutable_and_no_truth_authority(self):
        d = inventory()
        before = repr(d)
        out = assess_inventory(d)
        self.assertEqual(repr(d), before)
        for obj, name in ((d, "owner_id"), (d.plans[0], "owner_id"), (out, "positions")):
            with self.assertRaises(FrozenInstanceError):
                setattr(obj, name, None)
        with self.assertRaises(TypeError):
            bool(out)
        self.assertEqual(out.risk_clearance, "NOT CLEARED")

    def test_forged_outputs_and_hidden_entry_failures_are_refused(self):
        d = inventory()
        out = assess_inventory(d)
        with self.assertRaises(ValueError):
            replace(out, positions=out.positions[::-1])
        bad = assess_inventory(change_raw(d, "plans", 0, quantity=D(11)))
        with self.assertRaises(ValueError):
            replace(bad, status=Readiness.SUFFICIENT, reasons=())

    def test_no_real_io_sizing_or_network_interfaces(self):
        d = inventory()
        with patch("builtins.open", side_effect=AssertionError("I/O")), patch("io.open", side_effect=AssertionError("I/O")), \
                patch("sqlite3.connect", side_effect=AssertionError("database")), patch("socket.socket", side_effect=AssertionError("network")), \
                patch("demo_futures.risk.size_position", side_effect=AssertionError("sizing")):
            self.assertEqual(assess_inventory(d).status, Readiness.SUFFICIENT)

    def test_static_no_io_and_no_execution_imports(self):
        p = Path(__file__).resolve().parents[1] / "src/demo_futures/risk_remediation/budget_inventory_contract.py"
        tree = ast.parse(p.read_text(encoding="utf-8"))
        self.assertFalse(any(isinstance(n, ast.Import) for n in ast.walk(tree)))
        forbidden = {"open", "read_text", "write_text", "connect", "request", "size_position", "run", "fit", "predict"}
        calls = {n.func.id if isinstance(n.func, ast.Name) else n.func.attr for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, (ast.Name, ast.Attribute))}
        self.assertFalse(calls & forbidden)
