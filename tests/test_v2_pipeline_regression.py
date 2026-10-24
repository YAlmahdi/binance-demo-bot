"""Nonconstant invented observations; no label production, simulation or fitting."""
from dataclasses import replace
from fractions import Fraction
from functools import lru_cache
import hashlib
import math
import unittest
from unittest.mock import patch

from demo_futures.backtest import BacktestEngine
from demo_futures.data import Candle
from demo_futures.research_v2 import assembly, eligibility, labels
from demo_futures.research_v2.config import FEATURES, HOUR, STEP, SYMBOLS
from demo_futures.research_v2.features import ObservedCandle, SyntheticSeries, feature_at
from demo_futures.research_v2.preprocessing import estimate_preprocessing
from demo_futures.research_v2.validation import DevelopmentWindow, TrainingReceipt, ids_hash
from test_v2_eligibility import invented_pair


@lru_cache
def fixture():
    sources = []
    for offset, symbol in enumerate(SYMBOLS):
        observations = []
        for i in range(540 * 12):
            close = 100. + offset * 20 + (i % 36) / 8
            candle = Candle(i * STEP, close - .25, close + 1, close - 1,
                            close, 100. + i % 24, (i + 1) * STEP - 1,
                            10000., 10)
            observations.append(ObservedCandle(candle, (i + 1) * STEP))
        sources.append(assembly.Source('invented-' + symbol, 'r1',
                       SyntheticSeries(symbol, tuple(observations), 'varied-v1')))
    rows = tuple(feature_at(s.series, t * HOUR - 1)
                 for t in tuple(range(18, 518)) + tuple(range(531, 537))
                 for s in sources)
    window = DevelopmentWindow(0, 530 * HOUR, 536 * HOUR)
    train_ids = tuple(r.row_id for r in rows[:1000])
    receipt = TrainingReceipt(train_ids, ids_hash(train_ids), window)
    estimate = estimate_preprocessing(rows[:1000], receipt, receipt)
    if estimate.status != 'CONSISTENT':
        raise AssertionError(estimate.reasons)
    evaluation = tuple(r.row_id for r in rows[1000:]
                       if r.decision_time + 1 + 4 * HOUR <= window.evaluation_end)
    return assembly.Declaration(tuple(sources), rows, train_ids, evaluation,
        window, receipt, estimate.contract,
        assembly.Budgets(2000, 20000, 400000, 3000000, 3000000, 20000000, 20000000))


@lru_cache
def assembled():
    return assembly.assemble(fixture())


def associations(d):
    by_id = {r.row_id: r for r in d.rows}
    sources = {s.series.symbol: s for s in d.sources}
    result = []
    for identity in d.train_ids + d.evaluation_ids:
        row = by_id[identity]
        source = sources[row.symbol]
        result.append(eligibility.Association(identity,
            'train' if identity in d.train_ids else 'development_evaluation',
            d.window, invented_pair(row), source.identity, source.series.fixture_id,
            source.revision, 'r1', 'invented-producer', 'p1',
            row.decision_time + 1 + 4 * HOUR, 'invented-horizon', 'invented-funding'))
    return tuple(result)


def check(rows=None, d=None, out=None):
    d = fixture() if d is None else d
    rows = associations(d) if rows is None else rows
    return eligibility.validate_associations(d, assembled() if out is None else out,
        rows, tuple(eligibility.Revision(a.row_id, 'r1') for a in rows),
        eligibility.Budgets(2000, 400000, 3000000, 3000000, 20000000, 40000000))


class NonconstantPipelineTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(BacktestEngine, 'run',
                         side_effect=AssertionError('SIMULATOR_FORBIDDEN')))
        self.enterContext(patch.object(labels, 'paired_outcome',
                         side_effect=AssertionError('LABEL_GENERATION_FORBIDDEN')))

    def test_independent_features_statistics_and_transformed_values(self):
        d = fixture()
        self.assertEqual(len(d.feature_names), 9)
        self.assertEqual(d.feature_names, FEATURES)
        for row in d.rows:
            self.assertEqual(row.row_id, f'{row.symbol}:{row.decision_time}')
            self.assertEqual(row.status, 'READY')
            i = (row.decision_time + 1) // STEP - 1
            close = 100. + SYMBOLS.index(row.symbol) * 20 + (i % 36) / 8
            self.assertEqual(row.values[5], 2 / close)
            self.assertEqual(row.values[6], .25 / close)
        # Rational arithmetic over independently reconstructed binary inputs.
        values = []
        for row in d.rows[:1000]:
            i = (row.decision_time + 1) // STEP - 1
            close = 100. + SYMBOLS.index(row.symbol) * 20 + (i % 36) / 8
            values.append(Fraction(2 / close))
        mean = sum(values) / 1000
        variance = sum((x - mean) ** 2 for x in values) / 1000
        self.assertGreater(variance, 0)
        self.assertEqual(d.transform.lower[5], float(min(values)))
        self.assertEqual(d.transform.upper[5], float(max(values)))
        self.assertEqual(d.transform.mean[5], float(mean))
        self.assertEqual(d.transform.scale[5], math.sqrt(float(variance)))
        out = assembled()
        self.assertEqual(out.status, 'FEATURE_ASSEMBLY_VALID', out.reasons)
        transformed = {identity: vector for identity, _, vector in out.payload.transformed}
        first = d.rows[0]
        vector = transformed[first.row_id]
        self.assertIsNotNone(vector)
        self.assertEqual(vector[5], (float(values[0]) - float(mean)) / math.sqrt(float(variance)))
        self.assertEqual(vector[-1], first.values[-1])

    def test_association_determinism_immutability_and_authority(self):
        d = fixture(); rows = associations(d); before = repr((d, rows))
        a, b = check(rows), check(rows)
        self.assertEqual(a.status, 'SYNTHETIC_ASSOCIATION_CONSISTENT', a.reasons)
        self.assertEqual(a, b)
        self.assertEqual(before, repr((d, rows)))
        self.assertEqual(a.payload.row_ids, d.train_ids + d.evaluation_ids)
        self.assertEqual(a.payload.assembly_sha256, assembled().payload.sha256)
        self.assertEqual(a.payload.sha256, hashlib.sha256(a.payload.canonical).hexdigest())
        self.assertEqual(a.payload.training_authorization, 'NOT AUTHORIZED')
        self.assertEqual(a.payload.financial_validity, 'NOT ESTABLISHED')
        for name in ('external_provenance', 'external_completeness', 'training_readiness'):
            self.assertEqual(getattr(a.payload, name), 'UNVERIFIED')
        with self.assertRaises((AttributeError, TypeError)):
            a.payload.row_ids = ()

    def test_wrong_window_receipt_and_revision_fail_closed(self):
        d = fixture(); rows = associations(d)
        changed_window = replace(d.window, evaluation_end=537 * HOUR)
        wrong_receipt = replace(d.receipt, window=changed_window)
        bad = assembly.assemble(replace(d, receipt=wrong_receipt,
                              transform=replace(d.transform, receipt=wrong_receipt)))
        self.assertEqual(bad.status, 'INVALID'); self.assertIsNone(bad.payload)
        for changed in (replace(rows[0], window=changed_window),
                        replace(rows[0], source_revision='r2'),
                        replace(rows[0], stage='development_evaluation')):
            out = check((changed,) + rows[1:])
            self.assertEqual(out.status, 'INVALID', out.reasons)
            self.assertIsNone(out.payload)

    def test_changed_content_same_identity_is_rejected(self):
        d = fixture(); row = d.rows[0]
        changed = replace(row, values=(row.values[0] + .001,) + row.values[1:])
        out = assembly.assemble(replace(d, rows=(changed,) + d.rows[1:]))
        self.assertEqual(out.status, 'INVALID', out.reasons)
        self.assertIsNone(out.payload)

    def test_missing_outcome_evidence_does_not_filter_scheduled_coverage(self):
        rows = associations(fixture())
        for missing in (replace(rows[0], pair=None), replace(rows[0], funding_evidence=None)):
            out = check((missing,) + rows[1:])
            self.assertEqual(out.status, 'INSUFFICIENT', out.reasons)
            self.assertIsNone(out.payload)
        good = check(rows)
        self.assertEqual(good.payload.coverage, assembled().payload.coverage)
        self.assertEqual(len(good.payload.coverage), len(fixture().rows))
        self.assertGreater(len(good.payload.coverage), len(rows))

    def test_future_observation_change_preserves_training_and_earlier_features(self):
        d = fixture(); source = d.sources[0]; observations = source.series.observations
        # Last observation is strictly after every declared decision.
        last = observations[-1]
        changed = replace(last, candle=replace(last.candle, volume=last.candle.volume + 1))
        series = replace(source.series, observations=observations[:-1] + (changed,))
        self.assertGreater(last.candle.open_time, d.rows[-1].decision_time)
        rows = tuple(feature_at(series if r.symbol == series.symbol else d.sources[1].series,
                                r.decision_time) for r in d.rows)
        self.assertEqual(rows, d.rows)
        estimate = estimate_preprocessing(rows[:1000], d.receipt, d.receipt)
        self.assertEqual(estimate.contract, d.transform)
        altered = assembly.assemble(replace(d, sources=(replace(source, series=series), d.sources[1]), rows=rows))
        self.assertEqual(altered.status, 'FEATURE_ASSEMBLY_VALID', altered.reasons)
        self.assertEqual(altered.payload.transformed, assembled().payload.transformed)
        self.assertEqual(altered.payload.coverage, assembled().payload.coverage)
        self.assertNotEqual(altered.payload.sha256, assembled().payload.sha256)


if __name__ == '__main__':
    unittest.main()
