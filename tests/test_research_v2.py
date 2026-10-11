"""Synthetic V2 foundation tests; no saved market data, fitting or inference."""
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal as D
import hashlib
import math
import unittest
from unittest.mock import patch
from demo_futures.data import Candle
from demo_futures.backtest import BacktestEngine, FundingEvent
from demo_futures.risk import BacktestConfig
from demo_futures.research_v2.config import *
from demo_futures.research_v2.features import *
from demo_futures.research_v2.opportunities import *
from demo_futures.research_v2.labels import *
from demo_futures.research_v2.labels import _SingleAction
from demo_futures.research_v2.validation import *
from demo_futures.research_v2.artifacts import *

BASE = 1262304000000  # Invented fixtures anchored at 2010-01-01 UTC, never saved market data.
BOUNDARY = BASE + 18 * HOUR
DECISION = BOUNDARY - 1

def candle(i, price=100, *, volume=100, high=None, low=None):
    t = BASE + i * STEP
    return Candle(t, price, price + .5 if high is None else high,
                  price - .5 if low is None else low, price, volume, t + STEP - 1, 10000, 10)

def series(symbol="BTCUSDT", count=270, bars=None):
    bars = [candle(i) for i in range(count)] if bars is None else bars
    return SyntheticSeries(symbol, tuple(ObservedCandle(c, c.close_time+1) for c in bars), "generated-unit-fixture")

def opportunity(symbol="BTCUSDT", data=None):
    return Opportunity(feature_at(data or series(symbol), DECISION))

def coverage(events=None, **kwargs):
    return FundingCoverage(BOUNDARY, BOUNDARY+HORIZON, True,
                           (FundingEvent(BASE, ".001", 100),) if events is None else events, **kwargs)

def interval(symbol, boundary):
    return IntervalRow(symbol, boundary - 1, boundary + HORIZON)

def training_contract():
    window = DevelopmentWindow(BASE, BASE+100*HOUR, BASE+400*HOUR)
    rows = (interval("BTCUSDT",BASE+20*HOUR), interval("ETHUSDT",BASE+20*HOUR))
    ids = tuple(r.row_id for r in rows)
    receipt = TrainingReceipt(ids, ids_hash(ids), window)
    return TransformContract(receipt, (-1.,)*8, (1.,)*8, (0.,)*8, (1.,)*8), receipt

class ConfigurationTests(unittest.TestCase):
    def test_recipe_is_fixed_and_immutable(self):
        r = Recipe()
        self.assertEqual(r.symbols,("BTCUSDT","ETHUSDT"))
        self.assertEqual(len(r.feature_names),9)
        self.assertEqual(r.risk_clearance,"NOT CLEARED")
        with self.assertRaises(FrozenInstanceError):r.symbols=("SOLUSDT",)
        with self.assertRaises(TypeError):Recipe(symbols=("SOLUSDT",))
        with self.assertRaises(ValueError):replace(r,feature_names=("new",))

    def test_strict_inactive_symbol_refusal(self):
        for symbol in ("SOLUSDT","BNBUSDT","XRPUSDT","BTCUSD","btcusdt"):
            with self.subTest(symbol=symbol),self.assertRaises(PermissionError):
                BtcEthEncoder().encode(symbol)

    def test_frozen_financial_config_and_drift_refusal(self):
        self.assertEqual(frozen_financial_config(),BacktestConfig())
        with patch("demo_futures.research_v2.config.BacktestConfig",return_value=BacktestConfig(fee_rate=".001")):
            with self.assertRaises(ValueError):frozen_financial_config()

    def test_synthetic_only_and_receipt_timing(self):
        with self.assertRaises(PermissionError):replace(series(),evidence="HISTORICAL")
        with self.assertRaises(ValueError):ObservedCandle(candle(0),BASE)
        for value in (True,1.5,-1):
            with self.assertRaises(ValueError):timestamp(value)

class FeatureTests(unittest.TestCase):
    def test_constant_prices_hand_calculated_nine_inputs(self):
        f = feature_at(series(), DECISION)
        self.assertEqual(f.status,"READY")
        self.assertEqual(f.values[:4],(0.,0.,0.,0.))
        self.assertAlmostEqual(f.values[4],.01)
        self.assertAlmostEqual(f.values[5],.01)
        self.assertEqual(f.values[6],0)
        self.assertAlmostEqual(f.values[7],math.log(2))
        self.assertEqual(f.values[8],0)
        self.assertEqual(f.atr14,1)

    def test_log_returns_population_volatility_and_wilder_atr(self):
        from demo_futures.indicators import atr
        bars = [candle(i,100*math.exp(i*.001)) for i in range(270)]
        f = feature_at(series(bars=bars),DECISION)
        for n,v in zip((1,12,48),f.values[:3]):self.assertAlmostEqual(v,n*.001)
        self.assertAlmostEqual(f.values[3],0,places=12)
        self.assertAlmostEqual(f.atr14,atr(bars[:216],14)[-1])

    def test_volume_denominator_excludes_current(self):
        bars=[candle(i) for i in range(270)]
        bars[215]=candle(215,volume=200)
        self.assertAlmostEqual(feature_at(series(bars=bars),DECISION).values[7],math.log(3))

    def test_body_definition_uses_close_denominator(self):
        bars=[candle(i) for i in range(270)]
        bars[215]=replace(bars[215],open=99.8)
        self.assertAlmostEqual(feature_at(series(bars=bars),DECISION).values[6],.002)

    def test_future_perturbation_cannot_change_earlier_features(self):
        s=series()
        observations=s.observations[:216]+tuple(ObservedCandle(replace(v.candle,open=1000,high=2000,low=900,close=1500,volume=float("nan")),v.available_at) for v in s.observations[216:])
        self.assertEqual(feature_at(s,DECISION),feature_at(replace(s,observations=observations),DECISION))

    def test_warmup_exact_boundary_and_no_imputation(self):
        s=series(count=192)
        f=feature_at(s,BASE+16*HOUR-1)
        self.assertEqual(f.status,"WARMUP")
        self.assertIsNone(f.values)
        self.assertEqual(feature_at(series(),DECISION).status,"READY")

    def test_missing_duplicate_and_unordered_bars_rejected(self):
        bars=[candle(i) for i in range(270)]
        for changed in (bars[:80]+bars[81:],bars[:80]+[bars[79]]+bars[80:],
                        bars[:80]+[bars[81],bars[80]]+bars[82:]):
            with self.subTest():
                self.assertEqual(feature_at(series(bars=changed),DECISION).status,"DATA_QUALITY")

    def test_nonfinite_and_bad_ohlc_rejected(self):
        for bar in (replace(candle(215),close=float("nan")),replace(candle(215),high=99),replace(candle(215),open=True)):
            bars=[candle(i) for i in range(270)];bars[215]=bar
            self.assertEqual(feature_at(series(bars=bars),DECISION).status,"DATA_QUALITY")

    def test_zero_volume_range_and_prior_volume_rejected(self):
        for kind in ("volume","range","prior"):
            bars=[candle(i) for i in range(270)]
            if kind=="volume":bars[215]=replace(bars[215],volume=0)
            elif kind=="range":bars[215]=replace(bars[215],open=100,high=100,low=100,close=100)
            else:
                for i in range(195,215):bars[i]=replace(bars[i],volume=0)
            self.assertEqual(feature_at(series(bars=bars),DECISION).status,"DATA_QUALITY")

    def test_late_receipt_and_missing_decision_bar(self):
        s=series()
        obs=list(s.observations);obs[215]=replace(obs[215],available_at=BOUNDARY+1)
        self.assertEqual(feature_at(replace(s,observations=obs),DECISION).reason,"NOT_AVAILABLE_AT_DECISION")
        self.assertEqual(feature_at(series(count=215),DECISION).reason,"MISSING_DECISION_BAR")

    def test_feature_schema_symbol_flag_and_decision_time(self):
        f=feature_at(series(),DECISION)
        with self.assertRaises(ValueError):replace(f,values=f.values[:-1]+(1,))
        with self.assertRaises(ValueError):replace(f,decision_time=DECISION+1)
        with self.assertRaises(ValueError):replace(f,values=(float("inf"),)+f.values[1:])

class SchedulingTests(unittest.TestCase):
    def test_exact_hour_completed_bar_and_pair_order(self):
        markets={"ETHUSDT":series("ETHUSDT"),"BTCUSDT":series()}
        self.assertEqual(hourly_opportunities(markets,BOUNDARY,BOUNDARY+HOUR,available_at=BOUNDARY-1),())
        ops=hourly_opportunities(markets,BOUNDARY,BOUNDARY+HOUR,available_at=BOUNDARY)
        self.assertEqual(tuple(o.symbol for o in ops),SYMBOLS)
        self.assertTrue(all(o.decision_time==DECISION and o.interval_start==BOUNDARY for o in ops))
        self.assertEqual(ops[1].features.values[-1],1)
        self.assertEqual(ops[0].interval_end,BOUNDARY+HORIZON)

    def test_pair_retains_individual_causal_abstention(self):
        ops=hourly_opportunities({"BTCUSDT":series(),"ETHUSDT":series("ETHUSDT",count=215)},BOUNDARY,BOUNDARY+HOUR,available_at=BOUNDARY)
        self.assertEqual(len(ops),2)
        self.assertEqual(tuple(o.features.status for o in ops),("READY","DATA_QUALITY"))

    def test_inactive_extra_missing_and_mismatched_symbol_refused(self):
        for markets in ({"BTCUSDT":series()}, {"BTCUSDT":series(),"ETHUSDT":series("ETHUSDT"),"XRPUSDT":series()},
                        {"BTCUSDT":series("ETHUSDT"),"ETHUSDT":series()}):
            with self.subTest(),self.assertRaises((ValueError,PermissionError)):
                hourly_opportunities(markets,BOUNDARY,BOUNDARY+HOUR,available_at=BOUNDARY)

    def test_schedule_determinism_and_future_independence(self):
        markets={"BTCUSDT":series(),"ETHUSDT":series("ETHUSDT")}
        before=hourly_opportunities(markets,BOUNDARY,BOUNDARY+HOUR,available_at=BOUNDARY)
        markets["BTCUSDT"]=series(count=400)
        self.assertEqual(before,hourly_opportunities(markets,BOUNDARY,BOUNDARY+HOUR,available_at=BOUNDARY))
        with self.assertRaises(ValueError):hourly_opportunities(markets,BOUNDARY+1,BOUNDARY+HOUR,available_at=BOUNDARY)

class LabelTests(unittest.TestCase):
    def label(self,data=None,cov=None,op=None,**kwargs):
        s=data or series()
        return paired_outcome(op or opportunity(data=s),s,cov or coverage(),outcome_end=kwargs.get("outcome_end",BOUNDARY+HORIZON))

    def test_paired_separate_long_short_and_hand_calculated_costs(self):
        cov=coverage((FundingEvent(BASE,".001",100),FundingEvent(BOUNDARY+150000,".001",100)))
        pair=self.label(cov=cov)
        self.assertTrue(pair.fit_eligible)
        a,b=pair.long.trade,pair.short.trade
        self.assertEqual(a.quantity,D("20.841"))
        self.assertEqual(b.quantity,D("20.825"))
        self.assertEqual((a.entry_price,a.exit_price),(D("100.1"),D("99.9")))
        self.assertEqual(a.fees,a.quantity*D(".1"))
        self.assertEqual(a.slippage_cost,a.quantity*D(".2"))
        self.assertEqual(a.funding_cost,a.quantity*D(".1"))
        self.assertEqual(a.net_pnl,a.quantity*D("-.4"))
        self.assertEqual(b.funding_cost,b.quantity*D("-.1"))
        self.assertEqual(b.net_pnl,b.quantity*D("-.2"))
        self.assertEqual(pair.long.net_r,a.net_pnl/50)
        self.assertEqual(pair.cash_r,0)
        self.assertEqual(pair.hindsight_action(),"NO TRADE")

    def test_full_horizon_and_next_open_both_actions(self):
        pair=self.label()
        for action in (pair.long,pair.short):
            self.assertEqual(action.trade.entry_time,BOUNDARY)
            self.assertEqual(action.trade.exit_time,BOUNDARY+HORIZON-1)
            self.assertEqual(action.trade.exit_reason,"holding_time_limit")

    def test_direct_frozen_simulator_parity(self):
        s=series();op=opportunity(data=s);cov=coverage()
        pair=self.label(data=s,cov=cov)
        bars=[v.candle for v in s.observations[215:264]]
        for side,label in (("LONG",pair.long),("SHORT",pair.short)):
            expected=BacktestEngine(strategy=_SingleAction(side,1)).run({"BTCUSDT":bars},funding={"BTCUSDT":cov.events})
            self.assertEqual(label.trade,expected.trades[0])

    def test_stops_precede_targets_and_actions_remain_independent(self):
        bars=[candle(i) for i in range(270)]
        bars[216]=candle(216,high=104,low=97)
        pair=self.label(data=series(bars=bars))
        self.assertEqual(pair.long.trade.exit_reason,"stop_loss_both_touched")
        self.assertEqual(pair.short.trade.exit_reason,"stop_loss_both_touched")
        self.assertEqual(pair.long.trade.net_pnl,pair.long.trade.quantity*D("-2.299"))

    def test_long_profitable_target_is_not_achievable_oracle_portfolio(self):
        bars=[candle(i) for i in range(270)];bars[216]=candle(216,high=104,low=99.5)
        pair=self.label(data=series(bars=bars))
        self.assertEqual(pair.long.trade.exit_reason,"take_profit")
        self.assertEqual(pair.long.trade.net_pnl,pair.long.trade.quantity*D("2.6985"))
        self.assertEqual(pair.hindsight_action(),"LONG")

    def test_no_risk_increase_to_make_entry_executable(self):
        bars=[candle(i,high=200,low=1) for i in range(270)]
        pair=self.label(data=series(bars=bars))
        self.assertFalse(pair.fit_eligible)
        self.assertTrue(all(a.status=="NO_EXECUTABLE_REFERENCE_TRADE" for a in (pair.long,pair.short)))
        with self.assertRaises(ValueError):pair.hindsight_action()

    def test_incomplete_or_late_observed_horizon_no_negative_or_cash_label(self):
        for s,end in ((series(count=263),BOUNDARY+HORIZON),(series(),BOUNDARY+HORIZON-STEP)):
            pair=self.label(data=s,outcome_end=end)
            self.assertEqual(pair.long.status,"INCOMPLETE_HORIZON")
            self.assertIsNone(pair.long.net_r)
            with self.assertRaises(ValueError):pair.hindsight_action()
        s=series();obs=list(s.observations);obs[263]=replace(obs[263],available_at=BOUNDARY+HORIZON+1)
        self.assertEqual(self.label(data=replace(s,observations=obs)).long.status,"INCOMPLETE_HORIZON")

    def test_gap_invalid_horizon_and_causal_exclusion(self):
        s=series();obs=list(s.observations);obs[230]=replace(obs[230],candle=replace(obs[230].candle,close=float("nan")))
        self.assertEqual(self.label(data=replace(s,observations=obs)).long.status,"DATA_QUALITY")
        short=series(count=215)
        self.assertEqual(self.label(data=short).long.status,"CAUSAL_ABSTENTION")

    def test_funding_unknown_full_horizon_excluded_even_after_early_exit(self):
        bars=[candle(i) for i in range(270)];bars[216]=candle(216,high=104)
        cov=coverage(uncertain_intervals=((BOUNDARY+3*HOUR,BOUNDARY+HORIZON),))
        self.assertEqual(self.label(data=series(bars=bars),cov=cov).long.status,"FUNDING_UNCERTAIN")
        self.assertEqual(self.label(cov=replace(coverage(),complete=False)).short.status,"FUNDING_UNCERTAIN")

    def test_empty_context_future_only_and_missing_mark_not_zero_funding(self):
        for cov,status in ((coverage(()),"FUNDING_CONTEXT_UNAVAILABLE"),
                           (coverage((FundingEvent(BOUNDARY+HORIZON+1,".001",100),)),"FUNDING_CONTEXT_UNAVAILABLE"),
                           (coverage((FundingEvent(BOUNDARY+1,".001"),)),"FUNDING_UNCERTAIN")):
            self.assertEqual(self.label(cov=cov).long.status,status)

    def test_entry_time_settlement_not_charged_and_uncertain_credit_skipped(self):
        pair=self.label(cov=coverage((FundingEvent(BOUNDARY,".1",100),)))
        self.assertEqual(pair.long.trade.funding_cost,0)
        bars=[candle(i) for i in range(270)];bars[216]=candle(216,high=104,low=97)
        pair=self.label(data=series(bars=bars),cov=coverage((FundingEvent(BOUNDARY+1,"-.001",100),)))
        self.assertEqual(pair.long.trade.funding_cost,0)
        self.assertEqual(pair.long.trade.uncertain_funding_credits_skipped,1)
        self.assertGreater(pair.short.trade.funding_cost,0)

    def test_overrun_labels_retained_and_daily_accounts_fresh(self):
        pair=self.label(cov=coverage((FundingEvent(BOUNDARY+1,".2",100),)))
        self.assertTrue(pair.long.budget_breach)
        self.assertTrue(pair.long.funding_reserve_overrun)
        self.assertLess(pair.long.net_r,-1)
        self.assertEqual(pair.long.trade.exit_reason,"daily_loss_intrabar_conservative")
        self.assertEqual(self.label().long.trade.risk_budget,50)
        self.assertTrue(pair.fit_eligible)

    def test_eth_adapter_and_cross_symbol_funding_refusal(self):
        s=series("ETHUSDT")
        with self.assertRaises(ValueError):self.label(data=s)
        pair=self.label(data=s,cov=coverage(symbol="ETHUSDT"))
        self.assertTrue(pair.fit_eligible)
        self.assertTrue(all(x.trade.symbol=="ETHUSDT" for x in (pair.long,pair.short)))

    def test_duplicate_funding_and_outcome_identity_rejected(self):
        e=FundingEvent(BASE,".001",100)
        with self.assertRaises(ValueError):coverage((e,e))
        pair=self.label()
        with self.assertRaises(ValueError):replace(pair,long=pair.short)
        with self.assertRaises(ValueError):replace(pair.long,net_r=D(123))

    def test_label_determinism_and_future_outside_horizon_independence(self):
        original=self.label()
        s=series();obs=s.observations[:264]+tuple(ObservedCandle(replace(v.candle,close=float("nan")),v.available_at) for v in s.observations[264:])
        self.assertEqual(original,self.label(data=replace(s,observations=obs)))
        self.assertEqual(original,self.label())

class ValidationTests(unittest.TestCase):
    def test_purge_buffer_and_exact_equality_boundaries(self):
        w=DevelopmentWindow(BASE,BASE+40*HOUR,BASE+100*HOUR)
        self.assertEqual(partition_reason(interval("BTCUSDT",BASE+32*HOUR),w,"train"),"ACCEPT")
        self.assertEqual(partition_reason(interval("BTCUSDT",BASE+33*HOUR),w,"train"),"FOUR_HOUR_BUFFER")
        self.assertEqual(partition_reason(interval("BTCUSDT",BASE+37*HOUR),w,"train"),"PURGED_OVERLAP")
        self.assertEqual(partition_reason(interval("BTCUSDT",BASE+96*HOUR),w,"development_evaluation"),"ACCEPT")
        self.assertEqual(partition_reason(interval("BTCUSDT",BASE+97*HOUR),w,"development_evaluation"),"INCOMPLETE_EVALUATION_HORIZON")

    def test_supplied_split_integrity_and_locked_stage_refusal(self):
        w=DevelopmentWindow(BASE,BASE+40*HOUR,BASE+100*HOUR)
        train=tuple(interval(s,BASE+20*HOUR) for s in SYMBOLS)
        evaluation=tuple(interval(s,BASE+50*HOUR) for s in SYMBOLS)
        self.assertTrue(validate_partition(train,evaluation,w))
        with self.assertRaises(ValueError):validate_partition(train,train,w)
        with self.assertRaises(ValueError):validate_partition(train[::-1],evaluation,w)
        with self.assertRaises(PermissionError):partition_reason(None,w,"final")
        with self.assertRaises(PermissionError):sample_gate((),"confirmation")

    def test_hard_sample_gates_and_joint_nonoverlap_counts(self):
        rows=tuple(interval(s,BASE+i*HOUR) for i in range(1,602) for s in SYMBOLS)
        self.assertEqual(sample_gate(rows[:1000],"train")["status"],"SUFFICIENT")
        self.assertEqual(sample_gate(rows[:998],"train")["status"],"INSUFFICIENT")
        self.assertEqual(sample_gate(rows[:300],"development_evaluation")["status"],"INSUFFICIENT") # 38 groups, not 75.
        self.assertEqual(sample_gate(rows[:480],"development_evaluation")["joint_nonoverlapping_groups"],60)
        self.assertEqual(sample_gate(rows[:480],"development_evaluation")["status"],"SUFFICIENT")
        with self.assertRaises(ValueError):sample_gate(rows[:2]*2,"train")

    def test_training_receipt_rejects_future_eval_and_forged_hash(self):
        contract,receipt=training_contract()
        with self.assertRaises(ValueError):replace(receipt,row_ids_sha256="a"*64)
        ids=(interval("BTCUSDT",receipt.window.evaluation_start+HOUR).row_id,)
        with self.assertRaises(ValueError):replace(receipt,row_ids=ids,row_ids_sha256=ids_hash(ids))
        with self.assertRaises(ValueError):replace(receipt,stage="development_evaluation")

    def test_transform_schema_no_fit_and_symbol_passthrough(self):
        c,r=training_contract()
        self.assertFalse(hasattr(c,"fit"))
        f=feature_at(series("ETHUSDT"),DECISION)
        out=apply_transform(f,c,r)
        self.assertEqual(out.status,"IN_RANGE")
        self.assertEqual(out.values,f.values)
        with self.assertRaises(ValueError):replace(c,feature_names=FEATURES[::-1])
        with self.assertRaises(ValueError):replace(c,scale=(0.,)*8)

    def test_bounds_accept_equality_no_clipping_or_future_repair(self):
        c,r=training_contract();f=feature_at(series(),DECISION)
        self.assertEqual(apply_transform(replace(f,values=(1.,)+f.values[1:]),c,r).status,"IN_RANGE")
        out=apply_transform(replace(f,values=(1.0001,)+f.values[1:]),c,r)
        self.assertEqual(out.status,"OUT_OF_RANGE")
        self.assertIsNone(out.values)
        self.assertEqual(out.breaches,("log_return_1",))
        other=replace(r,row_ids=(r.row_ids[0],),row_ids_sha256=ids_hash((r.row_ids[0],)))
        with self.assertRaises(ValueError):apply_transform(f,c,other)

    def test_coverage_25pct_gate_label_independent_and_small_blocks(self):
        w=DevelopmentWindow(BASE,BASE+100*HOUR,BASE+400*HOUR)
        decisions=tuple(RangeDecision(s,BASE+i*HOUR-1,True,i%4==0) for i in range(101,401) for s in SYMBOLS)
        rows=tuple(interval(d.symbol,d.decision_time+1) for d in decisions if not d.abstained and d.decision_time+1+HORIZON<=w.evaluation_end)
        out=abstention_gate(decisions,w,rows)
        self.assertEqual(out["coverage"]["overall"]["rate"],.25)
        self.assertEqual(out["status"],"SUFFICIENT")
        self.assertEqual(abstention_gate(decisions,w,())["coverage"],out["coverage"]) # Label exclusions never shrink denominator.
        changed=(replace(decisions[0],abstained=True),)+decisions[1:]
        self.assertEqual(abstention_gate(changed,w,tuple(r for r in rows if r.row_id!=f"{decisions[0].symbol}:{decisions[0].decision_time}"))["status"],"INSUFFICIENT")
        small=abstention_gate(decisions[:2],DevelopmentWindow(BASE,BASE+100*HOUR,BASE+101*HOUR),())
        self.assertEqual(small["coverage"]["BTCUSDT:block-0"]["status"],"TOO_SMALL")

    def test_invalid_coverage_and_interval_refused(self):
        with self.assertRaises(ValueError):RangeDecision("BTCUSDT",DECISION,False,True)
        with self.assertRaises(ValueError):IntervalRow("BTCUSDT",DECISION,BOUNDARY+HOUR)

class ArtifactTests(unittest.TestCase):
    def test_inert_immutable_and_deterministic_provenance(self):
        item=EngineeringArtifact("a"*64,(("src/demo_futures/research_v2/config.py","b"*64),))
        self.assertEqual(item.sha256,hashlib.sha256(item.to_json().encode()).hexdigest())
        self.assertEqual(item.to_json(),replace(item).to_json())
        self.assertIn("NOT FITTED",item.state)
        self.assertIn("180-day",item.calendar)
        with self.assertRaises(FrozenInstanceError):item.state="DEPLOYED"

    def test_artifact_rejects_schema_mismatch_and_unsafe_reference(self):
        with self.assertRaises(ValueError):EngineeringArtifact("bad",())
        with self.assertRaises(ValueError):EngineeringArtifact("a"*64,(),recipe_sha256="b"*64)
        for name in ("src/../file.py","src/file.py:stream","src/file.py/../other.py","src//file.py"):
            with self.assertRaises(ValueError):EngineeringArtifact("a"*64,((name,"b"*64),))

class SafetyTests(unittest.TestCase):
    def test_guard_rejects_protected_reads_and_old_report_writes(self):
        from verify_research_v2 import ROOT, guard_for
        g=guard_for(ROOT/"reports/research-v2/SYNTHETIC-MOCK")
        for p in (ROOT/".env",ROOT/"data/market.sqlite3",ROOT/"artifacts/future-expansion/fixture.csv",
                  ROOT/"reports/ml-research/locked.json"):
            with self.subTest(path=p),self.assertRaises(RuntimeError):g("open",(str(p),"r",0))
        with self.assertRaises(RuntimeError):g("open",(str(ROOT/"src/demo_futures/risk.py"),"w",1))

    def test_guard_rejects_all_network_account_and_training_events(self):
        from verify_research_v2 import ROOT, guard_for, BLOCKED_EVENTS
        events=[]
        g=guard_for(ROOT/"reports/research-v2/SYNTHETIC-MOCK",event_log=events)
        # Event callback checks only: these do not initiate sockets, imports or account access.
        for event in ("urllib.Request","socket.getaddrinfo","socket.connect","http.client.send","sqlite3.connect","subprocess.Popen"):
            with self.assertRaises(RuntimeError):g(event,())
        for name in ("demo_futures.client","demo_futures.config","demo_futures.ml_research.model","sklearn","dotenv"):
            with self.assertRaises(RuntimeError):g("import",(name,))
        self.assertEqual(len(events),6)  # Mock callbacks never contaminate runtime event evidence.

class RefinementTests(unittest.TestCase):
    def test_label_refuses_mismatched_causal_atr(self):
        op=opportunity()
        forged=Opportunity(replace(op.features,atr14=100))
        with self.assertRaises(ValueError):paired_outcome(forged,series(),coverage(),outcome_end=BOUNDARY+HORIZON)

    def test_risk_flags_cannot_hide_overrun(self):
        pair=paired_outcome(opportunity(),series(),coverage((FundingEvent(BOUNDARY+1,".2",100),)),outcome_end=BOUNDARY+HORIZON)
        with self.assertRaises(ValueError):replace(pair.long,budget_breach=False)
        with self.assertRaises(ValueError):replace(pair.long,funding_reserve_overrun=False)

    def test_coverage_refuses_omitted_slots_and_reports_feature_breaches(self):
        w=DevelopmentWindow(BASE,BASE+100*HOUR,BASE+102*HOUR)
        ds=tuple(RangeDecision(s,BASE+i*HOUR-1,True,True,("log_return_1",)) for i in (101,102) for s in SYMBOLS)
        out=abstention_gate(ds,w,())
        self.assertEqual(out["coverage"]["overall"]["per_feature_breaches"]["log_return_1"],4)
        with self.assertRaises(ValueError):abstention_gate(ds[:-1],w,())

    def test_artifact_source_order_is_canonical(self):
        sources=(("src/b.py","b"*64),("src/a.py","a"*64))
        self.assertEqual(EngineeringArtifact("c"*64,sources).sha256,EngineeringArtifact("c"*64,sources[::-1]).sha256)
