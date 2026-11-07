"""Published A/H/P/S/F acceptance matrix on invented, in-memory records."""
from dataclasses import replace
from decimal import Decimal
import unittest
from unittest.mock import patch

from demo_futures.data import Candle
from demo_futures.research_v2.config import HOUR, HORIZON, STEP
from demo_futures.research_v2.contracts import EvidenceIdentity, Readiness
from demo_futures.research_v2.features import ObservedCandle, SyntheticSeries, feature_at
from demo_futures.research_v2.funding_contracts import (
    CoverageState, FundingClaim, ScheduleEvidence, SettlementObservation, assess_funding,
)
from demo_futures.research_v2.historical_scope import (
    CandleScope, CandleVersion, SliceApproval, SnapshotIdentity, VersionEvidence, VersionObservation,
    preflight, row_commitment,
)
from demo_futures.research_v2.horizon_coverage import assess_horizon, verify_horizon
from demo_futures.research_v2.opportunities import hourly_opportunities
from demo_futures.research_v2.pinned_prefix import assess_pinned_prefix
from demo_futures.research_v2.source_contracts import AvailabilityMode, OriginalAvailability, PROTECTED, TARGET_START
from demo_futures.research_v2.validation import (
    DevelopmentWindow, IntervalRow, RangeDecision, abstention_gate, partition_reason,
)


T = TARGET_START + 48 * HOUR
E = T + HORIZON
NOW = E + HOUR
SNAPSHOT = SnapshotIdentity("invented-source", "invented-snapshot", "revision-1", "BTCUSDT", "source-proof")


def approval(scope):
    return SliceApproval("invented-approval", scope, NOW - HOUR, NOW + HOUR, 4096)


def version_at(snapshot, opened, **changes):
    price = 100.0 + (opened // STEP % 7)
    candle = Candle(opened, price, price + 2, price - 1, price + 1, 10.0, opened + STEP - 1)
    return CandleVersion(snapshot, f"row-{opened}", "version-1", replace(candle, **changes))


def observe(version, assertion, when=None):
    original = (OriginalAvailability.VERIFIED if assertion == "ORIGINAL_ASOF_RECEIPT"
                else OriginalAvailability.UNKNOWN)
    evidence = VersionEvidence(f"proof-{version.row_id}", assertion, row_commitment(version),
                               version.candle.close_time + 1 if when is None else when)
    return VersionObservation(version, evidence, original)


def prefix_fixture(count=200, *, snapshot=SNAPSHOT, boundary=T, origin=None):
    start = boundary - count * STEP if origin is None else origin
    scope = CandleScope("prefix-scope", snapshot, start, boundary, boundary - 1)
    versions = (version_at(snapshot, opened, **({"high": 500.0} if opened == start else {}))
                for opened in range(start, boundary, STEP))
    return scope, tuple(observe(v, "ORIGINAL_ASOF_RECEIPT") for v in versions)


def horizon_fixture(*, snapshot=SNAPSHOT, boundary=T):
    anchor = version_at(snapshot, boundary - STEP)
    scope = CandleScope("horizon-scope", snapshot, boundary, boundary + HORIZON, boundary - 1,
                        anchor_sha256=row_commitment(anchor))
    observations = tuple(observe(version_at(snapshot, t), "AUDIT_OBSERVATION")
                         for t in range(boundary, boundary + HORIZON, STEP))
    return scope, anchor, observations


def prefix(scope, observations):
    return assess_pinned_prefix(scope, approval(scope), observations, evaluated_at=NOW, retrieved_at=NOW)


def horizon(scope, anchor, observations, cutoff=E):
    return assess_horizon(scope, approval(scope), anchor, observations, evaluated_at=NOW, audit_cutoff=cutoff)


def series(snapshot, observations):
    rows = tuple(ObservedCandle(o.version.candle, o.version.candle.close_time + 1) for o in observations)
    return SyntheticSeries(snapshot.symbol, rows, snapshot.snapshot_id)


class HistoricalValidatorTests(unittest.TestCase):
    def assert_result(self, diagnostic, readiness, *reasons):
        self.assertIs(diagnostic.validation.status, readiness)
        self.assertEqual(diagnostic.validation.reasons, reasons)
        if readiness is not Readiness.SUFFICIENT and hasattr(diagnostic, "sha256"):
            self.assertIsNone(diagnostic.sha256)
            self.assertIsNone(diagnostic.mature_at)

    def test_A1_exact_version_receipts_and_inclusive_cutoff(self):
        scope, rows = prefix_fixture()
        self.assertEqual(rows[-1].proof.available_at, T)
        result = prefix(scope, rows)
        self.assert_result(result, Readiness.SUFFICIENT)
        self.assertEqual(result.next_open_feasibility, "UNVERIFIED")
        self.assertEqual(result.features, feature_at(series(SNAPSHOT, rows), T - 1))
        with self.assertRaises(TypeError):
            bool(result)

    def test_A2_retrieval_or_ambiguous_receipt_cannot_supply_original_availability(self):
        scope, rows = prefix_fixture()
        for proof in (None, rows[-1].proof):
            with self.subTest(proof=proof is not None):
                uncertain = replace(rows[-1], proof=proof, original_availability=OriginalAvailability.UNKNOWN)
                out = prefix(scope, rows[:-1] + (uncertain,))
                self.assert_result(out, Readiness.INSUFFICIENT, "ORIGINAL_RECEIPT_UNKNOWN")
                self.assertIsNone(out.features)
        approximate = replace(scope, mode=AvailabilityMode.EXPLORATORY_CLOSED_BAR_APPROXIMATION)
        self.assert_result(prefix(approximate, rows), Readiness.INVALID, "UNAPPROVED_SCOPE")

    def test_A3_late_impossible_unproven_and_reused_receipts(self):
        scope, rows = prefix_fixture()
        final = rows[-1]
        cases = (
            (replace(final, proof=replace(final.proof, available_at=T + 1)),
             Readiness.INSUFFICIENT, ("RECEIPT_LATE",)),
            (replace(final, proof=replace(final.proof, available_at=T - 1)),
             Readiness.INVALID, ("INVALID_SCHEMA_OR_TIME",)),
            (replace(final, proof=None), Readiness.INVALID, ("ORIGINAL_AVAILABILITY_UNSUPPORTED",)),
            (replace(final, version=replace(final.version, version_id="corrected")),
             Readiness.INVALID, ("INVALID_EVIDENCE", "ORIGINAL_AVAILABILITY_UNSUPPORTED")),
            (replace(final, proof=replace(final.proof, available_at=NOW + 1)),
             Readiness.INVALID, ("INVALID_SCHEMA_OR_TIME",)),
        )
        for observation, status, reasons in cases:
            with self.subTest(reasons=reasons):
                out = prefix(scope, rows[:-1] + (observation,))
                self.assert_result(out, status, *reasons)
                self.assertIsNone(out.features)

    def test_H1_exact_grid_and_audit_maturity_at_equality(self):
        scope, anchor, rows = horizon_fixture()
        result = horizon(scope, anchor, rows)
        self.assert_result(result, Readiness.SUFFICIENT)
        self.assertEqual(result.mature_at, E)
        self.assertEqual(rows[-1].version.candle.close_time, E - 1)
        self.assertEqual(result, horizon(scope, anchor, rows))
        self.assert_result(horizon(scope, anchor, rows, E - 1), Readiness.INSUFFICIENT, "HORIZON_NOT_MATURE")
        late = rows[:-1] + (replace(rows[-1], proof=replace(rows[-1].proof, available_at=E + 1)),)
        self.assert_result(horizon(scope, anchor, late), Readiness.INSUFFICIENT, "HORIZON_NOT_MATURE")
        delayed = horizon(scope, anchor, late, E + 1)
        self.assert_result(delayed, Readiness.SUFFICIENT)
        self.assertEqual(delayed.mature_at, E + 1)
        self.assertNotEqual(delayed.sha256, result.sha256)
        missing = rows[:-1] + (replace(rows[-1], proof=None),)
        self.assert_result(horizon(scope, anchor, missing), Readiness.INSUFFICIENT,
                           "HORIZON_OBSERVATION_UNPROVEN")

    def test_H2_47_bars_interior_gap_and_extra_at_exclusive_end(self):
        scope, anchor, rows = horizon_fixture()
        for raw, missing in ((rows[:-1], E - STEP), (rows[:13] + rows[14:], T + 13 * STEP)):
            with self.subTest(missing=missing):
                out = horizon(scope, anchor, raw)
                self.assert_result(out, Readiness.INSUFFICIENT, "CANDLE_GAP")
                self.assertEqual(out.missing_opens, (missing,))
        substituted = rows[:-1] + (observe(version_at(SNAPSHOT, E), "AUDIT_OBSERVATION"),)
        self.assert_result(horizon(scope, anchor, substituted), Readiness.INVALID, "UNAUTHORIZED_DATES")
        clipped = replace(scope, end=E - STEP)
        self.assert_result(horizon(clipped, anchor, rows[:-1]), Readiness.INVALID, "UNAUTHORIZED_DATES")

    def test_H3_duplicate_disordered_wrong_grid_and_malformed_numbers(self):
        scope, anchor, rows = horizon_fixture()
        for pair in ((rows[13], rows[13]), (rows[14], rows[13])):
            self.assert_result(horizon(scope, anchor, rows[:13] + pair + rows[15:]),
                               Readiness.INVALID, "SOURCE_CONFLICT")
        for changes in ({"close_time": T + 14 * STEP}, {"high": float("nan")}, {"volume": True}):
            with self.subTest(changes=changes):
                v = rows[13].version
                broken = replace(rows[13], version=replace(v, candle=replace(v.candle, **changes)))
                self.assert_result(horizon(scope, anchor, rows[:13] + (broken,) + rows[14:]),
                                   Readiness.INVALID, "INVALID_SCHEMA_OR_TIME")

    def test_H4_commitment_replay_and_source_or_content_substitution(self):
        scope, anchor, rows = horizon_fixture()
        prior = horizon(scope, anchor, rows)

        def verify(s=scope, a=anchor, r=rows, cutoff=E, grant=None):
            return verify_horizon(prior.sha256, s, approval(s) if grant is None else grant, a, r,
                                  evaluated_at=NOW, audit_cutoff=cutoff)

        self.assertEqual(verify(), prior)
        for snapshot in (replace(SNAPSHOT, symbol="ETHUSDT"), replace(SNAPSHOT, snapshot_id="other"),
                         replace(SNAPSHOT, revision="revision-2"), replace(SNAPSHOT, source_ref="other-proof")):
            changed = horizon_fixture(snapshot=snapshot)
            self.assert_result(horizon(*changed), Readiness.SUFFICIENT)
            self.assert_result(verify(*changed), Readiness.INVALID, "SCOPED_HASH_INVALID")
        self.assert_result(verify(*horizon_fixture(boundary=T + HOUR), cutoff=NOW),
                           Readiness.INVALID, "SCOPED_HASH_INVALID")
        wrong = replace(scope, snapshot=replace(SNAPSHOT, interval="15m"))
        self.assert_result(verify(s=wrong), Readiness.INVALID, "WRONG_INTERVAL")
        self.assert_result(verify(cutoff=E + 1), Readiness.INVALID, "SCOPED_HASH_INVALID")
        self.assert_result(verify(grant=replace(approval(scope), approval_id="other-grant")),
                           Readiness.INVALID, "SCOPED_HASH_INVALID")
        v = rows[1].version
        mutated = replace(v, candle=replace(v.candle, volume=v.candle.volume + 1))
        self.assert_result(verify(r=(rows[0], replace(rows[1], version=mutated)) + rows[2:]),
                           Readiness.INVALID, "INVALID_EVIDENCE")
        fresh = (rows[0], observe(mutated, "AUDIT_OBSERVATION")) + rows[2:]
        self.assert_result(verify(r=fresh), Readiness.INVALID, "SCOPED_HASH_INVALID")
        self.assert_result(verify(a=replace(anchor, version_id="wrong-anchor")),
                           Readiness.INVALID, "SCOPED_HASH_INVALID")

    def test_H5_future_variation_cannot_change_causal_opportunities_or_denominator(self):
        btc_scope, btc_prefix = prefix_fixture()
        eth = replace(SNAPSHOT, symbol="ETHUSDT")
        _, eth_prefix = prefix_fixture(snapshot=eth)
        scope, anchor, future = horizon_fixture()
        changed = (observe(version_at(SNAPSHOT, T, volume=99.0), "AUDIT_OBSERVATION"),) + future[1:]
        window = DevelopmentWindow(T - 3 * HOUR, T - HOUR, T)
        expected_causal = prefix(btc_scope, btc_prefix)
        expected_coverage = None
        for supplied in (future, changed, future[:-1], ()):
            with self.subTest(rows=len(supplied)):
                markets = {"BTCUSDT": series(SNAPSHOT, btc_prefix + supplied), "ETHUSDT": series(eth, eth_prefix)}
                opportunities = hourly_opportunities(markets, T, T + HOUR, available_at=T)
                self.assertEqual(opportunities[0].features, expected_causal.features)
                self.assertEqual([o.symbol for o in opportunities], ["BTCUSDT", "ETHUSDT"])
                inventory = tuple(RangeDecision(o.symbol, o.decision_time, o.features.status == "READY", False)
                                  for o in opportunities)
                coverage = abstention_gate(inventory, window, ())['coverage']
                self.assertEqual(coverage['overall']['feature_eligible'], 2)
                if expected_coverage is None:
                    expected_coverage = coverage
                self.assertEqual(coverage, expected_coverage)
                future_result = horizon(scope, anchor, supplied)
                self.assertEqual(future_result.sha256 is not None, len(supplied) == 48)

    def test_H6_partition_edges_are_independent_of_audit_cutoff(self):
        scope, anchor, rows = horizon_fixture()
        out = horizon(scope, anchor, rows, E + 1)
        self.assert_result(out, Readiness.SUFFICIENT)
        interval = IntervalRow(SNAPSHOT.symbol, T - 1, E)
        evaluation = DevelopmentWindow(T - 3 * HOUR, T - HOUR, E)
        self.assertEqual(partition_reason(interval, evaluation, "development_evaluation"), "ACCEPT")
        self.assertEqual(partition_reason(interval, replace(evaluation, evaluation_end=E - HOUR),
                                          "development_evaluation"), "INCOMPLETE_EVALUATION_HORIZON")
        train = DevelopmentWindow(T - HOUR, E + HORIZON, E + HORIZON + HOUR)
        self.assertEqual(partition_reason(interval, train, "train"), "ACCEPT")
        self.assertEqual(partition_reason(interval, replace(train, evaluation_start=E + HORIZON - HOUR),
                                          "train"), "FOUR_HOUR_BUFFER")
        self.assertEqual(out, horizon(scope, anchor, rows, E + 1))

    def test_P1_199_200_full_prefix_and_frozen_atr_seed(self):
        short = prefix(*prefix_fixture(199))
        self.assert_result(short, Readiness.INSUFFICIENT, "INSUFFICIENT_WARMUP")
        self.assertEqual(short.features.status, "WARMUP")
        scope, rows = prefix_fixture()
        later_scope, _ = prefix_fixture(boundary=T + HOUR, origin=scope.start)
        extension = tuple(observe(version_at(SNAPSHOT, t), "ORIGINAL_ASOF_RECEIPT")
                          for t in range(T, T + HOUR, STEP))
        for request, values in ((scope, rows), (later_scope, rows + extension)):
            candles = tuple(o.version.candle for o in values)
            ranges = [candles[0].high - candles[0].low]
            ranges.extend(max(current.high - current.low, abs(current.high - previous.close),
                              abs(current.low - previous.close)) for previous, current in zip(candles, candles[1:]))
            atr = sum(ranges[:14]) / 14
            for current in ranges[14:]:
                atr = (atr * 13 + current) / 14
            result = prefix(request, values)
            self.assert_result(result, Readiness.SUFFICIENT)
            self.assertEqual(result.features.atr14, atr)
        truncated = (rows + extension)[-200:]
        self.assertNotEqual(result.features.atr14, feature_at(series(SNAPSHOT, truncated), T + HOUR - 1).atr14)
        self.assert_result(prefix(later_scope, truncated), Readiness.INSUFFICIENT, "CANDLE_GAP")
        shifted = replace(later_scope, start=truncated[0].version.candle.open_time)
        out = assess_pinned_prefix(shifted, approval(later_scope), truncated, evaluated_at=NOW, retrieved_at=NOW)
        self.assert_result(out, Readiness.INVALID, "APPROVAL_SCOPE_MISMATCH")

    def test_P2_pinned_gaps_disorder_and_revision_cannot_reseed(self):
        scope, rows = prefix_fixture()
        late_scope, _ = prefix_fixture(boundary=T + 17 * HOUR, origin=scope.start)
        self.assert_result(prefix(scope, rows), Readiness.SUFFICIENT)
        for missing in (0, 13, len(rows) - 1):
            out = prefix(scope, rows[:missing] + rows[missing + 1:])
            self.assert_result(out, Readiness.INSUFFICIENT, "CANDLE_GAP")
            self.assertEqual(out.missing_opens, (rows[missing].version.candle.open_time,))
        for pair in ((rows[13], rows[13]), (rows[14], rows[13])):
            self.assert_result(prefix(scope, rows[:13] + pair + rows[15:]), Readiness.INVALID, "SOURCE_CONFLICT")
        extension = tuple(observe(version_at(SNAPSHOT, t), "ORIGINAL_ASOF_RECEIPT")
                          for t in range(T + STEP, late_scope.end, STEP))
        grant = replace(approval(late_scope), expires_at=late_scope.end + HOUR)
        out = assess_pinned_prefix(late_scope, grant, rows + extension,
                                   evaluated_at=late_scope.end, retrieved_at=late_scope.end)
        self.assert_result(out, Readiness.INSUFFICIENT, "CANDLE_GAP")
        self.assertEqual(out.missing_opens, (T,))
        revised = replace(SNAPSHOT, revision="revision-2")
        new_scope, corrected = prefix_fixture(snapshot=revised)
        self.assert_result(prefix(scope, rows[:-1] + corrected[-1:]), Readiness.INVALID, "REVISION_MISMATCH")
        inherited = replace(corrected[-1], proof=rows[-1].proof)
        self.assert_result(prefix(new_scope, corrected[:-1] + (inherited,)), Readiness.INVALID,
                           "INVALID_EVIDENCE", "ORIGINAL_AVAILABILITY_UNSUPPORTED")
        self.assert_result(prefix(new_scope, corrected), Readiness.SUFFICIENT)

    def test_P3_documentary_flags_preserve_raw_values_and_existing_abstention(self):
        scope, rows = prefix_fixture()
        v = rows[3].version
        c = v.candle
        flat = dict(high=c.open, low=c.open, close=c.open)
        altered = observe(replace(v, candle=replace(c, volume=0.0, **flat)), "ORIGINAL_ASOF_RECEIPT")
        raw = rows[:3] + (altered,) + rows[4:]
        result = prefix(scope, raw)
        self.assert_result(result, Readiness.SUFFICIENT)
        self.assertEqual({f.reason for f in result.flags}, {"ZERO_VOLUME_REVIEW", "FLAT_BAR_REVIEW",
                                                            "RANGE_GT_5_PERCENT_REVIEW_ONLY"})
        self.assertEqual(result.features, feature_at(series(SNAPSHOT, raw), T - 1))
        self.assertEqual(raw[3].version.candle.volume, 0.0)
        final = rows[-1].version
        for change in ({"volume": 0.0}, {"high": final.candle.open, "low": final.candle.open,
                                        "close": final.candle.open}):
            last = observe(replace(final, candle=replace(final.candle, **change)), "ORIGINAL_ASOF_RECEIPT")
            abstained = prefix(scope, rows[:-1] + (last,))
            self.assert_result(abstained, Readiness.INSUFFICIENT, "CAUSAL_INPUT_INVALID")
            self.assertEqual(abstained.features.reason, "ZERO_VOLUME_OR_RANGE_DECISION")
        for high in (-1.0, float("inf")):
            bad = replace(rows[-1], version=replace(final, candle=replace(final.candle, high=high)))
            self.assert_result(prefix(scope, rows[:-1] + (bad,)), Readiness.INVALID, "INVALID_SCHEMA_OR_TIME")

    def test_S1_protected_and_inactive_authority_stop_before_rows_or_hashes(self):
        scope, rows = prefix_fixture()
        future, anchor, _ = horizon_fixture()
        edge = PROTECTED[0][0]
        protected_prefix = replace(scope, end=edge + HOUR, decision_time=edge + HOUR - 1)
        protected_future = replace(future, start=edge - HOUR, end=edge + 3 * HOUR, decision_time=edge - HOUR - 1)
        cases = ((None, "APPROVAL_MISSING"), (replace(approval(scope), expires_at=NOW), "APPROVAL_EXPIRED"),
                 (replace(approval(scope), revoked=True), "APPROVAL_REVOKED"))
        with patch("demo_futures.research_v2.pinned_prefix.grid") as prefix_grid, \
             patch("demo_futures.research_v2.horizon_coverage.grid") as future_grid, \
             patch("demo_futures.research_v2.horizon_coverage.row_commitment") as hash_row:
            for grant, reason in cases:
                out = assess_pinned_prefix(scope, grant, object(), evaluated_at=NOW, retrieved_at=NOW)
                self.assertIn(reason, out.validation.reasons)
            self.assertIn("PROTECTED_PERIOD", prefix(protected_prefix, object()).validation.reasons)
            self.assertIn("PROTECTED_PERIOD", horizon(protected_future, object(), object()).validation.reasons)
            funding_dependency = replace(future, end=PROTECTED[1][1])
            self.assertIn("PROTECTED_PERIOD", preflight(funding_dependency, approval(funding_dependency),
                                                        evaluated_at=NOW).reasons)
            prefix_grid.assert_not_called()
            future_grid.assert_not_called()
            hash_row.assert_not_called()
        rogue = VersionObservation(version_at(SNAPSHOT, edge))
        with patch("demo_futures.research_v2.historical_scope._candle_values") as inspect_values:
            out = horizon(future, anchor, (rogue,))
            inspect_values.assert_called_once_with(anchor.candle)
            self.assert_result(out, Readiness.INVALID, "PROTECTED_PERIOD")
        self.assert_result(prefix(scope, rows), Readiness.SUFFICIENT)

    def test_S2_projection_resource_binding_and_partial_input_fail_closed(self):
        scope, anchor, rows = horizon_fixture()
        wrong = replace(scope, projection=("open_time",))
        mixed = replace(scope, snapshot={"mutable": "snapshot"})
        cases = ((wrong, approval(wrong), "QUERY_PROJECTION_MISMATCH"),
                 (mixed, approval(mixed), "INVALID_SCHEMA_OR_TIME"),
                 (scope, replace(approval(scope), max_rows=47), "QUERY_RESOURCE_LIMIT"))
        with patch("demo_futures.research_v2.horizon_coverage.grid") as inspect:
            for s, grant, reason in cases:
                out = assess_horizon(s, grant, object(), object(), evaluated_at=NOW, audit_cutoff=E)
                self.assert_result(out, Readiness.INVALID, reason)
            inspect.assert_not_called()
        pinned = replace(scope, anchor_sha256="0" * 64)
        self.assert_result(horizon(pinned, anchor, rows), Readiness.INVALID, "SCOPED_HASH_INVALID")
        def untrusted_iterable():
            self.fail("The validator must not iterate a caller-controlled reader")
            yield rows[0]
        self.assert_result(horizon(scope, anchor, untrusted_iterable()), Readiness.INVALID, "INVALID_SCHEMA_OR_TIME")
        self.assert_result(horizon(scope, anchor, rows[:1]), Readiness.INSUFFICIENT, "CANDLE_GAP")
        self.assert_result(horizon(scope, anchor, (object(),) * 4097), Readiness.INVALID, "QUERY_RESOURCE_LIMIT")

    def test_F1_candle_coverage_cannot_prove_settlement_or_activate_bridge(self):
        coverage = horizon(*horizon_fixture())
        self.assert_result(coverage, Readiness.SUFFICIENT)
        causal = prefix(*prefix_fixture())
        claim = FundingClaim(SNAPSHOT.symbol, T, E, SNAPSHOT.source_id, SNAPSHOT.revision, CoverageState.UNKNOWN)
        schedule = ScheduleEvidence(SNAPSHOT.symbol, T, E, None, (T + STEP,), False)
        event = SettlementObservation(T + STEP, Decimal("0.0001"), None, None, None)
        for unsupported in (claim, replace(claim, schedule=schedule),
                            replace(claim, state=CoverageState.KNOWN_EVENTS, schedule=schedule, observations=(event,))):
            self.assertIs(assess_funding(unsupported).state, CoverageState.UNKNOWN)
        proof = EvidenceIdentity("invented-empty", SNAPSHOT.source_id, SNAPSHOT.revision, "NO_SETTLEMENT")
        empty = replace(claim, state=CoverageState.KNOWN_NO_SETTLEMENT,
                        schedule=replace(schedule, identity=proof, expected_settlements=(), complete=True))
        inert = assess_funding(empty)
        self.assertIs(inert.state, CoverageState.KNOWN_NO_SETTLEMENT)
        self.assertIs(inert.validation.status, Readiness.SUFFICIENT)
        self.assertFalse(hasattr(coverage, "funding"))
        self.assertFalse(hasattr(inert, "events"))
        self.assertEqual(coverage, horizon(*horizon_fixture()))
        self.assertEqual(causal, prefix(*prefix_fixture()))

    def test_invalid_dominates_missing_in_fixed_reason_order(self):
        scope, anchor, rows = horizon_fixture()
        no_proof = replace(rows[0], proof=None)
        impossible = replace(rows[-1], proof=replace(rows[-1].proof, available_at=E - 1))
        out = horizon(scope, anchor, (no_proof,) + rows[1:-2] + (impossible,))
        self.assert_result(out, Readiness.INVALID, "INVALID_SCHEMA_OR_TIME", "CANDLE_GAP",
                           "HORIZON_OBSERVATION_UNPROVEN")

    def test_missing_required_fields_cannot_escape_as_exceptions(self):
        scope, anchor, rows = horizon_fixture()
        proof = replace(rows[0].proof)
        object.__delattr__(proof, "row_sha256")
        self.assert_result(horizon(scope, anchor, (replace(rows[0], proof=proof),) + rows[1:]),
                           Readiness.INVALID, "INVALID_EVIDENCE")
        broken = replace(scope)
        object.__delattr__(broken, "snapshot")
        self.assert_result(horizon(broken, anchor, rows), Readiness.INVALID, "INVALID_SCHEMA_OR_TIME")
