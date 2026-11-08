"""Synthetic-only checks for the isolated completed-bar assumption diagnostic."""
from dataclasses import replace
import unittest
from unittest.mock import patch

from demo_futures.research_v2.config import HOUR, HORIZON, STEP
from demo_futures.research_v2.contracts import EvidenceIdentity, Readiness
from demo_futures.research_v2.exploratory_approximation import (
    ApproximationApproval, ApproximationDiagnostics, ApproximationObservation,
    assess_approximation, verify_approximation,
)
from demo_futures.research_v2.features import ObservedCandle, SyntheticSeries
from demo_futures.research_v2.funding_contracts import (
    CoverageState, FundingClaim, ScheduleEvidence, assess_funding,
)
from demo_futures.research_v2.historical_scope import VersionObservation, commitment, row_commitment
from demo_futures.research_v2.opportunities import hourly_opportunities
from demo_futures.research_v2.source_contracts import AvailabilityMode, OriginalAvailability, PROTECTED
from demo_futures.research_v2.validation import DevelopmentWindow, RangeDecision, abstention_gate

from test_v2_historical_validators import (
    E, NOW, SNAPSHOT, T, approval, horizon, horizon_fixture, observe, prefix, prefix_fixture, version_at,
)


MODE = AvailabilityMode.EXPLORATORY_CLOSED_BAR_APPROXIMATION


def fixture(count=200, *, snapshot=SNAPSHOT):
    strict, rows = prefix_fixture(count, snapshot=snapshot)
    scope = replace(strict, mode=MODE)
    inputs = tuple(ApproximationObservation(VersionObservation(row.version)) for row in rows)
    return scope, pin(scope, inputs), inputs


def pin(scope, inputs):
    claims = tuple(item.observation.original_availability.value for item in inputs)
    proofs = tuple(None if proof is None else (proof.evidence_id, proof.assertion, proof.basis, proof.available_at)
                   for item in inputs for proof in (item.observation.proof, item.material_correction))
    return ApproximationApproval(approval(scope), tuple(row_commitment(row.observation.version) for row in inputs),
                                 commitment(("v2-synthetic-closed-bar-evidence-v1", claims, proofs)))


def assess(scope, grant, rows):
    return assess_approximation(scope, grant, rows, evaluated_at=NOW, retrieved_at=NOW)


def strict_series(snapshot, rows):
    return SyntheticSeries(snapshot.symbol, tuple(ObservedCandle(row.version.candle, row.proof.available_at)
                                                   for row in rows), snapshot.snapshot_id)


class ExploratoryApproximationTests(unittest.TestCase):
    def assert_refused(self, diagnostic, reason, readiness=Readiness.INVALID):
        self.assertIs(diagnostic.validation.status, readiness)
        self.assertIn(reason, diagnostic.validation.reasons)
        self.assertIsNone(diagnostic.sha256)
        self.assertEqual(diagnostic.availability, ())

    def test_missing_receipts_are_assumed_only_and_strict_refuses(self):
        scope, grant, inputs = fixture()
        with patch("demo_futures.research_v2.features.ObservedCandle.__post_init__") as observed:
            result = assess(scope, grant, inputs)
            observed.assert_not_called()
        self.assertIs(type(result), ApproximationDiagnostics)
        self.assertIs(result.validation.status, Readiness.SUFFICIENT)
        self.assertIs(result.mode, MODE)
        self.assertEqual(result.assumption_basis, "PINNED_COMPLETED_BAR_ASSUMPTION")
        self.assertEqual(result.availability, (OriginalAvailability.UNKNOWN,) * 200)
        self.assertEqual(result.next_open_feasibility, "UNVERIFIED")
        self.assertFalse(hasattr(result, "features"))
        self.assertFalse(hasattr(result, "available_at"))
        self.assertTrue(result.sha256)
        with self.assertRaises(TypeError):
            bool(result)
        strict_scope = replace(scope, mode=AvailabilityMode.REQUIRE_VERIFIED_ASOF)
        strict = prefix(strict_scope, tuple(item.observation for item in inputs))
        self.assertIs(strict.validation.status, Readiness.INSUFFICIENT)
        self.assertIn("ORIGINAL_RECEIPT_UNKNOWN", strict.validation.reasons)
        self.assertIsNone(strict.features)

    def test_valid_receipt_is_distinct_from_assumed_completion(self):
        scope, grant, inputs = fixture()
        valid = observe(inputs[-1].observation.version, "ORIGINAL_ASOF_RECEIPT", T)
        rows = inputs[:-1] + (ApproximationObservation(valid),)
        result = assess(scope, pin(scope, rows), rows)
        self.assertIs(result.validation.status, Readiness.SUFFICIENT)
        self.assertEqual(result.availability[:-1], (OriginalAvailability.UNKNOWN,) * 199)
        self.assertIs(result.availability[-1], OriginalAvailability.VERIFIED)
        self.assertEqual(result.historical_evidence, "UNAUTHENTICATED / NOT VERIFIED")
        unsupported = replace(inputs[-1].observation, original_availability=OriginalAvailability.VERIFIED)
        self.assert_refused(assess(scope, grant, inputs[:-1] + (ApproximationObservation(unsupported),)),
                            "ORIGINAL_AVAILABILITY_UNSUPPORTED")

    def test_known_lateness_cannot_be_hidden_as_unknown(self):
        scope, grant, inputs = fixture()
        version = inputs[-1].observation.version
        late = observe(version, "ORIGINAL_ASOF_RECEIPT", T + 1)
        for claim in OriginalAvailability:
            observation = replace(late, original_availability=claim)
            self.assert_refused(assess(scope, grant, inputs[:-1] + (ApproximationObservation(observation),)),
                                "RECEIPT_LATE", Readiness.INSUFFICIENT)
        early = replace(late, proof=replace(late.proof, available_at=T - 1))
        self.assert_refused(assess(scope, grant, inputs[:-1] + (ApproximationObservation(early),)),
                            "INVALID_SCHEMA_OR_TIME")

    def test_material_post_cutoff_correction_and_conflicting_receipt_refuse(self):
        scope, grant, inputs = fixture()
        final = inputs[-1]
        version = final.observation.version
        notice = observe(version, "MATERIAL_CORRECTION", T + 1).proof
        corrected = replace(final, material_correction=notice)
        self.assert_refused(assess(scope, grant, inputs[:-1] + (corrected,)),
                            "RECEIPT_LATE", Readiness.INSUFFICIENT)
        pinned_late = pin(scope, inputs[:-1] + (corrected,))
        self.assert_refused(assess(scope, pinned_late, inputs), "SCOPED_HASH_INVALID")
        claimed = replace(corrected, observation=observe(version, "ORIGINAL_ASOF_RECEIPT", T))
        self.assert_refused(assess(scope, grant, inputs[:-1] + (claimed,)), "INVALID_EVIDENCE")
        wrong_digest = replace(corrected, material_correction=replace(notice, row_sha256="0" * 64))
        self.assert_refused(assess(scope, grant, inputs[:-1] + (wrong_digest,)), "INVALID_EVIDENCE")
        timely = replace(corrected, material_correction=replace(notice, available_at=T))
        rows = inputs[:-1] + (timely,)
        self.assertIs(assess(scope, pin(scope, rows), rows).validation.status, Readiness.SUFFICIENT)

    def test_mode_and_independent_grant_are_required_before_inspection(self):
        scope, grant, _ = fixture()
        strict = replace(scope, mode=AvailabilityMode.REQUIRE_VERIFIED_ASOF)
        wrong_grant = replace(grant, grant=approval(strict))
        expired = replace(grant, grant=replace(grant.grant, expires_at=NOW))
        revoked = replace(grant, grant=replace(grant.grant, revoked=True))
        with patch("demo_futures.research_v2.exploratory_approximation.grid") as inspect:
            self.assert_refused(assess(strict, grant, object()), "UNAPPROVED_SCOPE")
            self.assert_refused(assess(scope, wrong_grant, object()), "APPROVAL_METADATA_MISMATCH")
            self.assert_refused(assess(scope, expired, object()), "APPROVAL_EXPIRED")
            self.assert_refused(assess(scope, revoked, object()), "APPROVAL_REVOKED")
            self.assert_refused(assess(scope, None, object()), "APPROVAL_MISSING", Readiness.INSUFFICIENT)
            inspect.assert_not_called()

    def test_protected_scope_and_out_of_scope_row_precede_value_inspection(self):
        scope, grant, inputs = fixture()
        edge = PROTECTED[0][0]
        protected = replace(scope, end=edge + HOUR, decision_time=edge + HOUR - 1)
        with patch("demo_futures.research_v2.exploratory_approximation.grid") as inspect:
            self.assert_refused(assess(protected, grant, object()), "PROTECTED_PERIOD")
            inspect.assert_not_called()
        rogue = ApproximationObservation(VersionObservation(version_at(SNAPSHOT, edge)))
        with patch("demo_futures.research_v2.historical_scope._candle_values") as values:
            self.assert_refused(assess(scope, grant, (rogue,)), "PROTECTED_PERIOD")
            values.assert_not_called()
        self.assertIs(assess(scope, grant, inputs).validation.status, Readiness.SUFFICIENT)

    def test_gap_missing_origin_and_changed_origin_do_not_reseed(self):
        scope, grant, inputs = fixture(212)
        for index in (0, 5, 211):
            result = assess(scope, grant, inputs[:index] + inputs[index + 1:])
            self.assert_refused(result, "CANDLE_GAP", Readiness.INSUFFICIENT)
            self.assertEqual(result.missing_opens, (scope.start + index * STEP,))
        shifted = replace(scope, start=scope.start + 12 * STEP)
        self.assert_refused(assess(shifted, grant, inputs[-200:]), "APPROVAL_SCOPE_MISMATCH")
        off_grid = replace(scope, start=scope.start + 1)
        self.assert_refused(assess(off_grid, grant, inputs), "INVALID_SCHEMA_OR_TIME")
        self.assert_refused(assess(*fixture(199)), "INSUFFICIENT_WARMUP", Readiness.INSUFFICIENT)

    def test_disorder_duplicates_schema_and_revision_conflicts(self):
        scope, grant, inputs = fixture()
        head, rest = inputs[0], inputs[2:]
        for rows in ((head, head) + rest, (inputs[1], head) + rest):
            self.assert_refused(assess(scope, grant, rows), "SOURCE_CONFLICT")
        version = head.observation.version
        cases = ((replace(version, snapshot=replace(SNAPSHOT, revision="other")), "REVISION_MISMATCH"),
                 (replace(version, snapshot=replace(SNAPSHOT, source_id="other")), "SOURCE_IDENTITY_MISMATCH"),
                 (replace(version, candle=replace(version.candle, high=float("nan"))), "INVALID_SCHEMA_OR_TIME"),
                 (replace(version, candle=replace(version.candle, close_time=version.candle.close_time + 1)),
                  "INVALID_SCHEMA_OR_TIME"))
        for altered, reason in cases:
            with self.subTest(reason=reason):
                self.assert_refused(assess(scope, grant, (ApproximationObservation(VersionObservation(altered)),)
                                          + inputs[1:]), reason)

    def test_frozen_flags_and_decision_quality(self):
        scope, _, inputs = fixture()
        version = inputs[-1].observation.version
        candle = version.candle
        for bad in (replace(candle, volume=0.0), replace(candle, high=candle.open, low=candle.open, close=candle.open)):
            rows = inputs[:-1] + (ApproximationObservation(VersionObservation(replace(version, candle=bad))),)
            result = assess(scope, pin(scope, rows), rows)
            self.assert_refused(result, "CAUSAL_INPUT_INVALID", Readiness.INSUFFICIENT)
            self.assertTrue(result.flags)
        prior = tuple(ApproximationObservation(VersionObservation(replace(item.observation.version, candle=replace(
            item.observation.version.candle, volume=0.0)))) for item in inputs[-21:-1])
        rows = inputs[:-21] + prior + inputs[-1:]
        self.assert_refused(assess(scope, pin(scope, rows), rows), "CAUSAL_INPUT_INVALID", Readiness.INSUFFICIENT)

    def test_replay_binds_snapshot_revision_grant_content_and_receipt(self):
        scope, grant, inputs = fixture()
        result = assess(scope, grant, inputs)

        def replay(s=scope, g=grant, rows=inputs, retrieved_at=NOW):
            return verify_approximation(result.sha256, s, g, rows, evaluated_at=NOW, retrieved_at=retrieved_at)

        self.assertEqual(replay(), result)
        self.assertEqual(assess(scope, grant, inputs), result)
        for snapshot in (replace(SNAPSHOT, revision="other"), replace(SNAPSHOT, snapshot_id="other"),
                         replace(SNAPSHOT, symbol="ETHUSDT")):
            self.assert_refused(replay(*fixture(snapshot=snapshot)), "SCOPED_HASH_INVALID")
        new_grant = replace(grant, grant=replace(grant.grant, approval_id="other-grant"))
        self.assert_refused(replay(g=new_grant), "SCOPED_HASH_INVALID")
        self.assert_refused(replay(retrieved_at=NOW - 1), "SCOPED_HASH_INVALID")
        final = inputs[-1].observation.version
        mutated = replace(final, candle=replace(final.candle, volume=99.0))
        rows = inputs[:-1] + (ApproximationObservation(VersionObservation(mutated)),)
        self.assert_refused(assess(scope, grant, rows), "SCOPED_HASH_INVALID")
        self.assert_refused(replay(g=pin(scope, rows), rows=rows), "SCOPED_HASH_INVALID")
        witnessed = inputs[:-1] + (ApproximationObservation(observe(final, "ORIGINAL_ASOF_RECEIPT")),)
        self.assert_refused(replay(rows=witnessed), "SCOPED_HASH_INVALID")
        self.assert_refused(replay(g=pin(scope, witnessed), rows=witnessed), "SCOPED_HASH_INVALID")

    def test_future_slice_has_no_effect_on_causal_or_denominator_channels(self):
        scope, grant, inputs = fixture()
        diagnostic = assess(scope, grant, inputs)
        _, btc = prefix_fixture()
        eth_snapshot = replace(SNAPSHOT, symbol="ETHUSDT")
        _, eth = prefix_fixture(snapshot=eth_snapshot)
        future_scope, anchor, future = horizon_fixture()
        amended = (observe(version_at(SNAPSHOT, T, volume=99.0), "AUDIT_OBSERVATION"),) + future[1:]
        window = DevelopmentWindow(T - 3 * HOUR, T - HOUR, T)
        initial = None
        for horizon_rows in (future, amended, future[:-1], ()):
            future_receipts = tuple(observe(row.version, "ORIGINAL_ASOF_RECEIPT", NOW) for row in horizon_rows)
            markets = {"BTCUSDT": strict_series(SNAPSHOT, btc + future_receipts),
                       "ETHUSDT": strict_series(eth_snapshot, eth)}
            opportunities = hourly_opportunities(markets, T, T + HOUR, available_at=T)
            decisions = tuple(RangeDecision(o.symbol, o.decision_time, o.features.status == "READY", False)
                              for o in opportunities)
            coverage = abstention_gate(decisions, window, ())["coverage"]
            self.assertEqual(coverage["overall"]["feature_eligible"], 2)
            self.assertTrue(all(o.interval_end == T + HORIZON for o in opportunities))
            if initial is None:
                initial = opportunities, coverage
            self.assertEqual((opportunities, coverage), initial)
            self.assertEqual(assess(scope, grant, inputs), diagnostic)
            self.assertEqual(horizon(future_scope, anchor, horizon_rows).sha256 is not None, len(horizon_rows) == 48)
        self.assert_refused(assess(scope, grant, inputs + (ApproximationObservation(future[0]),)),
                            "UNAUTHORIZED_DATES")

    def test_funding_and_no_settlement_diagnostic_remain_separate(self):
        result = assess(*fixture())
        claim = FundingClaim(SNAPSHOT.symbol, T, E, SNAPSHOT.source_id, SNAPSHOT.revision, CoverageState.UNKNOWN)
        self.assertIs(assess_funding(claim).state, CoverageState.UNKNOWN)
        evidence = EvidenceIdentity("invented-empty", SNAPSHOT.source_id, SNAPSHOT.revision, "NO_SETTLEMENT")
        schedule = ScheduleEvidence(SNAPSHOT.symbol, T, E, evidence, (), True)
        empty = assess_funding(replace(claim, state=CoverageState.KNOWN_NO_SETTLEMENT, schedule=schedule))
        self.assertIs(empty.state, CoverageState.KNOWN_NO_SETTLEMENT)
        self.assertFalse(hasattr(empty, "events"))
        self.assertFalse(hasattr(result, "funding"))
        self.assertFalse(hasattr(result, "labels"))
        self.assertEqual(assess(*fixture()), result)
