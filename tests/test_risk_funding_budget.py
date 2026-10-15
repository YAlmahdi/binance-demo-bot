"""M1 invented settlement paths only; no financial simulation or saved evidence."""
import ast
from dataclasses import FrozenInstanceError, replace
from decimal import (
    Clamped, Decimal as D, DefaultContext, DivisionByZero, FloatOperation,
    Inexact, InvalidOperation, Overflow, Rounded, Subnormal, Underflow,
    getcontext, localcontext, ROUND_CEILING, ROUND_DOWN,
)
from pathlib import Path
import unittest
from unittest.mock import patch

from demo_futures.research_v2.contracts import EvidenceIdentity, Readiness
from demo_futures.research_v2.funding_contracts import (
    CoverageState, FundingClaim, ScheduleEvidence, SettlementObservation,
)
from demo_futures.risk_remediation.funding_budget import (
    FundingBudgetDiagnostic, FundingStressScenario, SyntheticFundingStressEnvelope,
    _context, assess_funding_budget,
)

BASE = 1262304000000  # Invented 2010 scenario times, never historical market inputs.
HOUR = 3_600_000


def evidence(assertion):
    return EvidenceIdentity("fixture-" + assertion, "invented-source", "v1", assertion)


def scenario(rows=((BASE + HOUR, ".002", "100"),), identity="path-a", state=CoverageState.KNOWN_EVENTS):
    events = tuple(SettlementObservation(t, D(rate), D(mark),
        evidence("SETTLEMENT_TIME_AND_RATE"), evidence("SETTLEMENT_MARK")) for t, rate, mark in rows)
    assertion = "NO_SETTLEMENT" if state == CoverageState.KNOWN_NO_SETTLEMENT else "SETTLEMENT_SCHEDULE"
    schedule = ScheduleEvidence("BTCUSDT", BASE + 1, BASE + 3 * HOUR + 1,
        evidence(assertion), tuple(v.timestamp for v in events), True)
    claim = FundingClaim("BTCUSDT", schedule.start, schedule.end, "invented-source", "v1",
                         state, events, schedule)
    return FundingStressScenario(identity, BASE - 10, claim)


def envelope(paths=None, **changes):
    value = SyntheticFundingStressEnvelope("BTCUSDT", "5m", "LONG", BASE - 1, BASE,
        BASE - 20, BASE + 3 * HOUR + 1, BASE, BASE + 2 * HOUR, BASE + 3 * HOUR,
        "invented-source", "v1", D(100), D(1000), evidence("FUNDING_STRESS_ENVELOPE"),
        (scenario(),) if paths is None else paths)
    return replace(value, **changes)


class FundingBudgetTests(unittest.TestCase):
    def test_exact_subnormal_floor_and_debit_are_supported(self):
        # Exact subnormal results need no rounding and are distinct from underflow.
        result = assess_funding_budget(envelope(entry_notional=D("1e-1000")))
        self.assertEqual(result.status, Readiness.SUFFICIENT)
        self.assertEqual(result.reserve_floor, D("1e-1003"))
        self.assertEqual(result.worst_case_debit, D("2e-1003"))
        self.assertEqual(result.reserve_shortfall, D("1e-1003"))
        with localcontext(_context()) as context:
            self.assertTrue(result.allowance.is_subnormal(context))

    def test_exact_subnormal_at_etiny_is_supported(self):
        value = envelope((scenario((), state=CoverageState.KNOWN_NO_SETTLEMENT),),
                         entry_notional=D("1e-1045"))
        result = assess_funding_budget(value)
        self.assertEqual(result.status, Readiness.SUFFICIENT)
        self.assertEqual(result.allowance, D("1e-1048"))

    def test_inexact_subnormal_debit_underflows_without_allowance(self):
        path = scenario(((BASE + HOUR, "1e-1052", "100"),))
        self.assert_rejected(envelope((path,)), "ARITHMETIC_UNSUPPORTED", Readiness.INVALID)

    def test_intermediate_product_overflow_is_explicitly_unsupported(self):
        # No algebraic rearrangement or new numerical limit is prescribed here.
        self.assert_rejected(envelope(entry_notional=D("1e999")),
                             "ARITHMETIC_UNSUPPORTED", Readiness.INVALID)

    def test_signaling_nan_and_signed_zero_entries_are_rejected(self):
        for number in (D("sNaN"), D("-sNaN"), D("-0")):
            for field_name in ("entry_price", "entry_notional"):
                with self.subTest(number=number, field_name=field_name):
                    self.assert_rejected(envelope(**{field_name: number}), "INVALID_NUMBER")

    def test_signaling_nan_settlement_rate_and_mark_fail_closed(self):
        path = scenario()
        for field_name in ("rate", "mark_price"):
            event = replace(path.claim.observations[0], **{field_name: D("sNaN")})
            self.assert_rejected(envelope((replace(path, claim=replace(path.claim,
                observations=(event,))),)), "FUNDING_CONTRACT_INVALID", Readiness.INVALID)

    def test_tampered_mutable_scenario_collection_is_rejected(self):
        value = envelope()
        object.__setattr__(value, "scenarios", list(value.scenarios))
        self.assert_rejected(value, "INVALID_SCHEMA", Readiness.INVALID)

    def test_tampered_schedule_and_scenario_time_are_revalidated(self):
        value = envelope()
        object.__setattr__(value.scenarios[0].claim.schedule, "expected_settlements", [])
        self.assert_rejected(value, "INVALID_SCHEMA", Readiness.INVALID)
        value = envelope()
        object.__setattr__(value.scenarios[0], "available_at", True)
        self.assert_rejected(value, "INVALID_TIME", Readiness.INVALID)

    def test_bounded_large_collection_is_not_silently_capped(self):
        # 256 is only this fixture's size, never a production resource policy.
        paths = tuple(scenario(((BASE + HOUR, ".002", "100"),), identity=f"path-{i:03d}")
                      for i in range(256))
        result = assess_funding_budget(envelope(paths))
        self.assertEqual(result.status, Readiness.SUFFICIENT)
        self.assertEqual(len(result.scenario_debits), 256)
        self.assertEqual(result.allowance, D(2))
        self.assertEqual(result, assess_funding_budget(envelope(paths[::-1])))

    def test_bounded_many_duplicate_paths_fail_closed(self):
        path = scenario()
        self.assert_rejected(envelope((path,) * 256), "DUPLICATE_SCENARIO", Readiness.INVALID)

    def test_unknown_alternative_blocks_known_path_and_empty_is_insufficient(self):
        paths = (scenario(), scenario((), identity="unknown", state=CoverageState.UNKNOWN))
        self.assert_rejected(envelope(paths), "FUNDING_CONTRACT_INSUFFICIENT", Readiness.INSUFFICIENT)
        self.assert_rejected(envelope(()), "MISSING_SCENARIOS", Readiness.INSUFFICIENT)

    def test_short_alternative_maximum_ignores_large_credit(self):
        paths = (scenario(((BASE + HOUR, "-.004", "100"), (BASE + 2 * HOUR, ".9", "100"))),
                 scenario(((BASE + HOUR, "-.006", "100"),), identity="path-b"))
        result = assess_funding_budget(envelope(paths, side="SHORT"))
        self.assertEqual(result.scenario_debits, (("path-a", D(4)), ("path-b", D(6))))
        self.assertEqual(result.allowance, D(6))

    def test_zero_time_origin_owns_only_first_millisecond_through_closure(self):
        events = tuple(SettlementObservation(t, D(".002"), D(100),
                       evidence("SETTLEMENT_TIME_AND_RATE"), evidence("SETTLEMENT_MARK")) for t in (1, 2))
        schedule = ScheduleEvidence("BTCUSDT", 1, 3, evidence("SETTLEMENT_SCHEDULE"), (1, 2), True)
        path = FundingStressScenario("zero-origin", 0, FundingClaim("BTCUSDT", 1, 3,
            "invented-source", "v1", CoverageState.KNOWN_EVENTS, events, schedule))
        result = assess_funding_budget(envelope((path,), decision_time=0, as_of=0,
            available_at=0, expires_at=3, holding_start=0, holding_end=1, closure_end=2))
        self.assertEqual(result.worst_case_debit, D(4))

    def test_missing_schedule_is_not_inferred_from_valid_events(self):
        path = scenario()
        path = replace(path, claim=replace(path.claim, schedule=None))
        self.assert_rejected(envelope((path,)), "FUNDING_CONTRACT_INSUFFICIENT", Readiness.INSUFFICIENT)

    def test_diagnostic_does_not_call_size_database_or_socket_interfaces(self):
        with patch("demo_futures.risk.size_position", side_effect=AssertionError("sizing integration")), \
                patch("sqlite3.connect", side_effect=AssertionError("database integration")), \
                patch("socket.socket", side_effect=AssertionError("network integration")):
            self.assertEqual(assess_funding_budget(envelope()).allowance, D(2))

    def assert_rejected(self, value, reason, status=None):
        output = assess_funding_budget(value)
        self.assertIn(reason, output.reasons)
        if status is not None:
            self.assertEqual(output.status, status)
        self.assertIsNone(output.allowance)
        self.assertIsNone(output.reserve_floor)
        self.assertEqual(output.scenario_debits, ())
        return output

    def test_long_multiple_debits_ignore_credit_hand_calculation(self):
        rows = ((BASE + HOUR, ".002", "100"), (BASE + 2 * HOUR, "-.9", "100"),
                (BASE + 3 * HOUR, ".003", "120"))
        result = assess_funding_budget(envelope((scenario(rows),)))
        self.assertEqual(result.reserve_floor, D(1))
        self.assertEqual(result.worst_case_debit, D("5.6"))
        self.assertEqual(result.allowance, D("5.6"))
        self.assertEqual(result.reserve_shortfall, D("4.6"))

    def test_short_signed_debits_ignore_positive_rate_credit(self):
        rows = ((BASE + HOUR, "-.002", "100"), (BASE + 2 * HOUR, ".8", "100"),
                (BASE + 3 * HOUR, "-.003", "120"))
        result = assess_funding_budget(envelope((scenario(rows),), side="SHORT"))
        self.assertEqual(result.worst_case_debit, D("5.6"))

    def test_alternative_paths_take_maximum_not_sum(self):
        paths = (scenario(identity="path-b"), scenario(((BASE + HOUR, ".005", "100"),)))
        result = assess_funding_budget(envelope(paths))
        self.assertEqual(result.scenario_debits, (("path-a", D(5)), ("path-b", D(2))))
        self.assertEqual(result.allowance, D(5))

    def test_existing_reserve_floor_not_added_to_debit(self):
        result = assess_funding_budget(envelope((scenario(((BASE + HOUR, ".0005", "100"),)),)))
        self.assertEqual(result.worst_case_debit, D(".5"))
        self.assertEqual(result.allowance, D(1))
        self.assertEqual(result.reserve_shortfall, D(0))

    def test_equal_floor_boundary(self):
        result = assess_funding_budget(envelope((scenario(((BASE + HOUR, ".001", "100"),)),)))
        self.assertEqual(result.allowance, result.reserve_floor)
        self.assertEqual(result.reserve_shortfall, 0)

    def test_credits_only_keep_floor(self):
        result = assess_funding_budget(envelope((scenario(((BASE + HOUR, "-.1", "100"),)),)))
        self.assertEqual(result.worst_case_debit, 0)
        self.assertEqual(result.allowance, 1)

    def test_rate_monotonicity(self):
        results = [assess_funding_budget(envelope((scenario(((BASE + HOUR, rate, "100"),)),))).allowance
                   for rate in ("0", ".0005", ".001", ".002", ".01")]
        self.assertEqual(results, sorted(results))

    def test_mark_and_notional_monotonicity(self):
        original = assess_funding_budget(envelope()).allowance
        higher_mark = assess_funding_budget(envelope((scenario(((BASE + HOUR, ".002", "120"),)),))).allowance
        higher_exposure = assess_funding_budget(envelope(entry_notional=D(2000))).allowance
        self.assertGreater(higher_mark, original)
        self.assertEqual(higher_exposure, original * 2)

    def test_canonical_scenario_order_and_repeatability(self):
        paths = (scenario(identity="path-b"), scenario(identity="path-a"))
        self.assertEqual(assess_funding_budget(envelope(paths)), assess_funding_budget(envelope(paths[::-1])))
        self.assertEqual(assess_funding_budget(envelope(paths)), assess_funding_budget(envelope(paths)))

    def test_decimal_context_independence_and_no_ambient_mutation(self):
        value = envelope(entry_price=D(3))
        expected = assess_funding_budget(value)
        with localcontext() as context:
            context.prec = 2
            context.rounding = ROUND_DOWN
            actual = assess_funding_budget(value)
            self.assertEqual(getcontext().prec, 2)
            self.assertEqual(getcontext().rounding, ROUND_DOWN)
        self.assertEqual(actual, expected)
        self.assertGreaterEqual(actual.worst_case_debit, D("66.666666666666666666666666666666666666666666666666"))

    def test_default_inexact_trap_does_not_change_valid_diagnostic(self):
        value = envelope(entry_price=D(3))
        expected = assess_funding_budget(value)
        previous = DefaultContext.traps.copy()
        try:
            DefaultContext.traps[Inexact] = True
            self.assertEqual(assess_funding_budget(value), expected)
        finally:
            DefaultContext.traps.update(previous)
        self.assertEqual(DefaultContext.traps, previous)

    def test_disabled_default_overflow_trap_returns_reasoned_failure(self):
        value = envelope(entry_notional=D("1e1001"))
        previous = DefaultContext.traps.copy()
        try:
            DefaultContext.traps[Overflow] = False
            result = self.assert_rejected(value, "ARITHMETIC_UNSUPPORTED", Readiness.INVALID)
            self.assertEqual(result.reasons, ("ARITHMETIC_UNSUPPORTED",))
        finally:
            DefaultContext.traps.update(previous)
        self.assertEqual(DefaultContext.traps, previous)

    def test_complete_context_policy_does_not_inherit_global_defaults(self):
        value = envelope(entry_price=D(3))
        expected = assess_funding_budget(value)
        previous = DefaultContext.copy()
        policy = {InvalidOperation: True, DivisionByZero: True, Overflow: True, Underflow: True,
                  Inexact: False, Rounded: False, Subnormal: False, Clamped: False, FloatOperation: False}
        try:
            DefaultContext.prec, DefaultContext.rounding = 2, ROUND_DOWN
            DefaultContext.Emin, DefaultContext.Emax = -9, 9
            DefaultContext.capitals, DefaultContext.clamp = 0, 1
            for enabled in (True, False):
                for signal in DefaultContext.traps:
                    DefaultContext.traps[signal] = enabled
                    DefaultContext.flags[signal] = True
                context = _context()
                self.assertEqual(dict(context.traps), policy)
                self.assertFalse(any(context.flags.values()))
                self.assertEqual((context.prec, context.rounding, context.Emin, context.Emax,
                                  context.capitals, context.clamp), (50, ROUND_CEILING, -999, 999, 1, 0))
                self.assertEqual(assess_funding_budget(value), expected)
        finally:
            for name in ("prec", "rounding", "Emin", "Emax", "capitals", "clamp"):
                setattr(DefaultContext, name, getattr(previous, name))
            DefaultContext.traps.update(previous.traps)
            DefaultContext.flags.update(previous.flags)
        self.assertEqual(tuple(getattr(DefaultContext, name) for name in
            ("prec", "rounding", "Emin", "Emax", "capitals", "clamp")),
            tuple(getattr(previous, name) for name in
            ("prec", "rounding", "Emin", "Emax", "capitals", "clamp")))
        self.assertEqual(dict(DefaultContext.traps), dict(previous.traps))
        self.assertEqual(dict(DefaultContext.flags), dict(previous.flags))

    def test_unsupported_arithmetic_is_independent_of_default_traps(self):
        previous = DefaultContext.traps.copy()
        try:
            for enabled in (True, False):
                for signal in DefaultContext.traps:
                    DefaultContext.traps[signal] = enabled
                for notional in (D("1e1001"), D("1e-1100")):
                    with self.subTest(enabled=enabled, notional=notional):
                        output = self.assert_rejected(envelope(entry_notional=notional),
                                                      "ARITHMETIC_UNSUPPORTED", Readiness.INVALID)
                        self.assertEqual(output.reasons, ("ARITHMETIC_UNSUPPORTED",))
        finally:
            DefaultContext.traps.update(previous)

    def test_nonfinite_arithmetic_results_cannot_construct_allowance(self):
        loose = _context()
        for signal in loose.traps:
            loose.traps[signal] = False
        # Defense at the result boundary, even if a future context regression disables traps.
        with patch("demo_futures.risk_remediation.funding_budget._context", return_value=loose):
            self.assert_rejected(envelope(entry_notional=D("1e1001")),
                                 "ARITHMETIC_UNSUPPORTED", Readiness.INVALID)

    def test_diagnostic_construction_error_returns_reasoned_failure(self):
        original = FundingBudgetDiagnostic
        def construct(status, *args, **kwargs):
            if status == Readiness.SUFFICIENT:
                raise ValueError("Unsupported numeric result")
            return original(status, *args, **kwargs)
        with patch("demo_futures.risk_remediation.funding_budget.FundingBudgetDiagnostic", side_effect=construct):
            self.assert_rejected(envelope(), "ARITHMETIC_UNSUPPORTED", Readiness.INVALID)

    def test_explicit_no_settlement_remains_synthetic_and_keeps_floor(self):
        result = assess_funding_budget(envelope((scenario((), state=CoverageState.KNOWN_NO_SETTLEMENT),)))
        self.assertEqual(result.status, Readiness.SUFFICIENT)
        self.assertEqual(result.worst_case_debit, 0)
        self.assertEqual(result.allowance, 1)
        self.assertEqual(result.authority, "SYNTHETIC_DIAGNOSTIC_ONLY")
        self.assertFalse(hasattr(result, "allow_missing_funding"))

    def test_empty_known_events_are_not_no_settlement(self):
        self.assert_rejected(envelope((scenario(()),)), "FUNDING_CONTRACT_INSUFFICIENT", Readiness.INSUFFICIENT)

    def test_unknown_claim_is_not_zero(self):
        self.assert_rejected(envelope((scenario((), state=CoverageState.UNKNOWN),)), "FUNDING_CONTRACT_INSUFFICIENT")

    def test_no_settlement_requires_explicit_schedule_evidence(self):
        path = scenario((), state=CoverageState.KNOWN_NO_SETTLEMENT)
        for schedule in (None, replace(path.claim.schedule, identity=None), replace(path.claim.schedule, complete=False)):
            with self.subTest(schedule=schedule):
                self.assert_rejected(envelope((replace(path, claim=replace(path.claim, schedule=schedule)),)),
                                     "FUNDING_CONTRACT_INSUFFICIENT")

    def test_no_settlement_with_events_is_invalid(self):
        path = scenario(state=CoverageState.KNOWN_NO_SETTLEMENT)
        self.assert_rejected(envelope((path,)), "FUNDING_CONTRACT_INVALID", Readiness.INVALID)

    def test_missing_scenarios_and_missing_envelope_evidence(self):
        self.assert_rejected(envelope(()), "MISSING_SCENARIOS")
        self.assert_rejected(envelope(evidence_identity=None), "MISSING_EVIDENCE")

    def test_expiry_is_exclusive(self):
        self.assert_rejected(envelope(expires_at=BASE), "STALE_ENVELOPE")
        self.assert_rejected(envelope(expires_at=BASE + 3 * HOUR), "HORIZON_UNSUPPORTED")
        self.assertEqual(assess_funding_budget(envelope()).status, Readiness.SUFFICIENT)

    def test_late_envelope_evidence(self):
        self.assert_rejected(envelope(available_at=BASE + 1), "FUTURE_UNAVAILABLE")

    def test_scenario_availability_boundary(self):
        path = scenario()
        self.assertEqual(assess_funding_budget(envelope((replace(path, available_at=BASE),))).status, Readiness.SUFFICIENT)
        self.assert_rejected(envelope((replace(path, available_at=BASE + 1),)), "FUTURE_UNAVAILABLE")

    def test_unavailable_payload_changes_do_not_change_earlier_diagnostic(self):
        path = replace(scenario(), available_at=BASE + 1)
        altered = replace(path, claim=replace(path.claim, observations=(replace(path.claim.observations[0], rate=D("NaN")),)))
        self.assertEqual(assess_funding_budget(envelope((path,))), assess_funding_budget(envelope((altered,))))

    def test_unavailable_envelope_does_not_evaluate_future_claim(self):
        with patch("demo_futures.risk_remediation.funding_budget.assess_funding", side_effect=AssertionError("future evaluated")):
            self.assert_rejected(envelope(available_at=BASE + 1), "FUTURE_UNAVAILABLE")

    def test_unavailable_envelope_payload_is_not_interpreted(self):
        value = envelope(available_at=BASE + 1)
        changed = replace(value, entry_price=D("NaN"), source_id="../unknown", evidence_identity=None)
        self.assertEqual(assess_funding_budget(value), assess_funding_budget(changed))

    def test_unavailable_scenario_does_not_evaluate_any_claim(self):
        paths = (scenario(), replace(scenario(identity="path-b"), available_at=BASE + 1))
        with patch("demo_futures.risk_remediation.funding_budget.assess_funding", side_effect=AssertionError("future evaluated")):
            self.assert_rejected(envelope(paths), "FUTURE_UNAVAILABLE")

    def test_exact_time_order_and_negative_times(self):
        for change in ({"decision_time": BASE + 1}, {"as_of": BASE - 2}, {"as_of": BASE + 1},
                       {"holding_end": BASE}, {"closure_end": BASE + HOUR}, {"available_at": -1}):
            with self.subTest(change=change):
                self.assert_rejected(envelope(**change), "INVALID_TIME", Readiness.INVALID)

    def test_noninteger_and_boolean_times_rejected_at_schema(self):
        for value in (True, 1.0, "1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                envelope(as_of=value)

    def test_entry_time_settlement_excluded(self):
        self.assert_rejected(envelope((scenario(((BASE, ".002", "100"),)),)), "FUNDING_CONTRACT_INVALID")

    def test_first_owned_millisecond_and_last_closure_timestamp(self):
        path = scenario(((BASE + 1, ".002", "100"), (BASE + 3 * HOUR, ".002", "100")))
        self.assertEqual(assess_funding_budget(envelope((path,))).worst_case_debit, 4)

    def test_after_closure_is_not_owned(self):
        path = scenario(((BASE + 3 * HOUR + 1, ".002", "100"),))
        self.assert_rejected(envelope((path,)), "FUNDING_CONTRACT_INVALID")

    def test_closure_delay_is_included_not_only_planned_hold(self):
        path = scenario(((BASE + 3 * HOUR, ".007", "100"),))
        self.assertEqual(assess_funding_budget(envelope((path,))).worst_case_debit, 7)

    def test_no_default_closure_delay_required_explicitly(self):
        with self.assertRaises(TypeError):
            SyntheticFundingStressEnvelope()

    def test_duplicate_and_unordered_settlements(self):
        for rows in (((BASE + HOUR, ".002", "100"),) * 2,
                     ((BASE + 2 * HOUR, ".002", "100"), (BASE + HOUR, ".002", "100"))):
            with self.subTest(rows=rows):
                self.assert_rejected(envelope((scenario(rows),)), "FUNDING_CONTRACT_INVALID")

    def test_duplicate_scenario_ids(self):
        self.assert_rejected(envelope((scenario(), scenario())), "DUPLICATE_SCENARIO")

    def test_scope_symbol_interval_side(self):
        for change in ({"symbol": "SOLUSDT"}, {"interval": "1h"}, {"side": "NO TRADE"}):
            with self.subTest(change=change):
                self.assert_rejected(envelope(**change), "UNSUPPORTED_SCOPE")

    def test_eth_consistent_binding_supported(self):
        path = scenario()
        path = replace(path, claim=replace(path.claim, symbol="ETHUSDT", schedule=replace(path.claim.schedule, symbol="ETHUSDT")))
        self.assertEqual(assess_funding_budget(envelope((path,), symbol="ETHUSDT")).allowance, 2)

    def test_identity_and_evidence_purpose_binding(self):
        for change in ({"source_id": "../unsafe"}, {"version": ""}):
            self.assert_rejected(envelope(**change), "INVALID_IDENTITY")
        for identity in (replace(evidence("FUNDING_STRESS_ENVELOPE"), revision="v2"), evidence("NO_SETTLEMENT"),
                         replace(evidence("FUNDING_STRESS_ENVELOPE"), basis="AUTHENTICATED")):
            self.assert_rejected(envelope(evidence_identity=identity), "INVALID_EVIDENCE")

    def test_wrong_source_revision_and_full_horizon_binding(self):
        path = scenario()
        for change in ({"revision": "v2"}, {"symbol": "ETHUSDT"}, {"end": BASE + 2 * HOUR + 1}, {"start": BASE}):
            with self.subTest(change=change):
                self.assert_rejected(envelope((replace(path, claim=replace(path.claim, **change)),)), "INCONSISTENT_SCOPE")

    def test_missing_mark_or_timing_evidence(self):
        path = scenario()
        for change in ({"mark_price": None}, {"mark_evidence": None}, {"timing_evidence": None}):
            event = replace(path.claim.observations[0], **change)
            self.assert_rejected(envelope((replace(path, claim=replace(path.claim, observations=(event,))),)), "FUNDING_CONTRACT_INSUFFICIENT")

    def test_nonfinite_and_nonpositive_entry_numbers(self):
        for value in (D("NaN"), D("Infinity"), D("-Infinity"), D(0), D(-1)):
            for name in ("entry_price", "entry_notional"):
                with self.subTest(name=name, value=value):
                    self.assert_rejected(envelope(**{name: value}), "INVALID_NUMBER")

    def test_boolean_float_string_numeric_inputs_not_coerced(self):
        for value in (True, 100.0, "100"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                envelope(entry_notional=value)

    def test_nonfinite_settlement_numbers_invalid(self):
        path = scenario()
        for name in ("rate", "mark_price"):
            for value in (D("NaN"), D("Infinity")):
                event = replace(path.claim.observations[0], **{name: value})
                self.assert_rejected(envelope((replace(path, claim=replace(path.claim, observations=(event,))),)), "FUNDING_CONTRACT_INVALID")

    def test_boolean_settlement_numbers_and_mutable_claims_refused(self):
        path = scenario()
        for claim in (replace(path.claim, observations=list(path.claim.observations)),
                      replace(path.claim, observations=(replace(path.claim.observations[0], rate=True),)),
                      replace(path.claim, schedule=replace(path.claim.schedule, complete="false"))):
            with self.assertRaises(ValueError):
                replace(path, claim=claim)

    def test_nested_mutability_cannot_enter_immutable_envelope(self):
        path = scenario()
        schedule = replace(path.claim.schedule, expected_settlements=list(path.claim.schedule.expected_settlements))
        with self.assertRaises(ValueError):
            replace(path, claim=replace(path.claim, schedule=schedule))

    def test_tampered_nested_payload_is_revalidated(self):
        value = envelope()
        object.__setattr__(value.scenarios[0].claim, "observations", [])
        self.assert_rejected(value, "INVALID_SCHEMA")

    def test_invalid_dominates_insufficient_with_ordered_reasons(self):
        value = envelope(evidence_identity=replace(evidence("FUNDING_STRESS_ENVELOPE"), revision="other"), scenarios=())
        output = self.assert_rejected(value, "INVALID_EVIDENCE", Readiness.INVALID)
        self.assertEqual(output.reasons, ("INVALID_EVIDENCE", "MISSING_SCENARIOS"))

    def test_reference_reserve_drift_refused(self):
        class ChangedConfig:
            funding_reserve_rate = D(".002")
        with patch("demo_futures.risk_remediation.funding_budget.BacktestConfig", ChangedConfig):
            self.assert_rejected(envelope(), "REFERENCE_RESERVE_CHANGED")

    def test_missing_declared_settlement_and_conflicting_mark(self):
        path = scenario()
        for claim in (replace(path.claim, schedule=replace(path.claim.schedule,
                         expected_settlements=(BASE + HOUR, BASE + 2 * HOUR))),
                      replace(path.claim, observations=(replace(path.claim.observations[0], mark_price=D(-1)),))):
            with self.subTest(claim=claim):
                output = assess_funding_budget(envelope((replace(path, claim=claim),)))
                self.assertNotEqual(output.status, Readiness.SUFFICIENT)
                self.assertIsNone(output.allowance)

    def test_immutable_envelope_scenario_and_diagnostic(self):
        value = envelope()
        output = assess_funding_budget(value)
        for obj, name, replacement in ((value, "side", "SHORT"), (value.scenarios[0], "scenario_id", "other"),
                                       (output, "allowance", D(99))):
            with self.assertRaises(FrozenInstanceError):
                setattr(obj, name, replacement)
        with self.assertRaises(ValueError):
            envelope(paths=[scenario()])

    def test_forged_mutable_scenario_id_fails_closed(self):
        path = scenario()
        object.__setattr__(path, "scenario_id", [])
        self.assert_rejected(envelope((path,)), "INVALID_IDENTITY")

    def test_foreign_input_not_inspected(self):
        class Foreign:
            def __getattribute__(self, name):
                raise AssertionError("foreign input inspected")
        self.assert_rejected(Foreign(), "INVALID_SCHEMA")

    def test_tampered_envelope_shape_revalidated(self):
        value = envelope()
        object.__setattr__(value, "as_of", True)
        self.assert_rejected(value, "INVALID_SCHEMA")

    def test_arithmetic_overflow_and_underflow_fail_closed(self):
        self.assert_rejected(envelope(entry_notional=D("1e1001")), "ARITHMETIC_UNSUPPORTED")
        self.assert_rejected(envelope(entry_notional=D("1e-1100")), "ARITHMETIC_UNSUPPORTED")

    def test_diagnostic_cannot_invent_money_or_hide_inconsistency(self):
        result = assess_funding_budget(envelope())
        with self.assertRaises(ValueError):
            replace(result, allowance=D(99))
        with self.assertRaises(ValueError):
            FundingBudgetDiagnostic(Readiness.INSUFFICIENT, ("MISSING_EVIDENCE",), reserve_floor=D(1))
        with self.assertRaises(ValueError):
            FundingBudgetDiagnostic(Readiness.INSUFFICIENT, ("UNREVIEWED_REASON",))

    def test_no_admission_authority_and_truth_testing(self):
        result = assess_funding_budget(envelope())
        self.assertEqual(result.evidence, "SYNTHETIC_ONLY")
        self.assertEqual(result.risk_clearance, "NOT CLEARED")
        for name in ("approved", "quantity", "order", "events", "execution_enabled", "allow_missing_funding"):
            self.assertFalse(hasattr(result, name))
        with self.assertRaises(TypeError):
            bool(result)

    def test_assessment_performs_no_io(self):
        value = envelope()
        with patch("builtins.open", side_effect=AssertionError("I/O")), patch("io.open", side_effect=AssertionError("I/O")):
            self.assertEqual(assess_funding_budget(value).allowance, 2)

    def test_static_import_and_call_boundary(self):
        source = Path(__file__).resolve().parents[1] / "src/demo_futures/risk_remediation/funding_budget.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        self.assertEqual(imports, {"dataclasses", "decimal", "risk", "research_v2.config",
            "research_v2.contracts", "research_v2.funding_contracts"})
        self.assertFalse(any(isinstance(node, ast.Import) for node in ast.walk(tree)))
        forbidden = {"open", "read_text", "write_text", "size_position", "run", "request", "connect", "fit", "predict"}
        calls = {node.func.id if isinstance(node.func, ast.Name) else node.func.attr
                 for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, (ast.Name, ast.Attribute))}
        self.assertFalse(calls & forbidden)
