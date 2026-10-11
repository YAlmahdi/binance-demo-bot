from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch
import unittest
from demo_futures.ml_research.portfolio import AdmissionStrategy,replay
from demo_futures.ml_research.config import START,FOLDS,STEP,BUFFER
from demo_futures.strategy import Signal
from demo_futures.backtest import FundingEvent,BacktestEngine,metrics
from demo_futures.risk import BacktestConfig
from test_ml_fixtures import history


class MLPortfolioTests(unittest.TestCase):
    def setUp(self):
        self.begin,self.end=FOLDS[0]
        # Full window with constant synthetic candles; baseline is injected only in these unit fixtures.
        template=history(count=1)[0]
        self.bars=tuple(replace(template,open_time=t,close_time=t+STEP-1) for t in range(START,self.end,STEP))
        self.data=SimpleNamespace(candles={"BTCUSDT":self.bars},funding={"BTCUSDT":(FundingEvent(START,"0",100),)},funding_gaps={"BTCUSDT":()})
        self.decision=self.begin+STEP-1
        self.map={("BTCUSDT",self.decision):.65}

    def signals(self,bars):
        return [Signal("LONG","Synthetic opportunity",1) if c.close_time==self.decision else Signal("NO TRADE","Synthetic none") for c in bars]

    def test_threshold_and_next_candle_execution(self):
        with patch("demo_futures.ml_research.portfolio.BaselineStrategy.signals",self.signals):
            result,_=replay(self.data,1,"ml",self.map)
        self.assertEqual(len(result.trades),1);self.assertEqual(result.trades[0].entry_time,self.decision+1)

    def test_below_threshold_and_cash_admit_none(self):
        with patch("demo_futures.ml_research.portfolio.BaselineStrategy.signals",self.signals):
            for policy,p in (("ml",{("BTCUSDT",self.decision):.649999}), ("no_trade",None)):
                result,_=replay(self.data,1,policy,p);self.assertEqual(result.metrics["net_pnl"],0)

    def test_missing_probability_fails_closed(self):
        with patch("demo_futures.ml_research.portfolio.BaselineStrategy.signals",self.signals):
            with self.assertRaises(ValueError):replay(self.data,1,"ml",{})

    def test_retrospective_funding_gap_does_not_gate_admission(self):
        data=replace_namespace(self.data,funding_gaps={"BTCUSDT":(self.decision+2*STEP,)})
        with patch("demo_futures.ml_research.portfolio.BaselineStrategy.signals",self.signals):
            result,summary=replay(data,1,"ml",self.map)
        self.assertEqual(len(result.trades),1);self.assertEqual(summary["economic_data_quality"],"INSUFFICIENT")
        self.assertEqual(summary["risk_evidence"],"NOT CLEARED")

    def test_cost_stress_only_doubles_fees_and_slippage(self):
        with patch("demo_futures.ml_research.portfolio.BaselineStrategy.signals",self.signals):
            normal,_=replay(self.data,1,"ml",self.map);stress,_=replay(self.data,1,"ml",self.map,doubled_costs=True)
        self.assertEqual(stress.config.fee_rate,normal.config.fee_rate*2)
        self.assertEqual(stress.config.slippage_rate,normal.config.slippage_rate*2)
        for n in normal.config.__dataclass_fields__:
            if n not in ("fee_rate","slippage_rate"):self.assertEqual(getattr(normal.config,n),getattr(stress.config,n))
        self.assertEqual(normal.trades[0].signal_time,stress.trades[0].signal_time)

    def test_fresh_account_and_exact_window_ledger(self):
        with patch("demo_futures.ml_research.portfolio.BaselineStrategy.signals",self.signals):
            result,_=replay(self.data,1,"ml",self.map)
        self.assertEqual(result.equity[0].timestamp,self.begin);self.assertEqual(result.equity[0].equity,10000)
        self.assertEqual(result.equity[-1].timestamp,self.end-1)
        self.assertEqual(result.metrics, {**metrics(result.trades,result.equity,10000),"exposure_time_pct":result.metrics["exposure_time_pct"]})

    def test_horizon_cutoff_applies_to_every_policy(self):
        self.decision=self.end-STEP-1
        with patch("demo_futures.ml_research.portfolio.BaselineStrategy.signals",self.signals):
            for policy in ("baseline","ml","no_trade"):
                result,_=replay(self.data,1,policy,{})
                self.assertEqual(len(result.trades),0)

    def test_common_window_baseline_parity(self):
        with patch("demo_futures.ml_research.portfolio.BaselineStrategy.signals",self.signals):
            baseline,_=replay(self.data,1,"baseline");admitted,_=replay(self.data,1,"ml",self.map)
        # Entry reasons differ; all financial and timing fields must agree.
        self.assertEqual(replace(admitted.trades[0],entry_reason=baseline.trades[0].entry_reason),baseline.trades[0])

    def test_locked_portfolio_stage_refused(self):
        with self.assertRaises(PermissionError):replay(self.data,4,"ml",{})


def replace_namespace(obj,**changes):return SimpleNamespace(**{**vars(obj),**changes})
