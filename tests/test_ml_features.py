import math
from dataclasses import replace
import unittest
from demo_futures.indicators import build_features
from demo_futures.strategy import BaselineStrategy
from demo_futures.ml_research.config import FEATURE_NAMES, DEV_END, STEP
from demo_futures.ml_research.features import FeatureRow, causal_indicators, feature_at
from demo_futures.ml_research.opportunities import enumerate_opportunities
from test_ml_fixtures import history


class MLFeatureTests(unittest.TestCase):
    def setUp(self):
        self.bars = history()
        self.indicators = causal_indicators(self.bars)

    def test_exact_16_ordered_predictors_no_target_or_future_metadata(self):
        row, reason = feature_at("BTCUSDT",self.bars,self.indicators,300,"LONG")
        self.assertIsNone(reason)
        self.assertEqual(len(row.values),16)
        self.assertEqual(len(set(FEATURE_NAMES)),16)
        self.assertTrue(all("pnl" not in name and "label" not in name for name in FEATURE_NAMES))
        self.assertEqual(row.available_at,self.bars[300].close_time)
        self.assertEqual(row.values[-2:],(0.,1.))

    def test_returns_and_candle_ratios_hand_calculated(self):
        row,_ = feature_at("ETHUSDT",self.bars,self.indicators,300,"SHORT")
        c=self.bars[300]
        for n,k in enumerate((1,3,12,48)):
            self.assertEqual(row.values[n],math.log(c.close/self.bars[300-k].close))
        self.assertEqual(row.values[12],2/c.close)
        self.assertEqual(row.values[13],0)
        self.assertEqual(row.values[-2:],(1.,0.))

    def test_reuses_frozen_indicator_values(self):
        f=build_features(self.bars)[300]
        row,_=feature_at("BTCUSDT",self.bars,self.indicators,300,"LONG")
        close=self.bars[300].close
        self.assertEqual(row.values[4:12],(close/f.ema20-1,f.ema20/f.ema50-1,
            f.ema50/f.ema200-1,(f.rsi14-50)/50,f.macd/close,f.macd_hist/close,
            f.atr14/close,f.relative_volume))

    def test_volume_denominator_excludes_current_candle(self):
        changed=self.bars[:]
        changed[300]=replace(changed[300],volume=changed[300].volume*2)
        original,_=feature_at("BTCUSDT",self.bars,self.indicators,300,"LONG")
        new,_=feature_at("BTCUSDT",changed,causal_indicators(changed),300,"LONG")
        self.assertEqual(new.values[11],original.values[11]*2)
        self.assertEqual(new.values[:11],original.values[:11])

    def test_warmup_exact_boundary_and_no_imputation(self):
        row,reason=feature_at("BTCUSDT",self.bars,self.indicators,198,"LONG")
        self.assertIsNone(row);self.assertEqual(reason,"WARMUP")
        self.assertIsNotNone(feature_at("BTCUSDT",self.bars,self.indicators,199,"LONG")[0])
        indicators=list(self.indicators)
        indicators[300]=replace(indicators[300],relative_volume=None)
        self.assertIsNone(feature_at("BTCUSDT",self.bars,indicators,300,"LONG")[0])

    def test_nonfinite_indicator_rejected(self):
        indicators=list(self.indicators)
        indicators[300]=replace(indicators[300],atr14=float("nan"))
        self.assertEqual(feature_at("BTCUSDT",self.bars,indicators,300,"LONG")[1],"UNAVAILABLE_OR_NONFINITE_FEATURE")

    def test_prefix_and_future_perturbation_causality(self):
        changed=self.bars[:500]+[replace(c,open=c.open*3,high=c.high*3,low=c.low*3,
            close=c.close*3,volume=c.volume*10) for c in self.bars[500:]]
        prefix=causal_indicators(self.bars[:500]); future=causal_indicators(changed)
        for i in (199,300,499):
            expected=feature_at("BTCUSDT",self.bars,self.indicators,i,"LONG")[0]
            self.assertEqual(expected,feature_at("BTCUSDT",self.bars[:500],prefix,i,"LONG")[0])
            self.assertEqual(expected,feature_at("BTCUSDT",changed,future,i,"LONG")[0])

    def test_feature_contract_rejects_future_availability_and_wrong_dimension(self):
        for values,available in [((1.,)*15,1),((1.,)*16,2),((float("inf"),)*16,1)]:
            with self.assertRaises(ValueError): FeatureRow("x","BTCUSDT",1,available,values)

    def test_locked_feature_observations_refused(self):
        c=replace(self.bars[0],open_time=DEV_END,close_time=DEV_END+STEP-1)
        with self.assertRaises(PermissionError): causal_indicators([c])

    def test_enumeration_matches_every_baseline_signal_not_journal_admissions(self):
        markets={"BTCUSDT":self.bars,"ETHUSDT":history(direction=-1)}
        opportunities,features,counts=enumerate_opportunities(markets)
        expected={(s,c.close_time,signal.side) for s,bars in markets.items()
            for c,signal in zip(bars,BaselineStrategy().signals(bars)) if signal.side!="NO TRADE"}
        self.assertGreater(len(expected),0)
        self.assertEqual({(o.symbol,o.decision_time,o.signal.side) for o in opportunities},expected)
        self.assertEqual([r.row_id for r in features],[r.row_id for r in opportunities])
        self.assertEqual([o.decision_time for o in opportunities],sorted(o.decision_time for o in opportunities))
        self.assertEqual(counts["BTCUSDT:candles"],700)

    def test_enumeration_deterministic_and_prior_rows_unchanged(self):
        markets={"BTCUSDT":self.bars,"ETHUSDT":self.bars}
        first=enumerate_opportunities(markets)
        self.assertEqual(first,enumerate_opportunities(dict(reversed(list(markets.items())))))
        prefix=enumerate_opportunities({s:bars[:500] for s,bars in markets.items()})
        cutoff=self.bars[499].close_time
        self.assertEqual(prefix[0],tuple(o for o in first[0] if o.decision_time<=cutoff))
        self.assertEqual(prefix[1],tuple(o for o in first[1] if o.decision_time<=cutoff))
