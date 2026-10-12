"""Invented boundary contexts only; no historical evidence or market inputs."""
from dataclasses import FrozenInstanceError, fields, is_dataclass, replace
from decimal import Decimal
import unittest
from unittest.mock import patch

from demo_futures.data import Candle
from demo_futures.research_v2.config import HOUR, STEP
from demo_futures.research_v2.contracts import EvidenceIdentity, Readiness, result
from demo_futures.research_v2.features import ObservedCandle, SyntheticSeries
from demo_futures.research_v2.funding_contracts import (
    CoverageRequirement, CoverageState, FundingAssessment, FundingClaim,
    ScheduleEvidence, SettlementObservation,
)
from demo_futures.research_v2.loader_boundary import (
    BoundaryRequest, assess_boundary, required_coverage, validate_request,
)
from demo_futures.research_v2.source_contracts import (
    AvailabilityMode, OriginalAvailability, ScopedHashMetadata, SourceMetadata,
    TARGET_END, TARGET_START,
)


def request(**changes):
    values = dict(symbols=("BTCUSDT", "ETHUSDT"), start=TARGET_START,
                  end=TARGET_START + 22 * HOUR, decision_time=TARGET_START + 18 * HOUR - 1,
                  scope_id="invented-boundary", source_id="invented-source", revision="r1",
                  mode=AvailabilityMode.EXPLORATORY_CLOSED_BAR_APPROXIMATION)
    values.update(changes)
    return BoundaryRequest(**values)


def evidence(req, assertion):
    return EvidenceIdentity("fixture-" + assertion, req.source_id, req.revision, assertion)


def contexts(req):
    """Fictional prices/receipts/schedules at declared UTC dates, never market records."""
    sources, funding, series = [], [], []
    for symbol in req.symbols:
        digest = ScopedHashMetadata("a" * 64, req.source_id, req.revision, symbol,
                                    "5m", req.start, req.end)
        sources.append(SourceMetadata(
            req.scope_id, req.source_id, req.revision, symbol, "5m", req.start, req.end,
            req.decision_time, req.end + HOUR, req.mode, OriginalAvailability.UNKNOWN,
            evidence(req, "SOURCE_IDENTITY"), evidence(req, "APPROVED_SYNTHETIC_SCOPE"), digest))
        event_time = req.end - 123  # Deliberately not a nominal eight-hour slot.
        event = SettlementObservation(event_time, Decimal("-.001"), Decimal("100"),
                                      evidence(req, "SETTLEMENT_TIME_AND_RATE"),
                                      evidence(req, "SETTLEMENT_MARK"))
        schedule = ScheduleEvidence(symbol, req.start, req.end,
                                    evidence(req, "SETTLEMENT_SCHEDULE"), (event_time,), True)
        funding.append(FundingClaim(symbol, req.start, req.end, req.source_id, req.revision,
                                    CoverageState.KNOWN_EVENTS, (event,), schedule))
        bars = tuple(Candle(t, 100., 100.5, 99.5, 100., 100., t + STEP - 1, 10000., 10)
                     for t in range(req.start, req.end, STEP))
        series.append(SyntheticSeries(symbol, tuple(ObservedCandle(c, c.close_time + 1)
                                                   for c in bars), req.source_id))
    return tuple(sources), tuple(funding), tuple(series)


def assess(req=None, *, sources=None, funding=None, series=None):
    req = request() if req is None else req
    defaults = contexts(req)
    return assess_boundary(req, sources=defaults[0] if sources is None else sources,
                           funding=defaults[1] if funding is None else funding,
                           series=defaults[2] if series is None else series)


class RequestTests(unittest.TestCase):
    def test_valid_request_and_full_inventory(self):
        req = request()
        self.assertEqual(validate_request(req).status, Readiness.SUFFICIENT)
        self.assertEqual(required_coverage(req), tuple(CoverageRequirement(s, req.start, req.end)
                                                     for s in req.symbols))

    def test_single_symbol_and_canonical_symbol_order(self):
        self.assertEqual(tuple(c.symbol for c in required_coverage(request(symbols=("ETHUSDT",)))), ("ETHUSDT",))
        self.assertEqual(required_coverage(request(symbols=("ETHUSDT", "BTCUSDT"))), required_coverage(request()))

    def test_wrong_symbols_intervals_and_evidence(self):
        for changes, reason in (({"symbols": ("XRPUSDT",)}, "WRONG_SYMBOL"),
                                ({"symbols": ("SOLUSDT",)}, "WRONG_SYMBOL"),
                                ({"symbols": ("BNBUSDT",)}, "WRONG_SYMBOL"),
                                ({"interval": "15m"}, "WRONG_INTERVAL"),
                                ({"evidence": "AUTHENTICATED_HISTORY"}, "UNAPPROVED_SCOPE")):
            with self.subTest(changes=changes):
                req = request(**changes)
                self.assertIn(reason, assess_boundary(req).validation.reasons)
                with self.assertRaises(ValueError): required_coverage(req)

    def test_empty_duplicate_symbols_and_unsafe_identity(self):
        for req in (request(symbols=()), request(symbols=("BTCUSDT", "BTCUSDT")),
                    request(source_id="../outside"), request(scope_id="")):
            self.assertEqual(validate_request(req).status, Readiness.INVALID)

    def test_immutable_typed_request_rejects_mutable_or_nonprimitive_fields(self):
        for changes in ({"symbols": ["BTCUSDT"]}, {"start": True}, {"end": float("inf")},
                        {"decision_time": "later"}, {"source_id": object()}, {"mode": "approximation"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): request(**changes)
        with self.assertRaises(FrozenInstanceError): request().end = TARGET_END

    def test_wrong_bounds_grid_and_decision_are_rejected(self):
        for req in (request(start=TARGET_START - STEP), request(end=TARGET_START),
                    request(end=TARGET_START + 1), request(start=-STEP),
                    request(decision_time=TARGET_START), request(decision_time=TARGET_END)):
            self.assertNotEqual(validate_request(req).status, Readiness.SUFFICIENT)

    def test_protected_overlap_and_exact_end_boundary(self):
        self.assertEqual(validate_request(request(end=TARGET_END)).status, Readiness.SUFFICIENT)
        for end in (TARGET_END + STEP, TARGET_END + 30 * 24 * HOUR):
            self.assertIn("PROTECTED_PERIOD", validate_request(request(end=end)).reasons)

    def test_foreign_or_forged_request_fails_closed(self):
        self.assertEqual(assess_boundary(result()).validation.status, Readiness.INVALID)
        forged = request()
        object.__setattr__(forged, "mode", "FORGED")
        self.assertEqual(validate_request(forged).status, Readiness.INVALID)


class BoundaryTests(unittest.TestCase):
    def test_consistent_contexts_produce_inert_diagnostics_only(self):
        out = assess()
        self.assertEqual(out.validation.status, Readiness.SUFFICIENT)
        self.assertEqual(tuple(d.symbol for d in out.symbols), ("BTCUSDT", "ETHUSDT"))
        self.assertEqual(out.authority, "INERT_VALIDATION_ONLY")
        self.assertEqual(out.historical_evidence, "UNAUTHENTICATED / NOT VERIFIED")
        self.assertEqual(out.risk_clearance, "NOT CLEARED")

    def test_request_not_observed_events_derives_inventory(self):
        req = request(); sources, claims, bars = contexts(req)
        empty = tuple(replace(c, observations=(), schedule=None) for c in claims)
        self.assertEqual(assess(req, funding=empty).required_coverage, assess(req).required_coverage)
        missing = assess(req, funding=())
        self.assertEqual(missing.required_coverage, required_coverage(req))
        self.assertEqual(missing.validation.status, Readiness.INSUFFICIENT)

    def test_missing_coverage_cell_refuses_full_readiness(self):
        req = request(); claims = contexts(req)[1]
        out = assess(req, funding=claims[:1])
        self.assertIn("FUNDING_COVERAGE_UNPROVEN", out.validation.reasons)
        self.assertEqual(out.symbols[1].coverage_state, CoverageState.UNKNOWN)

    def test_duplicate_and_conflicting_coverage_cells_are_invalid(self):
        req = request(); claims = contexts(req)[1]
        for duplicate in (claims[0], replace(claims[0], source_id="other")):
            self.assertIn("SOURCE_CONFLICT", assess(req, funding=claims + (duplicate,)).validation.reasons)

    def test_partial_or_undeclared_funding_bounds_are_invalid(self):
        req = request(); claims = contexts(req)[1]
        for changed in (replace(claims[0], start=req.start + STEP),
                        replace(claims[0], end=req.end - STEP),
                        replace(claims[0], end=req.end + STEP)):
            self.assertIn("UNAUTHORIZED_DATES", assess(req, funding=(changed, claims[1])).validation.reasons)

    def test_overlapping_or_partitioned_cells_are_not_merged(self):
        req = request(); claims = contexts(req)[1]
        for cut in (req.start + HOUR, req.end - HOUR):
            rows = (replace(claims[0], end=cut), replace(claims[0], start=cut - STEP), claims[1])
            self.assertIn("SOURCE_CONFLICT", assess(req, funding=rows).validation.reasons)

    def test_missing_source_and_quality_contexts_are_insufficient(self):
        for changes, reason in (({"sources": ()}, "SOURCE_IDENTITY_MISMATCH"),
                                ({"series": ()}, "CAUSAL_INPUT_INVALID")):
            out = assess(**changes)
            self.assertEqual(out.validation.status, Readiness.INSUFFICIENT)
            self.assertIn(reason, out.validation.reasons)

    def test_duplicate_or_undeclared_source_and_series_are_rejected(self):
        req = request(); sources, claims, bars = contexts(req)
        for name, rows in (("sources", sources + sources[:1]), ("series", bars + bars[:1])):
            self.assertIn("SOURCE_CONFLICT", assess(req, **{name: rows}).validation.reasons)
        only_btc = request(symbols=("BTCUSDT",))
        self.assertIn("UNAPPROVED_SCOPE", assess(only_btc, sources=sources).validation.reasons)
        self.assertIn("WRONG_SYMBOL", assess(req, sources=(replace(sources[0], symbol="XRPUSDT"),)).validation.reasons)

    def test_source_revision_scope_mode_and_decision_binding(self):
        req = request(); sources, claims, bars = contexts(req)
        for changed, reason in ((replace(sources[0], source_id="other"), "SOURCE_IDENTITY_MISMATCH"),
                                (replace(sources[0], revision="r2"), "REVISION_MISMATCH"),
                                (replace(sources[0], scope_id="other"), "UNAPPROVED_SCOPE"),
                                (replace(sources[0], mode=AvailabilityMode.REQUIRE_VERIFIED_ASOF), "UNAPPROVED_SCOPE"),
                                (replace(sources[0], decision_time=req.decision_time - HOUR), "INVALID_SCHEMA_OR_TIME")):
            self.assertIn(reason, assess(req, sources=(changed, sources[1])).validation.reasons)

    def test_funding_and_fixture_source_binding(self):
        req = request(); sources, claims, bars = contexts(req)
        for changed, reason in ((replace(claims[0], source_id="other"), "SOURCE_IDENTITY_MISMATCH"),
                                (replace(claims[0], revision="r2"), "REVISION_MISMATCH")):
            self.assertIn(reason, assess(req, funding=(changed, claims[1])).validation.reasons)
        self.assertIn("SOURCE_IDENTITY_MISMATCH", assess(req, series=(replace(bars[0], fixture_id="other"), bars[1])).validation.reasons)

    def test_precomputed_results_cannot_replace_raw_evidence(self):
        req = request()
        forged = FundingAssessment(result(), CoverageState.KNOWN_EVENTS, "BTCUSDT", req.start, req.end)
        for changes in ({"funding": (forged,)}, {"sources": (result(),)}, {"series": (result(),)}):
            self.assertIn("INVALID_EVIDENCE", assess(req, **changes).validation.reasons)

    def test_synthetic_no_settlement_never_becomes_financial_context(self):
        req = request(); claims = contexts(req)[1]
        empty = tuple(replace(c, state=CoverageState.KNOWN_NO_SETTLEMENT, observations=(),
                              schedule=replace(c.schedule, expected_settlements=(), identity=evidence(req, "NO_SETTLEMENT")))
                      for c in claims)
        out = assess(req, funding=empty)
        self.assertEqual(out.validation.status, Readiness.SUFFICIENT)
        self.assertTrue(all(d.coverage_state == CoverageState.KNOWN_NO_SETTLEMENT for d in out.symbols))
        self.assertFalse(hasattr(out, "events"))
        self.assertFalse(hasattr(out, "allow_missing_funding"))

    def test_forged_authenticated_evidence_and_missing_schedule_are_refused(self):
        req = request(); sources, claims, bars = contexts(req)
        forged = replace(sources[0], source_evidence=replace(sources[0].source_evidence, basis="AUTHENTICATED_HISTORY"))
        self.assertIn("INVALID_EVIDENCE", assess(req, sources=(forged, sources[1])).validation.reasons)
        bad = replace(claims[0], evidence="REAL_HISTORY")
        self.assertIn("UNAPPROVED_SCOPE", assess(req, funding=(bad, claims[1])).validation.reasons)
        missing = replace(claims[0], schedule=None)
        self.assertEqual(assess(req, funding=(missing, claims[1])).validation.status, Readiness.INSUFFICIENT)

    def test_missing_settlement_mark_and_timing_support(self):
        req = request(); claims = contexts(req)[1]; c = claims[0]; event = c.observations[0]
        for changed, reason in ((replace(c, schedule=replace(c.schedule, expected_settlements=(req.start, event.timestamp))), "MISSING_EXPECTED_SETTLEMENT"),
                                (replace(c, observations=(replace(event, mark_price=None),)), "MARK_UNSUPPORTED"),
                                (replace(c, observations=(replace(event, timing_evidence=None),)), "FUNDING_TIME_UNCERTAIN")):
            self.assertIn(reason, assess(req, funding=(changed, claims[1])).validation.reasons)

    def test_nonfinite_funding_values_are_invalid(self):
        req = request(); claims = contexts(req)[1]; c = claims[0]
        for event in (replace(c.observations[0], rate=Decimal("NaN")),
                      replace(c.observations[0], mark_price=Decimal("Infinity"))):
            self.assertEqual(assess(req, funding=(replace(c, observations=(event,)), claims[1])).validation.status,
                             Readiness.INVALID)

    def test_strict_unknown_original_receipts_remain_insufficient(self):
        req = request(mode=AvailabilityMode.REQUIRE_VERIFIED_ASOF)
        self.assertIn("ORIGINAL_RECEIPT_UNKNOWN", assess(req).validation.reasons)

    def test_internally_consistent_strict_receipts_remain_unauthenticated(self):
        req = request(mode=AvailabilityMode.REQUIRE_VERIFIED_ASOF)
        sources = tuple(replace(m, original_availability=OriginalAvailability.VERIFIED,
                                original_receipt=req.decision_time + 1,
                                availability_evidence=evidence(req, "ORIGINAL_ASOF_RECEIPT")) for m in contexts(req)[0])
        out = assess(req, sources=sources)
        self.assertEqual(out.validation.status, Readiness.SUFFICIENT)
        self.assertEqual(out.historical_evidence, "UNAUTHENTICATED / NOT VERIFIED")

    def test_approximation_preserves_unknown_and_actual_supplied_receipts(self):
        req = request(); sources = contexts(req)[0]
        out = assess(req)
        for d, m in zip(out.symbols, sources):
            self.assertEqual(d.original_availability, OriginalAvailability.UNKNOWN)
            self.assertEqual(d.retrieved_at, m.retrieved_at)
            self.assertIsNone(d.original_receipt)

    def test_approximation_does_not_accept_unsupported_or_late_verified_claims(self):
        req = request(); sources = contexts(req)[0]
        unsupported = replace(sources[0], original_availability=OriginalAvailability.VERIFIED)
        self.assertIn("ORIGINAL_AVAILABILITY_UNSUPPORTED", assess(req, sources=(unsupported, sources[1])).validation.reasons)
        late = replace(unsupported, original_receipt=req.decision_time + 2,
                       availability_evidence=evidence(req, "ORIGINAL_ASOF_RECEIPT"))
        self.assertIn("RECEIPT_LATE", assess(req, sources=(late, sources[1])).validation.reasons)

    def test_approximation_cannot_bypass_causal_observation_receipts(self):
        req = request(); bars = contexts(req)[2]; observations = list(bars[0].observations)
        observations[215] = replace(observations[215], available_at=req.decision_time + 2)
        out = assess(req, series=(replace(bars[0], observations=tuple(observations)), bars[1]))
        self.assertEqual(out.symbols[0].causal.reasons, ("RECEIPT_LATE",))

    def test_candle_gap_and_missing_full_horizon_remain_incomplete(self):
        req = request(); bars = contexts(req)[2]
        for observations in (bars[0].observations[:20] + bars[0].observations[21:], bars[0].observations[:-1]):
            out = assess(req, series=(replace(bars[0], observations=observations), bars[1]))
            self.assertIn("CANDLE_GAP", out.validation.reasons)

    def test_truncated_prefix_never_reseeds_or_calls_quality(self):
        req = request(symbols=("BTCUSDT",)); bars = contexts(req)[2]
        truncated = replace(bars[0], observations=bars[0].observations[16:])
        with patch("demo_futures.research_v2.loader_boundary.assess_candles", side_effect=AssertionError("No reseeding")):
            out = assess(req, series=(truncated,))
        self.assertEqual(out.symbols[0].causal.reasons, ("CANDLE_GAP",))

    def test_exact_199_200_warmup_preserves_frozen_eligibility(self):
        for count, status in ((199, Readiness.INSUFFICIENT), (200, Readiness.SUFFICIENT)):
            req = request(start=TARGET_START + (216 - count) * STEP)
            out = assess(req)
            self.assertEqual(out.symbols[0].causal.status, status)
            if count == 199: self.assertIn("INSUFFICIENT_WARMUP", out.validation.reasons)

    def test_future_anomaly_changes_quality_not_earlier_causal_diagnostic(self):
        req = request(); bars = contexts(req)[2]; observations = list(bars[0].observations)
        observations[250] = replace(observations[250], candle=replace(observations[250].candle, close=float("nan")))
        changed = assess(req, series=(replace(bars[0], observations=tuple(observations)), bars[1]))
        self.assertEqual(changed.validation.status, Readiness.INVALID)
        self.assertEqual(changed.symbols[0].causal, assess(req).symbols[0].causal)

    def test_review_flags_do_not_become_new_filters(self):
        req = request(); bars = contexts(req)[2]; observations = list(bars[0].observations)
        observations[215] = replace(observations[215], candle=replace(observations[215].candle, high=103., low=97.))
        out = assess(req, series=(replace(bars[0], observations=tuple(observations)), bars[1]))
        self.assertEqual(out.validation.status, Readiness.SUFFICIENT)
        self.assertIn("RANGE_GT_5_PERCENT_REVIEW_ONLY", tuple(f.reason for f in out.symbols[0].flags))
        self.assertEqual(out.symbols[0].market_realism, "UNKNOWN / NOT CERTIFIED")

    def test_foreign_capabilities_are_rejected_without_inspection(self):
        class Poison:
            def __getattr__(self, name): raise AssertionError("Foreign input was inspected")
        for changes in ({"sources": (Poison(),)}, {"funding": (lambda: None,)}, {"series": (Poison(),)}):
            self.assertEqual(assess(**changes).validation.status, Readiness.INVALID)
        req = request(); sources = contexts(req)[0]
        self.assertEqual(assess(req, sources=(replace(sources[0], scoped_hash=Poison()),)).validation.status, Readiness.INVALID)

    def test_malformed_nested_plain_values_fail_closed(self):
        req = request(); sources, claims, bars = contexts(req)
        cases = ({"sources": (replace(sources[0], start="bad"), sources[1])},
                 {"funding": (replace(claims[0], schedule=replace(claims[0].schedule, expected_settlements=("bad",))), claims[1])},
                 {"series": [bars[0]]})
        for changes in cases:
            self.assertEqual(assess(req, **changes).validation.status, Readiness.INVALID)

    def test_no_io_and_input_values_are_preserved(self):
        req = request(); inputs = contexts(req); before = tuple(repr(v) for v in inputs)
        with patch("builtins.open", side_effect=AssertionError("Boundary cannot access files")):
            out = assess_boundary(req, sources=inputs[0], funding=inputs[1], series=inputs[2])
        self.assertEqual(out.validation.status, Readiness.SUFFICIENT)
        self.assertEqual(before, tuple(repr(v) for v in inputs))

    def test_result_has_no_payload_or_executable_capability(self):
        out = assess()
        forbidden = (SourceMetadata, FundingClaim, FundingAssessment, SyntheticSeries, ObservedCandle, Candle, Decimal)
        def inspect(value):
            self.assertNotIsInstance(value, forbidden)
            self.assertFalse(callable(value))
            if is_dataclass(value):
                for f in fields(value): inspect(getattr(value, f.name))
            elif type(value) is tuple:
                for child in value: inspect(child)
        inspect(out)
        for name in ("load", "open", "fit", "dataset", "labels", "source_handle", "allow_access", "activate"):
            self.assertFalse(hasattr(out, name))
        with self.assertRaises(TypeError): bool(out)
        with self.assertRaises(FrozenInstanceError): out.authority = "AUTHORIZED"

    def test_diagnostic_constructors_reject_payloads_and_mutable_members(self):
        out = assess(); payload = contexts(request())[2][0]
        for changes in ({"validation": payload}, {"symbols": [out.symbols[0]]},
                        {"symbols": (payload,)}, {"required_coverage": list(out.required_coverage)}):
            with self.subTest(changes=tuple(changes)), self.assertRaises(ValueError): replace(out, **changes)
        for changes in ({"source": payload}, {"flags": []}, {"retrieved_at": True}):
            with self.subTest(changes=tuple(changes)), self.assertRaises(ValueError): replace(out.symbols[0], **changes)

    def test_out_of_scope_candles_and_nested_capabilities_are_refused(self):
        req = request(); sources, claims, bars = contexts(req)
        extra = replace(bars[0].observations[-1].candle, open_time=req.end, close_time=req.end + STEP - 1)
        changed = replace(bars[0], observations=bars[0].observations + (ObservedCandle(extra, extra.close_time + 1),))
        self.assertIn("UNAUTHORIZED_DATES", assess(req, series=(changed, bars[1])).validation.reasons)
        fake = replace(sources[0], source_evidence=replace(sources[0].source_evidence, identity=lambda: None))
        self.assertIn("INVALID_EVIDENCE", assess(req, sources=(fake, sources[1])).validation.reasons)

    def test_deterministic_rejections_and_input_order(self):
        req = request(); sources, claims, bars = contexts(req)
        self.assertEqual(assess(req), assess(req, sources=sources[::-1], funding=claims[::-1], series=bars[::-1]))
        bad = request(symbols=("XRPUSDT",), interval="15m", evidence="REAL")
        a = assess_boundary(bad); b = assess_boundary(bad)
        self.assertEqual(a, b)
        self.assertEqual(a.validation.reasons, ("UNAPPROVED_SCOPE", "WRONG_SYMBOL", "WRONG_INTERVAL"))


if __name__ == "__main__":
    unittest.main()
