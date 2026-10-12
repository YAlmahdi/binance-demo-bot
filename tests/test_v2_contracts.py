"""Invented fixtures only; contract assertions are not historical evidence."""
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal as D
import unittest
from unittest.mock import patch

from demo_futures.research_v2.contracts import *
from demo_futures.research_v2.funding_contracts import *
from demo_futures.research_v2.source_contracts import *
from demo_futures.research_v2.quality_contracts import assess_candles
from demo_futures.research_v2.config import STEP, HOUR
from demo_futures.research_v2.features import ObservedCandle, SyntheticSeries, feature_at
from demo_futures.data import Candle

BASE = 1262304000000  # Invented 2010 prices/events, not market records.
BOUNDARY = BASE + 18 * HOUR


def evidence(assertion, source="invented-source", revision="r1"):
    return EvidenceIdentity("fixture-" + assertion, source, revision, assertion)


def settlement(t=BASE + 123, rate="-.001", mark="100"):
    return SettlementObservation(t, D(rate), D(mark) if mark is not None else None,
                                 evidence("SETTLEMENT_TIME_AND_RATE"), evidence("SETTLEMENT_MARK"))


def claim(state=CoverageState.KNOWN_EVENTS):
    observations = (settlement(),) if state == CoverageState.KNOWN_EVENTS else ()
    assertion = "SETTLEMENT_SCHEDULE" if state != CoverageState.KNOWN_NO_SETTLEMENT else "NO_SETTLEMENT"
    schedule = ScheduleEvidence("BTCUSDT", BASE, BASE + HOUR, evidence(assertion),
                                tuple(v.timestamp for v in observations), True)
    return FundingClaim("BTCUSDT", BASE, BASE + HOUR, "invented-source", "r1", state,
                        observations, schedule)


def metadata(mode=AvailabilityMode.EXPLORATORY_CLOSED_BAR_APPROXIMATION):
    h = ScopedHashMetadata("a" * 64, "invented-source", "r1", "BTCUSDT", "5m", TARGET_START, TARGET_END)
    return SourceMetadata("engineering-only", "invented-source", "r1", "BTCUSDT", "5m",
                          TARGET_START, TARGET_END, TARGET_START + HOUR - 1, TARGET_END + HOUR,
                          mode, OriginalAvailability.UNKNOWN,
                          evidence("SOURCE_IDENTITY"), evidence("APPROVED_SYNTHETIC_SCOPE"), h)


def expectation():
    return SourceExpectation("engineering-only", "invented-source", "r1")


def candle(i, width=.5):
    start = BASE + i * STEP
    return Candle(start, 100., 100. + width, 100. - width, 100., 100., start + STEP - 1, 10000., 10)


def series(bars=None):
    bars = tuple(candle(i) for i in range(270)) if bars is None else tuple(bars)
    return SyntheticSeries("BTCUSDT", tuple(ObservedCandle(c, c.close_time + 1) for c in bars), "invented-fixture")


class ResultTests(unittest.TestCase):
    def test_order_and_deduplication_are_fixed(self):
        self.assertEqual(result(("SOURCE_CONFLICT", "WRONG_SYMBOL", "SOURCE_CONFLICT"),
                                ("FUNDING_COVERAGE_UNPROVEN",)).reasons,
                         ("WRONG_SYMBOL", "SOURCE_CONFLICT", "FUNDING_COVERAGE_UNPROVEN"))

    def test_result_cannot_hide_failure_or_grant_access(self):
        with self.assertRaises(ValueError): ContractResult(Readiness.SUFFICIENT, ("CANDLE_GAP",))
        with self.assertRaises(ValueError): ContractResult(Readiness.INVALID)
        with self.assertRaises(ValueError): result(("invented-reason",))
        self.assertEqual(result().authority, "INERT_VALIDATION_ONLY")
        with self.assertRaises(FrozenInstanceError): result().status = Readiness.INVALID


class FundingContractTests(unittest.TestCase):
    def test_known_exact_signed_events_and_marks(self):
        c = claim()
        for rate in ("-.001", "0", ".002"):
            event = replace(c.observations[0], rate=D(rate))
            updated = replace(c, observations=(event,))
            out = assess_funding(updated)
            self.assertEqual(out.validation.status, Readiness.SUFFICIENT)
            self.assertEqual(out.state, CoverageState.KNOWN_EVENTS)
            self.assertEqual(updated.observations[0].rate, D(rate))
            self.assertEqual(updated.observations[0].timestamp, BASE + 123)

    def test_empty_enumeration_is_not_complete(self):
        c = replace(claim(), observations=(), schedule=None)
        out = assess_funding(c)
        self.assertEqual(out.state, CoverageState.UNKNOWN)
        self.assertEqual(out.validation.status, Readiness.INSUFFICIENT)
        self.assertIn("EMPTY_CONTEXT_UNSUPPORTED", out.validation.reasons)

    def test_known_no_settlement_is_inert_and_evidenced(self):
        c = claim(CoverageState.KNOWN_NO_SETTLEMENT)
        out = assess_funding(c)
        self.assertEqual(out.state, CoverageState.KNOWN_NO_SETTLEMENT)
        self.assertEqual(out.validation.status, Readiness.SUFFICIENT)
        self.assertFalse(hasattr(out, "events"))  # Not financial adapter context.
        self.assertFalse(hasattr(out, "allow_missing_funding"))

    def test_no_settlement_without_evidence_or_completeness(self):
        c = claim(CoverageState.KNOWN_NO_SETTLEMENT)
        for schedule in (None, replace(c.schedule, identity=None), replace(c.schedule, complete=False)):
            out = assess_funding(replace(c, schedule=schedule))
            self.assertEqual(out.state, CoverageState.UNKNOWN)
            self.assertEqual(out.validation.status, Readiness.INSUFFICIENT)

    def test_contradictory_no_settlement_rejected(self):
        c = claim(CoverageState.KNOWN_NO_SETTLEMENT)
        for changed in (replace(c, observations=(settlement(),)),
                        replace(c, schedule=replace(c.schedule, expected_settlements=(BASE + 123,)))):
            out = assess_funding(changed)
            self.assertEqual(out.validation.status, Readiness.INVALID)
            self.assertIn("SOURCE_CONFLICT", out.validation.reasons)

    def test_missing_expected_settlement_remains_unknown(self):
        c = claim()
        schedule = replace(c.schedule, expected_settlements=(BASE + 123, BASE + 456))
        out = assess_funding(replace(c, schedule=schedule))
        self.assertEqual(out.validation.status, Readiness.INSUFFICIENT)
        self.assertEqual(out.state, CoverageState.UNKNOWN)
        self.assertIn("MISSING_EXPECTED_SETTLEMENT", out.validation.reasons)

    def test_schedule_identity_source_revision_and_purpose(self):
        c = claim()
        for identity in (evidence("WRONG"), evidence("SETTLEMENT_SCHEDULE", source="other"),
                         evidence("SETTLEMENT_SCHEDULE", revision="r2"),
                         replace(evidence("SETTLEMENT_SCHEDULE"), identity="../unsafe")):
            out = assess_funding(replace(c, schedule=replace(c.schedule, identity=identity)))
            self.assertEqual(out.validation.status, Readiness.INVALID)
            self.assertIn("INVALID_EVIDENCE", out.validation.reasons)

    def test_wrong_scope_symbol_and_malformed_inputs(self):
        c = claim()
        for changed, code in ((replace(c, symbol="XRPUSDT"), "WRONG_SYMBOL"),
                              (replace(c, evidence="REAL_HISTORY"), "UNAPPROVED_SCOPE"),
                              (replace(c, start=True), "INVALID_SCHEMA_OR_TIME"),
                              (replace(c, end=c.start), "INVALID_SCHEMA_OR_TIME"),
                              (replace(c, state="KNOWN_EVENTS"), "INVALID_SCHEMA_OR_TIME"),
                              (replace(c, observations=[]), "INVALID_SCHEMA_OR_TIME")):
            self.assertIn(code, assess_funding(changed).validation.reasons)
        self.assertEqual(assess_funding(None).validation.status, Readiness.INVALID)

    def test_duplicates_conflicts_and_order_rejected(self):
        c = claim(); e = c.observations[0]
        for events in ((e, e), (e, replace(e, rate=D(".1"))),
                       (replace(e, timestamp=BASE + 124), e)):
            out = assess_funding(replace(c, observations=events))
            self.assertEqual(out.validation.status, Readiness.INVALID)
            self.assertIn("SOURCE_CONFLICT", out.validation.reasons)

    def test_unsupported_timing_and_marks_do_not_pass(self):
        c = claim(); e = c.observations[0]
        for changed, code in ((replace(e, timing_evidence=None), "FUNDING_TIME_UNCERTAIN"),
                              (replace(e, mark_price=None), "MARK_UNSUPPORTED"),
                              (replace(e, mark_evidence=None), "MARK_UNSUPPORTED")):
            out = assess_funding(replace(c, observations=(changed,)))
            self.assertEqual(out.validation.status, Readiness.INSUFFICIENT)
            self.assertIn(code, out.validation.reasons)
        out = assess_funding(replace(c, observations=(replace(e, timestamp=c.end),)))
        self.assertEqual(out.validation.status, Readiness.INVALID)
        self.assertIn("UNEXPECTED_SETTLEMENT", out.validation.reasons)

    def test_nonfinite_and_nonpositive_inputs_rejected(self):
        c = claim(); e = c.observations[0]
        for changed in (replace(e, rate=D("NaN")), replace(e, rate=D("Infinity")),
                        replace(e, rate=True), replace(e, mark_price=D("NaN")),
                        replace(e, mark_price=D("-1")), replace(e, mark_price=D("0")),
                        replace(e, timestamp=1.5)):
            self.assertEqual(assess_funding(replace(c, observations=(changed,))).validation.status, Readiness.INVALID)

    def test_schedule_bounds_order_duplicates_and_unknown_state(self):
        c = claim()
        for changed in (replace(c.schedule, start=True), replace(c.schedule, end=float("inf")),
                        replace(c.schedule, end=c.end + 1), replace(c.schedule, symbol="ETHUSDT"),
                        replace(c.schedule, expected_settlements=(BASE + 123, BASE + 123)),
                        replace(c.schedule, expected_settlements=(c.end,)),
                        replace(c.schedule, expected_settlements=(float("nan"),))):
            self.assertEqual(assess_funding(replace(c, schedule=changed)).validation.status, Readiness.INVALID)
        self.assertEqual(assess_funding(replace(c, state=CoverageState.UNKNOWN)).validation.status, Readiness.INSUFFICIENT)

    def test_aggregate_preserves_invalid_and_missing_reasons(self):
        good = assess_funding(claim())
        unknown = assess_funding(replace(claim(), symbol="ETHUSDT", schedule=None))
        bad = assess_funding(replace(claim(), symbol="XRPUSDT"))
        required = (CoverageRequirement("BTCUSDT", BASE, BASE + HOUR),)
        self.assertEqual(aggregate_funding((good,), required=required).status, Readiness.SUFFICIENT)
        self.assertEqual(aggregate_funding(()).status, Readiness.INSUFFICIENT)
        both = required + (CoverageRequirement("ETHUSDT", BASE, BASE + HOUR),)
        self.assertEqual(aggregate_funding((good, unknown), required=both).status, Readiness.INSUFFICIENT)
        self.assertEqual(aggregate_funding((unknown, bad)).status, Readiness.INVALID)
        self.assertIn("FUNDING_COVERAGE_UNPROVEN", aggregate_funding((unknown, bad)).reasons)
        self.assertEqual(aggregate_funding((None,)).status, Readiness.INVALID)

    def test_aggregate_requires_explicit_complete_inventory(self):
        good = assess_funding(claim())
        btc = CoverageRequirement("BTCUSDT", BASE, BASE + HOUR)
        eth = CoverageRequirement("ETHUSDT", BASE, BASE + HOUR)
        self.assertEqual(aggregate_funding((good,)).status, Readiness.INSUFFICIENT)
        self.assertEqual(aggregate_funding((good,), required=(btc, eth)).status, Readiness.INSUFFICIENT)
        self.assertEqual(aggregate_funding((good, good), required=(btc,)).status, Readiness.INVALID)
        c = claim(); other = assess_funding(replace(c, symbol="ETHUSDT", schedule=replace(c.schedule, symbol="ETHUSDT")))
        self.assertEqual(aggregate_funding((good, other), required=(btc, eth)).status, Readiness.SUFFICIENT)
        self.assertEqual(aggregate_funding((good,), required=(replace(btc, start=True),)).status, Readiness.INVALID)

    def test_aggregate_cannot_accept_contradictory_state(self):
        with self.assertRaises(ValueError): FundingAssessment(result(), CoverageState.UNKNOWN)
        with self.assertRaises(ValueError): FundingAssessment(result(insufficient=("MARK_UNSUPPORTED",)), CoverageState.KNOWN_EVENTS)

    def test_half_open_funding_bounds_and_unsupported_empty_event_claim(self):
        c = claim(); event = replace(c.observations[0], timestamp=c.start)
        allowed = replace(c, observations=(event,), schedule=replace(c.schedule, expected_settlements=(c.start,)))
        self.assertEqual(assess_funding(allowed).validation.status, Readiness.SUFFICIENT)
        empty = replace(c, observations=(), schedule=replace(c.schedule, expected_settlements=()))
        self.assertEqual(assess_funding(empty).state, CoverageState.UNKNOWN)
        self.assertIn("EMPTY_CONTEXT_UNSUPPORTED", assess_funding(empty).validation.reasons)


class SourceContractTests(unittest.TestCase):
    def test_approximation_unknown_is_metadata_only(self):
        m = metadata(); before = replace(m)
        out = assess_source(m, expectation())
        self.assertEqual(out.status, Readiness.SUFFICIENT)
        self.assertEqual(m, before)
        self.assertEqual(m.original_availability, OriginalAvailability.UNKNOWN)
        self.assertIsNone(m.original_receipt)
        self.assertEqual(m.retrieved_at, TARGET_END + HOUR)
        self.assertEqual(out.authority, "INERT_VALIDATION_ONLY")

    def test_strict_unknown_and_verified_asof(self):
        m = metadata(AvailabilityMode.REQUIRE_VERIFIED_ASOF)
        self.assertEqual(assess_source(m, expectation()).status, Readiness.INSUFFICIENT)
        self.assertIn("ORIGINAL_RECEIPT_UNKNOWN", assess_source(m, expectation()).reasons)
        verified = replace(m, original_availability=OriginalAvailability.VERIFIED,
                           original_receipt=m.decision_time + 1, availability_evidence=evidence("ORIGINAL_ASOF_RECEIPT"))
        self.assertEqual(assess_source(verified, expectation()).status, Readiness.SUFFICIENT)

    def test_late_original_receipt_is_rejected_under_strict_mode(self):
        m = metadata(AvailabilityMode.REQUIRE_VERIFIED_ASOF)
        m = replace(m, original_availability=OriginalAvailability.VERIFIED,
                    original_receipt=m.decision_time + 2, availability_evidence=evidence("ORIGINAL_ASOF_RECEIPT"))
        self.assertEqual(assess_source(m, expectation()).reasons, ("RECEIPT_LATE",))

    def test_unsupported_availability_claim_cannot_be_approximated_away(self):
        m = replace(metadata(), original_availability=OriginalAvailability.VERIFIED)
        self.assertEqual(assess_source(m, expectation()).status, Readiness.INVALID)
        self.assertIn("ORIGINAL_AVAILABILITY_UNSUPPORTED", assess_source(m, expectation()).reasons)

    def test_scope_symbol_interval_source_revision_and_origin(self):
        m = metadata()
        for changed, code in ((replace(m, scope_id="other"), "UNAPPROVED_SCOPE"),
                              (replace(m, symbol="SOLUSDT"), "WRONG_SYMBOL"),
                              (replace(m, symbol="BNBUSDT"), "WRONG_SYMBOL"),
                              (replace(m, symbol="XRPUSDT"), "WRONG_SYMBOL"),
                              (replace(m, interval="15m"), "WRONG_INTERVAL"),
                              (replace(m, source_id=""), "SOURCE_IDENTITY_MISMATCH"),
                              (replace(m, revision="r2"), "REVISION_MISMATCH"),
                              (replace(m, origin="https://unapproved.invalid"), "SOURCE_IDENTITY_MISMATCH"),
                              (replace(m, path="/unapproved"), "SOURCE_IDENTITY_MISMATCH")):
            out = assess_source(changed, expectation())
            self.assertEqual(out.status, Readiness.INVALID)
            self.assertIn(code, out.reasons)

    def test_exact_target_boundary_and_protected_overlap(self):
        m = metadata()
        self.assertEqual(assess_source(m, expectation()).status, Readiness.SUFFICIENT)
        for changed in (replace(m, end=TARGET_END + STEP), replace(m, end=PROTECTED[1][1])):
            out = assess_source(changed, expectation())
            self.assertIn("PROTECTED_PERIOD", out.reasons)
            self.assertEqual(out.status, Readiness.INVALID)
        self.assertIn("UNAUTHORIZED_DATES", assess_source(replace(m, start=TARGET_START - STEP), expectation()).reasons)
        self.assertIn("UNAUTHORIZED_DATES", assess_source(replace(m, end=TARGET_END - STEP), expectation()).reasons)

    def test_unsafe_expected_bounds_and_invalid_time_types(self):
        m = metadata()
        for e in (replace(expectation(), start=TARGET_START - STEP), replace(expectation(), end=TARGET_END + STEP)):
            self.assertIn("UNAUTHORIZED_DATES", assess_source(m, e).reasons)
        for changed in (replace(m, start=True), replace(m, end=float("nan")),
                        replace(m, retrieved_at=TARGET_END - 1), replace(m, decision_time=TARGET_START + 1),
                        replace(m, original_receipt=TARGET_END + 2 * HOUR)):
            self.assertEqual(assess_source(changed, expectation()).status, Readiness.INVALID)
        self.assertEqual(assess_source(None, expectation()).status, Readiness.INVALID)

    def test_missing_and_wrong_evidence_rejected(self):
        m = metadata()
        for changed in (replace(m, source_evidence=None), replace(m, scope_evidence=None),
                        replace(m, scope_evidence=evidence("SOURCE_IDENTITY")),
                        replace(m, availability_evidence=evidence("WRONG"))):
            self.assertIn("INVALID_EVIDENCE", assess_source(changed, expectation()).reasons)

    def test_scoped_hash_is_metadata_and_whole_payload_scope_refused(self):
        m = metadata()
        for h in (None, replace(m.scoped_hash, digest="bad"), replace(m.scoped_hash, scope="WHOLE_DATABASE"),
                  replace(m.scoped_hash, end=TARGET_END + STEP), replace(m.scoped_hash, projection=("*",)),
                  replace(m.scoped_hash, algorithm="md5")):
            self.assertIn("SCOPED_HASH_INVALID", assess_source(replace(m, scoped_hash=h), expectation()).reasons)
        with patch("builtins.open", side_effect=AssertionError("No I/O")):
            self.assertEqual(assess_source(m, expectation()).status, Readiness.SUFFICIENT)

    def test_metadata_cannot_bypass_observed_candle_receipt(self):
        m = metadata(); self.assertEqual(assess_source(m, expectation()).status, Readiness.SUFFICIENT)
        s = series(); late = tuple(replace(o, available_at=max(o.available_at, BOUNDARY + HOUR)) for o in s.observations)
        self.assertEqual(feature_at(replace(s, observations=late), BOUNDARY - 1).reason, "NOT_AVAILABLE_AT_DECISION")
        with self.assertRaises(ValueError): ObservedCandle(candle(0), candle(0).close_time)

    def test_results_are_deterministic_and_pure(self):
        m = replace(metadata(), symbol="XRPUSDT", scope_id="wrong", source_evidence=None)
        self.assertEqual(assess_source(m, expectation()), assess_source(m, expectation()))
        self.assertEqual(assess_source(m, expectation()).reasons[:2], ("UNAPPROVED_SCOPE", "WRONG_SYMBOL"))

    def test_approximation_does_not_accept_a_late_verified_availability_claim(self):
        m = metadata()
        m = replace(m, original_availability=OriginalAvailability.VERIFIED,
                    original_receipt=m.decision_time + 2, availability_evidence=evidence("ORIGINAL_ASOF_RECEIPT"))
        self.assertEqual(assess_source(m, expectation()).reasons, ("RECEIPT_LATE",))

    def test_non_synthetic_metadata_and_malformed_enums_refused(self):
        m = metadata()
        for changed in (replace(m, evidence="HISTORICAL"), replace(m, mode="unknown"),
                        replace(m, original_availability="UNKNOWN"), replace(m, original_receipt=float("inf"))):
            self.assertEqual(assess_source(changed, expectation()).status, Readiness.INVALID)
        self.assertEqual(assess_source(m, replace(expectation(), evidence="HISTORICAL")).status, Readiness.INVALID)


class CandleContractTests(unittest.TestCase):
    def test_valid_structure_and_causality_never_certify_realism(self):
        s = series(); out = assess_candles(s, BOUNDARY - 1)
        self.assertEqual(out.structure.status, Readiness.SUFFICIENT)
        self.assertEqual(out.causal.status, Readiness.SUFFICIENT)
        self.assertEqual(out.market_realism, "UNKNOWN / NOT CERTIFIED")
        self.assertIs(out.observations, s.observations)

    def test_wide_range_is_documentary_flag_not_exclusion(self):
        bars = [candle(i) for i in range(270)]; bars[215] = candle(215, width=3.)
        out = assess_candles(series(bars), BOUNDARY - 1)
        self.assertEqual(out.structure.status, Readiness.SUFFICIENT)
        self.assertEqual(out.causal.status, Readiness.SUFFICIENT)
        self.assertIn("RANGE_GT_5_PERCENT_REVIEW_ONLY", tuple(f.reason for f in out.flags))

    def test_zero_volume_and_flat_preserved_but_decision_ineligible(self):
        bars = [candle(i) for i in range(270)]
        bars[215] = replace(candle(215, width=0), volume=0.)
        s = series(bars); out = assess_candles(s, BOUNDARY - 1)
        self.assertEqual(out.observations[215].candle, bars[215])
        self.assertEqual(out.structure.status, Readiness.SUFFICIENT)
        self.assertEqual(out.causal.status, Readiness.INSUFFICIENT)
        self.assertEqual(out.existing_feature_reason, "ZERO_VOLUME_OR_RANGE_DECISION")
        self.assertEqual(tuple(f.reason for f in out.flags), ("ZERO_VOLUME_REVIEW", "FLAT_BAR_REVIEW"))

    def test_invalid_ohlc_and_nonfinite_are_classified_and_preserved(self):
        for changed in (replace(candle(20), high=99), replace(candle(20), close=float("nan")),
                        replace(candle(20), volume=float("inf")), replace(candle(20), trades=True)):
            bars = [candle(i) for i in range(270)]; bars[20] = changed
            s = series(bars); out = assess_candles(s, BOUNDARY - 1)
            self.assertEqual(out.structure.status, Readiness.INVALID)
            self.assertIs(out.observations[20].candle, changed)
            self.assertNotEqual(out.causal.status, Readiness.SUFFICIENT)

    def test_gaps_duplicates_and_order_do_not_repair(self):
        bars = [candle(i) for i in range(270)]
        for changed, readiness in ((bars[:20] + bars[21:], Readiness.INSUFFICIENT),
                                   (bars[:20] + [bars[19]] + bars[20:], Readiness.INVALID),
                                   (bars[:20] + [bars[21], bars[20]] + bars[22:], Readiness.INVALID)):
            s = series(changed); out = assess_candles(s, BOUNDARY - 1)
            self.assertEqual(out.structure.status, readiness)
            self.assertEqual(out.observations, s.observations)
            self.assertNotEqual(out.causal.status, Readiness.SUFFICIENT)

    def test_future_anomaly_does_not_change_causal_channel(self):
        bars = [candle(i) for i in range(270)]
        bars[250] = replace(bars[250], close=float("nan"))
        out = assess_candles(series(bars), BOUNDARY - 1)
        self.assertEqual(out.structure.status, Readiness.INVALID)
        self.assertEqual(out.causal, assess_candles(series(), BOUNDARY - 1).causal)

    def test_empty_context_invalid_decision_and_foreign_inputs(self):
        self.assertIn("CANDLE_GAP", assess_candles(series(()), BOUNDARY - 1).structure.reasons)
        self.assertEqual(assess_candles(series(), True).causal.status, Readiness.INVALID)
        self.assertEqual(assess_candles(None, BOUNDARY - 1).structure.status, Readiness.INVALID)

    def test_exact_199_vs_200_bar_warmup_at_same_hour(self):
        # End at the same hour; declare a synthetic prefix starting 80 minutes later.
        for count, expected in ((199, "WARMUP"), (200, "READY")):
            bars = tuple(candle(i) for i in range(216 - count, 216))
            out = assess_candles(series(bars), BOUNDARY - 1)
            self.assertEqual(out.existing_feature_status, expected)
            if count == 199: self.assertEqual(out.causal.reasons, ("INSUFFICIENT_WARMUP",))

    def test_frozen_atr_seed_and_full_contiguous_prefix(self):
        bars = tuple(candle(i, width=5. if i < 14 else .5) for i in range(216))
        expected = 10.
        for _ in range(14, 216): expected = (expected * 13 + 1.) / 14
        full = feature_at(series(bars), BOUNDARY - 1)
        self.assertEqual(full.atr14, expected)
        self.assertNotEqual(full.atr14, feature_at(series(bars[-200:]), BOUNDARY - 1).atr14)
        self.assertEqual(full, feature_at(series(bars), BOUNDARY - 1))

    def test_gap_does_not_reseed_despite_200_later_bars(self):
        bars = tuple(candle(i) for i in range(504) if i != 20)
        out = assess_candles(series(bars), BASE + 42 * HOUR - 1)
        self.assertIn("CANDLE_GAP", out.causal.reasons)
        self.assertEqual(out.existing_feature_status, "DATA_QUALITY")

    def test_atr_receives_only_supplied_completed_prefix(self):
        from demo_futures.indicators import atr
        s = series()
        with patch("demo_futures.research_v2.features.atr", wraps=atr) as spy:
            feature_at(s, BOUNDARY - 1)
            supplied, period = spy.call_args.args
            self.assertEqual(period, 14)
            self.assertEqual(tuple(supplied), tuple(o.candle for o in s.observations[:216]))

    def test_late_receipts_stay_rejected(self):
        s = series(); obs = list(s.observations)
        obs[215] = replace(obs[215], available_at=BOUNDARY + 1)
        out = assess_candles(replace(s, observations=tuple(obs)), BOUNDARY - 1)
        self.assertEqual(out.causal.reasons, ("RECEIPT_LATE",))


if __name__ == "__main__":
    unittest.main()
