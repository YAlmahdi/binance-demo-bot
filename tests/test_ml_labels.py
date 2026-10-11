from dataclasses import replace
from decimal import Decimal as D
import unittest
from demo_futures.backtest import BacktestEngine,FundingEvent
from demo_futures.risk import BacktestConfig
from demo_futures.ml_research.config import START,DEV_END,STEP,HORIZON
from demo_futures.ml_research.labels import LabelResult,OneOpportunity,label_opportunity
from test_ml_fixtures import candle,opportunity


class MLLabelTests(unittest.TestCase):
    def setUp(self):
        self.bars=[candle(i) for i in range(60)]
        self.funding=(FundingEvent(START,".001",100),)

    def label(self,side="LONG",bars=None,funding=None,**kwargs):
        bars=self.bars if bars is None else bars
        return label_opportunity(opportunity(bars,side=side),bars,
            self.funding if funding is None else funding,**kwargs)

    def test_next_open_and_exact_48_held_bars(self):
        result=self.label()
        self.assertEqual(result.status,"VALID")
        self.assertEqual(result.interval_start,START+STEP)
        self.assertEqual(result.interval_end,START+49*STEP)
        self.assertEqual(result.trade.entry_time,result.decision_time+1)
        self.assertEqual(result.trade.exit_time,result.interval_end-1)
        self.assertEqual(result.trade.exit_reason,"holding_time_limit")

    def test_direct_frozen_engine_parity_both_sides(self):
        for side in ("LONG","SHORT"):
            op=opportunity(self.bars,side=side)
            label=label_opportunity(op,self.bars,self.funding)
            direct=BacktestEngine(strategy=OneOpportunity(op.signal)).run(
                {op.symbol:self.bars[:49]},funding={op.symbol:self.funding})
            self.assertEqual(label.trade,direct.trades[0])
            self.assertEqual(label.y,int(direct.trades[0].net_pnl>0))

    def test_long_costs_and_quantity_hand_calculated(self):
        funding=self.funding+(FundingEvent(START+450000,".001",100),)
        t=self.label(funding=funding).trade
        self.assertEqual(t.quantity,D("20.841"))  # floor(50 / 2.39910, .001)
        self.assertEqual(t.entry_price,D("100.1"));self.assertEqual(t.exit_price,D("99.9"))
        self.assertEqual(t.gross_pnl,0)
        self.assertEqual(t.slippage_cost,t.quantity*D(".2"))
        self.assertEqual(t.fees,t.quantity*D(".1"))
        self.assertEqual(t.funding_cost,t.quantity*D(".1"))
        self.assertEqual(t.net_pnl,t.quantity*D("-.4"))
        self.assertLessEqual(t.planned_loss,t.risk_budget)
        self.assertEqual(t.risk_budget,50)
        self.assertLessEqual(t.quantity*t.entry_price,D(20000))

    def test_short_signed_funding_and_costs_hand_calculated(self):
        funding=self.funding+(FundingEvent(START+450000,".001",100),)
        t=self.label("SHORT",funding=funding).trade
        self.assertEqual(t.quantity,D("20.825"))  # floor(50 / 2.40090, .001)
        self.assertEqual(t.entry_price,D("99.9"));self.assertEqual(t.exit_price,D("100.1"))
        self.assertEqual(t.funding_cost,t.quantity*D("-.1"))
        self.assertEqual(t.net_pnl,t.quantity*D("-.2"))
        self.assertEqual(t.net_pnl,t.gross_pnl-t.slippage_cost-t.fees-t.funding_cost)

    def test_long_and_short_profitable_targets(self):
        for side,high,low,expected in (("LONG",104,99,D("2.6985")),("SHORT",101,96,D("2.7015"))):
            bars=self.bars[:];bars[1]=candle(1,high=high,low=low)
            r=self.label(side,bars=bars)
            self.assertEqual(r.y,1)
            self.assertEqual(r.trade.exit_reason,"take_profit")
            self.assertEqual(r.trade.net_pnl,r.trade.quantity*expected)
            self.assertEqual(r.interval_end,START+49*STEP)  # no shortened purge interval

    def test_stop_first_when_both_levels_hit(self):
        bars=self.bars[:];bars[1]=candle(1,high=104,low=97)
        r=self.label(bars=bars)
        self.assertEqual(r.y,0)
        self.assertEqual(r.trade.exit_reason,"stop_loss_both_touched")
        self.assertEqual(r.trade.net_pnl,r.trade.quantity*D("-2.299"))

    def test_gap_stop_not_guaranteed_risk_budget(self):
        bars=self.bars[:];bars[2]=candle(2,90,91,89,90)
        r=self.label(bars=bars)
        self.assertEqual(r.trade.exit_reason,"stop_gap")
        self.assertEqual(r.trade.exit_reference,90)
        self.assertLess(r.trade.net_pnl,-r.trade.risk_budget)

    def test_gap_target_no_favorable_improvement(self):
        bars=self.bars[:];bars[2]=candle(2,110,111,109,110)
        r=self.label(bars=bars)
        self.assertEqual(r.trade.exit_reason,"target_gap_no_improvement")
        self.assertEqual(r.trade.exit_reference,103)

    def test_funding_at_entry_not_charged(self):
        t=self.label(funding=(FundingEvent(START+STEP,".2",100),)).trade
        self.assertEqual(t.funding_cost,0)

    def test_uncertain_credit_on_stop_bar_omitted_but_debit_charged(self):
        bars=self.bars[:];bars[1]=candle(1,high=104,low=97)
        for rate,skipped in (("-.001",1),(".001",0)):
            r=self.label(bars=bars,funding=(FundingEvent(START+450000,rate,100),))
            self.assertEqual(r.trade.uncertain_funding_credits_skipped,skipped)
            self.assertEqual(r.trade.funding_cost,0 if skipped else r.trade.quantity*D(".1"))

    def test_isolated_daily_halt_and_fresh_next_account(self):
        # Deliberately extreme synthetic funding triggers isolated daily guard.
        first=self.label(funding=(FundingEvent(START+450000,".2",100),))
        self.assertEqual(first.trade.exit_reason,"daily_loss_intrabar_conservative")
        op=opportunity(self.bars,index=2)
        second=label_opportunity(op,self.bars,self.funding)
        self.assertEqual(second.status,"VALID")
        self.assertEqual(second.trade.risk_budget,50)
        self.assertEqual(second.trade.quantity,D("20.841"))

    def test_midnight_reset_reuses_engine_behavior(self):
        day=START//86400000*86400000
        start=day+86400000-2*STEP
        bars=[candle(i,start=start) for i in range(49)]
        op=opportunity(bars)
        events=(FundingEvent(start,".001",100),FundingEvent(start+900000,".001",100))
        result=label_opportunity(op,bars,events)
        direct=BacktestEngine(strategy=OneOpportunity(op.signal)).run({"BTCUSDT":bars},funding={"BTCUSDT":events})
        self.assertEqual(result.trade,direct.trades[0])

    def test_incomplete_horizon_excluded_never_shortened_or_class_zero(self):
        r=self.label(bars=self.bars[:48])
        self.assertEqual(r.status,"INCOMPLETE_HORIZON")
        self.assertIsNone(r.y);self.assertIsNone(r.trade)
        r=self.label(outcome_end=START+48*STEP)
        self.assertEqual(r.status,"INCOMPLETE_HORIZON")

    def test_funding_gap_uses_full_interval_even_after_early_exit(self):
        bars=self.bars[:];bars[1]=candle(1,high=104)
        r=self.label(bars=bars,funding_gaps=(START+30*STEP,))
        self.assertEqual(r.status,"FUNDING_UNCERTAIN")
        self.assertIsNone(r.y)

    def test_missing_funding_excluded_without_dummy_record(self):
        r=self.label(funding=())
        self.assertEqual(r.status,"FUNDING_UNCERTAIN")
        self.assertIsNone(r.y)

    def test_future_only_funding_outside_horizon_does_not_establish_context(self):
        r=self.label(funding=(FundingEvent(START+55*STEP,".001",100),))
        self.assertEqual(r.status,"FUNDING_UNCERTAIN")

    def test_non_executable_sizing_excluded_and_no_risk_increase(self):
        op=opportunity(self.bars,atr=100)
        r=label_opportunity(op,self.bars,self.funding)
        self.assertEqual(r.status,"NO_EXECUTABLE_REFERENCE_TRADE")
        self.assertIsNone(r.y)

    def test_locked_decision_refused_before_touching_candles(self):
        op=replace(opportunity(self.bars),decision_time=DEV_END)
        class Trap:
            def __len__(self): raise AssertionError("Protected observations touched")
        with self.assertRaises(PermissionError): label_opportunity(op,Trap(),Trap())

    def test_wrong_decision_index_and_duplicate_funding_refused(self):
        with self.assertRaises(ValueError):
            label_opportunity(replace(opportunity(self.bars),candle_index=1),self.bars,self.funding)
        with self.assertRaises(ValueError): self.label(funding=self.funding*2)

    def test_label_determinism_and_outside_horizon_independence(self):
        original=self.label()
        bars=self.bars[:49]+[replace(c,open=c.open*2,high=c.high*2,low=c.low*2,close=c.close*2) for c in self.bars[49:]]
        self.assertEqual(original,self.label(bars=bars))
        self.assertEqual(original,self.label())

    def test_target_zero_is_nonpositive_class(self):
        r=self.label()
        trade=replace(r.trade,net_pnl=D(0))
        result=LabelResult(r.row_id,r.symbol,r.decision_time,r.interval_start,r.interval_end,
            "VALID","Synthetic exact zero",0,trade)
        self.assertEqual(result.y,0)
        with self.assertRaises(ValueError): replace(result,y=1)
