"""M2 invented plans and settlement paths; no simulator or market inputs."""
import ast
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal as D, DefaultContext, getcontext, localcontext, Inexact, ROUND_DOWN
from pathlib import Path
import unittest
from unittest.mock import patch

from demo_futures.risk import PositionPlan
from demo_futures.research_v2.contracts import Readiness
from demo_futures.research_v2.funding_contracts import CoverageState
from demo_futures.risk_remediation.plan_budget_contract import (
    PlanBudgetBinding, PlanBudgetDiagnostic, assess_plan_budget,
)
from test_risk_funding_budget import BASE, HOUR, envelope, evidence, scenario


def plan(**changes):
    return replace(PositionPlan(D(10), D(100), D(98), D(103), D(50), D(50), D(500)), **changes)


def binding(e=None, **changes):
    e = envelope() if e is None else e
    value = PlanBudgetBinding(e.symbol, e.interval, e.side, e.source_id, e.version,
        e.decision_time, e.as_of, e.holding_start, e.holding_end, e.closure_end,
        D(10), D(100), D(1000), D(49), D(1), evidence("PLAN_BUDGET_DECOMPOSITION"))
    return replace(value, **changes)


class PlanBudgetTests(unittest.TestCase):
    def test_each_tampered_envelope_metadata_type_is_rejected_before_comparison(self):
        class Foreign:
            def __eq__(self, other):
                raise AssertionError("comparison before schema validation")
            __ne__ = __eq__
        for name in ("symbol", "interval", "side", "source_id", "version",
                     "decision_time", "as_of", "holding_start", "holding_end", "closure_end"):
            with self.subTest(field=name):
                e = envelope()
                b = binding(e)
                object.__setattr__(e, name, Foreign())
                self.reject(e=e, b=b, reason="INVALID_SCHEMA", status=Readiness.INVALID)

    def test_adjacent_representable_budget_values_use_exact_comparison(self):
        # Existing fixed 50-digit reconciliation context, not a new tolerance.
        from demo_futures.risk_remediation.plan_budget_contract import reconciliation_context
        with localcontext(reconciliation_context()):
            below, above = D(51).next_minus(), D(51).next_plus()
        for budget, comparison in ((below, "EXCEEDS"), (D(51), "WITHIN"), (above, "WITHIN")):
            output = assess_plan_budget(plan(budget=budget), envelope(), binding())
            self.assertEqual(output.comparison, comparison)

    def test_inexact_decomposition_is_not_rounded_into_a_match(self):
        self.reject(b=binding(nonfunding_loss=D("49." + "0" * 60 + "1")),
                    reason="ARITHMETIC_UNSUPPORTED", status=Readiness.INVALID)

    def test_valid_synthetic_identity_does_not_authenticate_decomposition(self):
        identity = replace(evidence("PLAN_BUDGET_DECOMPOSITION"), identity="other-invented-assertion")
        out = assess_plan_budget(plan(), envelope(), binding(evidence_identity=identity))
        self.assertEqual(out.status, Readiness.SUFFICIENT)
        self.assertEqual(out.authority, "SYNTHETIC_DIAGNOSTIC_ONLY")
        self.assertEqual(out.risk_clearance, "NOT CLEARED")

    def test_duplicate_settlement_is_not_admitted_as_extra_stress(self):
        e = envelope((scenario(((BASE + HOUR, ".002", "100"),) * 2),))
        self.reject(e=e, b=binding(e), reason="M1_INVALID", status=Readiness.INVALID)

    def test_nonfinite_or_inconsistent_diagnostic_construction_is_rejected(self):
        out = assess_plan_budget(plan(), envelope(), binding())
        for changes in ({"adjusted_loss": D("NaN")}, {"headroom": D("Infinity")},
                        {"comparison": "APPROVED"}, {"reasons": ("UNREVIEWED",)}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(out, **changes)

    def test_tampered_envelope_metadata_never_invokes_foreign_comparison(self):
        class Foreign:
            def __eq__(self, other):
                raise AssertionError("foreign metadata comparison executed")
            def __ne__(self, other):
                raise AssertionError("foreign metadata comparison executed")
        e = envelope()
        b = binding(e)
        object.__setattr__(e, "symbol", Foreign())
        self.reject(e=e, b=b, reason="INVALID_SCHEMA", status=Readiness.INVALID)

    def reject(self, p=None, e=None, b=None, reason=None, status=None):
        output = assess_plan_budget(plan() if p is None else p,
            envelope() if e is None else e, binding() if b is None else b)
        if reason is not None:
            self.assertIn(reason, output.reasons)
        if status is not None:
            self.assertEqual(output.status, status)
        self.assertIsNone(output.adjusted_loss)
        self.assertIsNone(output.budget)
        self.assertIsNone(output.headroom)
        self.assertIsNone(output.comparison)
        return output

    def test_hand_calculated_adverse_comparison(self):
        out = assess_plan_budget(plan(), envelope(), binding())
        self.assertEqual((out.adjusted_loss, out.budget, out.headroom, out.comparison),
                         (D(51), D(50), D(-1), "EXCEEDS"))
        self.assertEqual(out.status, Readiness.SUFFICIENT)  # Valid adverse diagnostic.

    def test_reserve_replaced_once_not_added_twice(self):
        out = assess_plan_budget(plan(), envelope(), binding())
        self.assertEqual(out.adjusted_loss, D(49) + D(2))
        self.assertNotEqual(out.adjusted_loss, D(50) + D(2))

    def test_exact_equal_budget_boundary(self):
        out = assess_plan_budget(plan(budget=D(51)), envelope(), binding())
        self.assertEqual(out.headroom, 0)
        self.assertEqual(out.comparison, "WITHIN")

    def test_one_decimal_unit_below_and_above_boundary(self):
        for budget, comparison in (("50.999999", "EXCEEDS"), ("51.000001", "WITHIN")):
            self.assertEqual(assess_plan_budget(plan(budget=D(budget)), envelope(), binding()).comparison, comparison)

    def test_credit_only_path_preserves_existing_reserve(self):
        e = envelope((scenario(((BASE + HOUR, "-.9", "100"),)),))
        self.assertEqual(assess_plan_budget(plan(), e, binding(e)).adjusted_loss, D(50))

    def test_explicit_no_settlement_keeps_floor(self):
        e = envelope((scenario((), state=CoverageState.KNOWN_NO_SETTLEMENT),))
        self.assertEqual(assess_plan_budget(plan(), e, binding(e)).adjusted_loss, D(50))

    def test_maximum_across_alternatives_not_sum(self):
        e = envelope((scenario(identity="small"), scenario(((BASE + HOUR, ".005", "100"),), identity="large")))
        self.assertEqual(assess_plan_budget(plan(), e, binding(e)).adjusted_loss, D(54))

    def test_short_adverse_signed_rate(self):
        e = envelope((scenario(((BASE + HOUR, "-.003", "100"),)),), side="SHORT")
        out = assess_plan_budget(plan(stop_price=D(102), target_price=D(97)), e, binding(e))
        self.assertEqual(out.adjusted_loss, D(52))

    def test_quantity_binding_mismatch(self):
        self.reject(p=plan(quantity=D(9)), reason="EXPOSURE_MISMATCH")

    def test_entry_price_binding_mismatch(self):
        self.reject(p=plan(entry_price=D(101)), reason="EXPOSURE_MISMATCH")

    def test_declared_notional_mismatch(self):
        self.reject(b=binding(entry_notional=D(999)), reason="EXPOSURE_MISMATCH")

    def test_envelope_notional_mismatch(self):
        self.reject(e=envelope(entry_notional=D(2000)), reason="EXPOSURE_MISMATCH")

    def test_envelope_price_mismatch(self):
        self.reject(e=envelope(entry_price=D(101)), reason="EXPOSURE_MISMATCH")

    def test_all_metadata_bindings_are_exact(self):
        for field_name, value in (("symbol", "ETHUSDT"), ("interval", "1h"), ("side", "SHORT"),
                ("source_id", "other"), ("version", "v2"), ("decision_time", BASE - 2),
                ("as_of", BASE - 1), ("holding_start", BASE + 1),
                ("holding_end", BASE + HOUR), ("closure_end", BASE + 4 * HOUR)):
            with self.subTest(field_name=field_name):
                self.reject(b=binding(**{field_name: value}), reason="INVALID_BINDING")

    def test_reserve_declaration_mismatch(self):
        self.reject(b=binding(embedded_reserve=D(2)), reason="RESERVE_MISMATCH")

    def test_decomposition_cannot_be_inferred(self):
        self.reject(b=binding(nonfunding_loss=D(48)), reason="DECOMPOSITION_MISMATCH")

    def test_missing_binding_is_insufficient(self):
        out = assess_plan_budget(plan(), envelope(), None)
        self.assertEqual(out.reasons, ("MISSING_BINDING",))
        self.assertEqual(out.status, Readiness.INSUFFICIENT)
        self.assertIsNone(out.adjusted_loss)

    def test_missing_and_wrong_evidence(self):
        self.reject(b=binding(evidence_identity=None), reason="MISSING_EVIDENCE", status=Readiness.INSUFFICIENT)
        for identity in (evidence("NO_SETTLEMENT"), replace(evidence("PLAN_BUDGET_DECOMPOSITION"), revision="v2"),
                         replace(evidence("PLAN_BUDGET_DECOMPOSITION"), basis="AUTHENTICATED")):
            self.reject(b=binding(evidence_identity=identity), reason="INVALID_EVIDENCE")

    def test_unknown_or_missing_coverage_is_insufficient(self):
        for e in (envelope(()), envelope((scenario((), state=CoverageState.UNKNOWN),))):
            self.reject(e=e, b=binding(e), reason="M1_INSUFFICIENT", status=Readiness.INSUFFICIENT)

    def test_stale_expired_and_future_envelopes(self):
        for changes in ({"expires_at": BASE}, {"expires_at": BASE + 3 * HOUR}, {"available_at": BASE + 1}):
            e = envelope(**changes)
            self.reject(e=e, b=binding(e), reason="M1_INSUFFICIENT")

    def test_incompatible_claim_scope(self):
        path = scenario()
        e = envelope((replace(path, claim=replace(path.claim, revision="wrong")),))
        self.reject(e=e, b=binding(e), reason="M1_INVALID", status=Readiness.INVALID)

    def test_entry_and_after_closure_events_are_rejected(self):
        for timestamp in (BASE, BASE + 3 * HOUR + 1):
            e = envelope((scenario(((timestamp, ".002", "100"),)),))
            self.reject(e=e, b=binding(e), reason="M1_INVALID")

    def test_first_owned_and_last_closure_millisecond(self):
        e = envelope((scenario(((BASE + 1, ".002", "100"), (BASE + 3 * HOUR, ".002", "100"))),))
        self.assertEqual(assess_plan_budget(plan(), e, binding(e)).adjusted_loss, D(53))

    def test_nonfinite_and_nonpositive_plan_fields(self):
        for name in ("quantity", "entry_price", "stop_price", "target_price", "budget", "planned_loss", "margin"):
            for number in (D("NaN"), D("sNaN"), D("Infinity"), D(0), D(-1)):
                with self.subTest(name=name, number=number):
                    self.reject(p=plan(**{name: number}), reason="INVALID_NUMBER")

    def test_nonfinite_binding_fields(self):
        for name in ("quantity", "entry_price", "entry_notional", "nonfunding_loss", "embedded_reserve"):
            for number in (D("sNaN"), D("Infinity"), D(-1)):
                self.reject(b=binding(**{name: number}), reason="INVALID_NUMBER")

    def test_boolean_float_and_mutable_fields_not_coerced(self):
        for number in (True, 10.0, "10", []):
            self.reject(b=binding(quantity=number), reason="INVALID_SCHEMA")
            self.reject(p=plan(quantity=number), reason="INVALID_SCHEMA")
        self.reject(b=binding(as_of=True), reason="INVALID_SCHEMA")

    def test_foreign_inputs_not_inspected(self):
        class Foreign:
            def __getattribute__(self, name):
                raise AssertionError("foreign payload inspected")
        self.reject(p=Foreign(), reason="INVALID_SCHEMA")
        self.reject(b=Foreign(), reason="INVALID_SCHEMA")

    def test_deleted_binding_field_fails_closed(self):
        value = binding()
        object.__delattr__(value, "quantity")
        self.reject(b=value, reason="INVALID_SCHEMA")

    def test_mutable_evidence_shape_rejected(self):
        self.reject(b=binding(evidence_identity=[]), reason="INVALID_EVIDENCE")

    def test_protective_side_levels_must_match(self):
        for changes in ({"stop_price": D(100)}, {"target_price": D(99)}, {"stop_price": D(102)}):
            self.reject(p=plan(**changes), reason="PLAN_LEVELS_INVALID")

    def test_inexact_exposure_does_not_introduce_tolerance(self):
        self.reject(p=plan(quantity=D("10.000000000000000000000000000000000000000000000000001")),
                    b=binding(quantity=D("10.000000000000000000000000000000000000000000000000001")),
                    reason="ARITHMETIC_UNSUPPORTED")

    def test_m1_overflow_and_underflow_propagate_without_amounts(self):
        for value in (D("1e1001"), D("1e-1100")):
            e = envelope(entry_notional=value)
            self.reject(e=e, b=binding(e, entry_notional=value), reason="M1_INVALID")

    def test_exact_subnormal_decomposition_is_supported(self):
        e = envelope(entry_notional=D("1e-1000"))
        p = plan(quantity=D("1e-1002"), budget=D("5e-1003"), planned_loss=D("5e-1003"), margin=D("5e-1001"))
        b = binding(e, quantity=p.quantity, entry_notional=e.entry_notional,
                    nonfunding_loss=D("4e-1003"), embedded_reserve=D("1e-1003"))
        out = assess_plan_budget(p, e, b)
        self.assertEqual(out.adjusted_loss, D("6e-1003"))

    def test_m2_adjusted_loss_overflow_fails_closed(self):
        e = envelope((scenario(((BASE + HOUR, "9", "1"),)),),
                     entry_price=D(1), entry_notional=D("1e999"))
        p = plan(quantity=D("1e999"), entry_price=D(1), stop_price=D(".9"), target_price=D("1.1"),
                 budget=D("9.999e999"), planned_loss=D("9.001e999"), margin=D("5e998"))
        b = binding(e, quantity=p.quantity, entry_price=p.entry_price, entry_notional=e.entry_notional,
                    nonfunding_loss=D("9e999"), embedded_reserve=D("1e996"))
        self.reject(p=p, e=e, b=b, reason="ARITHMETIC_UNSUPPORTED", status=Readiness.INVALID)

    def test_m2_exposure_multiplication_underflow_fails_closed(self):
        self.reject(p=plan(quantity=D("1e-1100")), b=binding(quantity=D("1e-1100")),
                    reason="ARITHMETIC_UNSUPPORTED", status=Readiness.INVALID)

    def test_eth_binding_remains_supported_without_scope_expansion(self):
        path = scenario()
        path = replace(path, claim=replace(path.claim, symbol="ETHUSDT",
                       schedule=replace(path.claim.schedule, symbol="ETHUSDT")))
        e = envelope((path,), symbol="ETHUSDT")
        self.assertEqual(assess_plan_budget(plan(), e, binding(e)).adjusted_loss, D(51))

    def test_zero_nonfunding_loss_is_explicit_and_supported(self):
        out = assess_plan_budget(plan(planned_loss=D(1)), envelope(), binding(nonfunding_loss=D(0)))
        self.assertEqual(out.adjusted_loss, D(2))

    def test_context_and_default_traps_do_not_change_results(self):
        expected = assess_plan_budget(plan(), envelope(), binding())
        saved = DefaultContext.traps.copy()
        try:
            DefaultContext.traps[Inexact] = True
            with localcontext() as context:
                context.prec = 2
                context.rounding = ROUND_DOWN
                before = context.copy()
                self.assertEqual(assess_plan_budget(plan(), envelope(), binding()), expected)
                self.assertEqual(getcontext().prec, before.prec)
                self.assertEqual(dict(getcontext().flags), dict(before.flags))
        finally:
            DefaultContext.traps.update(saved)

    def test_large_bounded_collection_and_input_order(self):
        e = envelope(tuple(scenario(identity=f"path-{i:03d}") for i in range(256)))
        self.assertEqual(assess_plan_budget(plan(), e, binding(e)).adjusted_loss, D(51))
        self.assertEqual(assess_plan_budget(plan(), e, binding(e)),
            assess_plan_budget(plan(), replace(e, scenarios=e.scenarios[::-1]), binding(e)))

    def test_immutable_inputs_outputs_and_no_authority(self):
        p, e, b = plan(), envelope(), binding()
        before = (repr(p), repr(e), repr(b))
        out = assess_plan_budget(p, e, b)
        self.assertEqual((repr(p), repr(e), repr(b)), before)
        for obj, name in ((p, "quantity"), (b, "quantity"), (out, "budget")):
            with self.assertRaises(FrozenInstanceError):
                setattr(obj, name, D(99))
        with self.assertRaises(TypeError):
            bool(out)
        self.assertEqual(out.risk_clearance, "NOT CLEARED")
        self.assertEqual(out.authority, "SYNTHETIC_DIAGNOSTIC_ONLY")
        self.assertFalse(hasattr(out, "approved"))

    def test_forged_output_is_refused(self):
        out = assess_plan_budget(plan(), envelope(), binding())
        with self.assertRaises(ValueError):
            replace(out, headroom=D(99))
        with self.assertRaises(ValueError):
            PlanBudgetDiagnostic(Readiness.INVALID, ("INVALID_SCHEMA",), budget=D(1))

    def test_no_io_or_sizing_interfaces(self):
        p, e, b = plan(), envelope(), binding()
        with patch("builtins.open", side_effect=AssertionError("I/O")), \
                patch("io.open", side_effect=AssertionError("I/O")), \
                patch("sqlite3.connect", side_effect=AssertionError("database")), \
                patch("socket.socket", side_effect=AssertionError("network")), \
                patch("demo_futures.risk.size_position", side_effect=AssertionError("sizing")):
            self.assertEqual(assess_plan_budget(p, e, b).adjusted_loss, D(51))

    def test_static_import_and_call_boundary(self):
        path = Path(__file__).resolve().parents[1] / "src/demo_futures/risk_remediation/plan_budget_contract.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        self.assertFalse(any(isinstance(n, ast.Import) for n in ast.walk(tree)))
        forbidden = {"open", "read_text", "write_text", "connect", "request", "size_position", "run", "fit", "predict"}
        calls = {n.func.id if isinstance(n.func, ast.Name) else n.func.attr for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, (ast.Name, ast.Attribute))}
        self.assertFalse(calls & forbidden)
