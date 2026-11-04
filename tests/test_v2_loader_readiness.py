"""Invented loader-readiness boundaries; no historical access or label production."""
from dataclasses import replace
from functools import lru_cache
import unittest
from unittest.mock import patch

from demo_futures.backtest import BacktestEngine
from demo_futures.research_v2 import assembly, eligibility, labels
from demo_futures.research_v2.adapter_access_contract import validate_adapter_access
from demo_futures.research_v2.config import HOUR, HORIZON, STEP
from demo_futures.research_v2.contracts import Readiness
from demo_futures.research_v2.features import feature_at
from demo_futures.research_v2.funding_contracts import CoverageState
from demo_futures.research_v2.loader_boundary import assess_boundary, validate_request
from demo_futures.research_v2.opportunities import Opportunity
from demo_futures.research_v2.preprocessing import estimate_preprocessing
from demo_futures.research_v2.quality_contracts import assess_candles
from demo_futures.research_v2.source_contracts import (
    AvailabilityMode, OriginalAvailability, PROTECTED, TARGET_START,
)
from demo_futures.research_v2.validation import IntervalRow, TrainingReceipt, ids_hash
from test_v2_adapter_access_contract import boundary, declarations
from test_v2_loader_boundary import contexts, evidence, request
from test_v2_pipeline_regression import fixture


class NoProductionTests(unittest.TestCase):
    def setUp(self):
        for target, name in ((BacktestEngine, "run"), (labels, "paired_outcome")):
            blocked = self.enterContext(patch.object(
                target, name, side_effect=AssertionError("SIMULATOR_OR_LABEL_PRODUCTION_FORBIDDEN")))
            self.addCleanup(blocked.assert_not_called)


class MalformedBoundaryTests(NoProductionTests):
    def test_missing_request_field_returns_invalid_diagnostics(self):
        req = request(symbols=("BTCUSDT",))
        object.__delattr__(req, "source_id")
        self.assertEqual(validate_request(req).status, Readiness.INVALID)
        out = assess_boundary(req)
        self.assertEqual(out.validation.reasons, ("INVALID_SCHEMA_OR_TIME",))
        self.assertEqual(out.symbols, ())

    def test_missing_nested_fields_return_invalid_without_payloads(self):
        for category, field in (("source", "source_id"), ("funding", "source_id"),
                                ("series", "fixture_id"), ("candle", "volume")):
            with self.subTest(category=category):
                req = request(symbols=("BTCUSDT",))
                sources, funding, series = contexts(req)
                target = {"source": sources[0], "funding": funding[0],
                          "series": series[0], "candle": series[0].observations[0].candle}[category]
                object.__delattr__(target, field)
                out = assess_boundary(req, sources=sources, funding=funding, series=series)
                self.assertEqual(out.validation.status, Readiness.INVALID)
                self.assertEqual(out.validation.reasons, ("INVALID_EVIDENCE",))
                self.assertEqual(out.symbols, ())


class BoundaryCompositionTests(NoProductionTests):
    def test_ohlcv_types_and_completed_grid_preserve_rejected_raw_inputs(self):
        req = request(symbols=("BTCUSDT",))
        sources, funding, series = contexts(req)
        original = series[0].observations[200]
        bad_fields = (("open", float("nan")), ("high", float("inf")),
                      ("low", -1.), ("close", 0.), ("volume", -1.),
                      ("quote_volume", "invalid"), ("trades", True),
                      ("open", True), ("high", 99.),
                      ("open_time", original.candle.open_time + 1),
                      ("close_time", original.candle.close_time - 1))
        for field, value in bad_fields:
            with self.subTest(field=field, value=value):
                observed = replace(original, candle=replace(original.candle, **{field: value}))
                raw = replace(series[0], observations=series[0].observations[:200] +
                              (observed,) + series[0].observations[201:])
                before = repr(raw)
                quality = assess_candles(raw, req.decision_time)
                self.assertIs(quality.observations, raw.observations)
                self.assertEqual(quality.structure.status, Readiness.INVALID)
                self.assertIn("STRUCTURALLY_INVALID", tuple(f.reason for f in quality.flags))
                out = assess_boundary(req, sources=sources, funding=funding, series=(raw,))
                self.assertEqual(out.validation.status, Readiness.INVALID)
                self.assertIsNone(feature_at(raw, req.decision_time).values)
                self.assertEqual(repr(raw), before)

    def test_prefix_disorder_and_future_gaps_are_separate_causal_channels(self):
        req = request(symbols=("BTCUSDT",))
        sources, funding, series = contexts(req)
        observations = series[0].observations
        cases = ((observations[:200] + observations[201:], False, "CANDLE_GAP"),
                 (observations[:200] + (observations[201], observations[200]) +
                  observations[202:], False, "SOURCE_CONFLICT"),
                 (observations[:200] + (observations[199],) + observations[200:],
                  False, "SOURCE_CONFLICT"),
                 (observations[:240] + observations[241:], True, "CANDLE_GAP"))
        for raw, causal_ready, reason in cases:
            with self.subTest(reason=reason, causal_ready=causal_ready):
                changed = replace(series[0], observations=raw)
                before = repr(changed)
                out = assess_boundary(req, sources=sources, funding=funding, series=(changed,))
                self.assertIn(reason, out.validation.reasons)
                self.assertEqual(out.symbols[0].causal.status == Readiness.SUFFICIENT, causal_ready)
                self.assertEqual(repr(changed), before)
                self.assertEqual(out, assess_boundary(req, sources=sources, funding=funding,
                                                     series=(changed,)))

    def test_strict_receipt_claim_cannot_override_late_candle_availability(self):
        req = request(symbols=("BTCUSDT",), mode=AvailabilityMode.REQUIRE_VERIFIED_ASOF)
        sources, funding, series = contexts(req)
        absent = assess_boundary(req, sources=sources, funding=funding, series=series)
        self.assertIn("ORIGINAL_RECEIPT_UNKNOWN", absent.validation.reasons)
        self.assertEqual(absent.symbols[0].causal.status, Readiness.SUFFICIENT)
        source = replace(sources[0], original_availability=OriginalAvailability.VERIFIED,
                         original_receipt=req.decision_time + 1,
                         availability_evidence=evidence(req, "ORIGINAL_ASOF_RECEIPT"))
        late = replace(series[0].observations[215], available_at=req.decision_time + 2)
        changed = replace(series[0], observations=series[0].observations[:215] +
                          (late,) + series[0].observations[216:])
        for retrieved_at in (source.retrieved_at, source.retrieved_at + HOUR):
            with self.subTest(retrieved_at=retrieved_at):
                out = assess_boundary(req, sources=(replace(source, retrieved_at=retrieved_at),),
                                      funding=funding, series=(changed,))
                self.assertEqual(out.symbols[0].source.status, Readiness.SUFFICIENT)
                self.assertEqual(out.symbols[0].causal.reasons, ("RECEIPT_LATE",))
                self.assertEqual(out.symbols[0].retrieved_at, retrieved_at)
                self.assertEqual(out.symbols[0].original_receipt, req.decision_time + 1)
                self.assertIsNone(feature_at(changed, req.decision_time).values)

    def test_empty_and_unknown_funding_diagnostics_never_become_consumable_evidence(self):
        req = request(symbols=("BTCUSDT",))
        sources, funding, series = contexts(req)
        original = funding[0]
        no_settlement = replace(original, state=CoverageState.KNOWN_NO_SETTLEMENT,
            observations=(), schedule=replace(original.schedule, expected_settlements=(),
                                              identity=evidence(req, "NO_SETTLEMENT")))
        cases = ((replace(original, state=CoverageState.UNKNOWN, observations=(), schedule=None),
                  Readiness.INSUFFICIENT),
                 (replace(no_settlement, schedule=replace(no_settlement.schedule, identity=None)),
                  Readiness.INSUFFICIENT),
                 (no_settlement, Readiness.SUFFICIENT))
        for claim, expected in cases:
            with self.subTest(state=claim.state, status=expected):
                out = assess_boundary(req, sources=sources, funding=(claim,), series=series)
                self.assertEqual(out.validation.status, expected)
                self.assertEqual(out.symbols[0].causal.status, Readiness.SUFFICIENT)
                self.assertEqual(out.historical_evidence, "UNAUTHENTICATED / NOT VERIFIED")
                self.assertFalse(hasattr(out, "events"))
                self.assertFalse(hasattr(out, "allow_missing_funding"))
                rejected = assembly.assemble(out)
                self.assertEqual(rejected.status, "INVALID")
                self.assertIsNone(rejected.payload)

    def test_47_vs_48_future_bars_are_not_certified_by_metadata_consistency(self):
        spec, manifest = declarations()
        for count in (47, 48):
            with self.subTest(future_bars=count):
                end = spec.decision_time + 1 + count * STEP
                scoped = replace(spec, context_end=end, horizon_end=end)
                pinned = replace(manifest, context_end=end, horizon_end=end)
                self.assertEqual(validate_adapter_access(scoped, pinned).status, Readiness.SUFFICIENT)
                req = boundary(scoped)
                sources, funding, series = contexts(req)
                out = assess_boundary(req, sources=sources, funding=funding, series=series)
                self.assertEqual(out.validation.status, Readiness.SUFFICIENT)
                feature = feature_at(series[0], req.decision_time)
                opportunity = Opportunity(feature)
                self.assertEqual(opportunity.interval_end, req.decision_time + 1 + HORIZON)
                self.assertEqual(sum(o.candle.open_time >= opportunity.interval_start
                                     for o in series[0].observations), count)
                if count == 47:
                    self.assertLess(req.end, opportunity.interval_end)
                    with self.assertRaises(ValueError):
                        IntervalRow(feature.symbol, feature.decision_time, req.end)
                else:
                    interval = IntervalRow(feature.symbol, feature.decision_time, req.end)
                    self.assertEqual(interval.label_end, opportunity.interval_end)
                self.assertFalse(hasattr(out, "financial_label_validity"))

    def test_protected_prefix_and_horizon_reject_before_candle_inspection(self):
        class Unreadable:
            def __getattr__(self, name):
                raise AssertionError("Out-of-scope candle inspection")
        for changes, reason in (({"start": TARGET_START - STEP}, "UNAUTHORIZED_DATES"),
                                ({"end": PROTECTED[0][0] + STEP}, "PROTECTED_PERIOD"),
                                ({"end": PROTECTED[1][1]}, "PROTECTED_PERIOD")):
            with self.subTest(changes=changes), patch(
                    "demo_futures.research_v2.loader_boundary.assess_candles") as inspect:
                out = assess_boundary(request(**changes), series=(Unreadable(),))
                self.assertEqual(out.validation.status, Readiness.INVALID)
                self.assertIn(reason, out.validation.reasons)
                self.assertEqual(out.symbols, ())
                inspect.assert_not_called()


@lru_cache(maxsize=1)
def pipeline():
    """Rebase the existing invented nonconstant fixture, never market history."""
    original = fixture()
    shifted_sources = []
    for source in original.sources:
        observations = tuple(replace(o, candle=replace(o.candle,
            open_time=o.candle.open_time + TARGET_START,
            close_time=o.candle.close_time + TARGET_START),
            available_at=o.available_at + TARGET_START) for o in source.series.observations)
        shifted_sources.append(replace(source, series=replace(source.series,
                                                             observations=observations)))
    rows = tuple(replace(r, decision_time=r.decision_time + TARGET_START) for r in original.rows)
    window = replace(original.window, train_start=original.window.train_start + TARGET_START,
        evaluation_start=original.window.evaluation_start + TARGET_START,
        evaluation_end=original.window.evaluation_end + TARGET_START)
    train_ids = tuple(r.row_id for r in rows[:len(original.train_ids)])
    shifted_ids = {old.row_id: new.row_id for old, new in zip(original.rows, rows)}
    evaluation_ids = tuple(shifted_ids[identity] for identity in original.evaluation_ids)
    receipt = TrainingReceipt(train_ids, ids_hash(train_ids), window)
    declaration = replace(original, sources=tuple(shifted_sources), rows=rows,
        train_ids=train_ids, evaluation_ids=evaluation_ids, window=window, receipt=receipt,
        transform=replace(original.transform, receipt=receipt))
    req = request(end=TARGET_START + 540 * HOUR, decision_time=rows[0].decision_time,
                  source_id=shifted_sources[0].series.fixture_id)
    sources, funding, _ = contexts(req)
    return declaration, req, sources, funding, assembly.assemble(declaration)


class PipelineReadinessTests(NoProductionTests):
    def test_rebased_pipeline_preserves_training_statistics_and_lacks_label_authority(self):
        declaration, req, sources, funding, assembled = pipeline()
        out = assess_boundary(req, sources=sources, funding=funding,
                              series=tuple(s.series for s in declaration.sources))
        self.assertEqual(out.validation.status, Readiness.SUFFICIENT)
        self.assertEqual(assembled.status, "FEATURE_ASSEMBLY_VALID", assembled.reasons)
        self.assertEqual(feature_at(declaration.sources[0].series, req.decision_time), declaration.rows[0])
        estimate = estimate_preprocessing(declaration.rows[:1000], declaration.receipt, declaration.receipt)
        self.assertEqual(estimate.contract, declaration.transform)
        self.assertEqual(estimate.contract.mean, fixture().transform.mean)
        self.assertEqual(estimate.contract.scale, fixture().transform.scale)
        self.assertEqual(estimate.contract.receipt.window, declaration.window)
        self.assertEqual(assembled.payload.training_authorization, "NOT AUTHORIZED")
        self.assertEqual(assembled.payload.financial_label_validity, "UNVERIFIED")
        before = assembled.payload.coverage
        missing = eligibility.validate_associations(declaration, assembled, (), (),
            eligibility.Budgets(2000, 400000, 3000000, 3000000, 20000000, 40000000))
        self.assertEqual(missing.status, "INSUFFICIENT", missing.reasons)
        self.assertIsNone(missing.payload)
        self.assertEqual(assembled.payload.coverage, before)

    def test_future_interior_gap_cannot_be_hidden_by_feature_only_assembly_success(self):
        declaration, req, sources, funding, baseline = pipeline()
        source = declaration.sources[0]
        raw = replace(source.series, observations=source.series.observations[:-2] +
                      source.series.observations[-1:])
        self.assertGreater(raw.observations[-2].candle.open_time, declaration.rows[-1].decision_time)
        changed = replace(declaration, sources=(replace(source, series=raw), declaration.sources[1]))
        out = assess_boundary(req, sources=sources, funding=funding,
                              series=tuple(s.series for s in changed.sources))
        self.assertIn("CANDLE_GAP", out.validation.reasons)
        self.assertEqual(out.symbols[0].causal.status, Readiness.SUFFICIENT)
        assembled = assembly.assemble(changed)
        self.assertEqual(assembled.status, "FEATURE_ASSEMBLY_VALID", assembled.reasons)
        self.assertEqual(assembled.payload.transformed, baseline.payload.transformed)
        self.assertEqual(assembled.payload.coverage, baseline.payload.coverage)
        self.assertNotEqual(assembled.payload.sha256, baseline.payload.sha256)
        self.assertEqual(assembled.payload.source_completeness, "UNVERIFIED")

    def test_broken_original_prefix_cannot_reseed_or_supply_preprocessing(self):
        declaration, req, sources, funding, _ = pipeline()
        source = declaration.sources[0]
        raw = replace(source.series, observations=source.series.observations[:20] +
                      source.series.observations[21:])
        before = repr(raw)
        changed = replace(declaration, sources=(replace(source, series=raw), declaration.sources[1]))
        out = assess_boundary(req, sources=sources, funding=funding,
                              series=tuple(s.series for s in changed.sources))
        self.assertIn("CANDLE_GAP", out.symbols[0].causal.reasons)
        first = feature_at(raw, req.decision_time)
        self.assertIsNone(first.values)
        self.assertIsNone(first.atr14)
        estimate = estimate_preprocessing((first,) + declaration.rows[1:1000],
                                           declaration.receipt, declaration.receipt)
        self.assertNotEqual(estimate.status, "CONSISTENT")
        self.assertIsNone(estimate.contract)
        rejected = assembly.assemble(changed)
        self.assertEqual(rejected.status, "INVALID", rejected.reasons)
        self.assertIsNone(rejected.payload)
        self.assertEqual(repr(raw), before)


if __name__ == "__main__":
    unittest.main()
