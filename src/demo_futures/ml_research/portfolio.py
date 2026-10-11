"""Admission adapter: reuse frozen simulator, keep retrospective labels out of decisions."""
from collections import Counter
from dataclasses import replace
from decimal import Decimal
import math
from ..strategy import BaselineStrategy, Signal
from ..backtest import BacktestEngine, metrics
from ..risk import BacktestConfig
from .config import START, DEV_END, FOLDS, BUFFER, STEP


class AdmissionStrategy:
    version="frozen-baseline-development-admission-v001"
    def __init__(self, fold, policy, probabilities=None):
        if type(fold) is not int or not 1<=fold<=3: raise PermissionError("Only development folds are permitted")
        if policy not in ("ml", "baseline", "no_trade", "training_prevalence", "majority_class"):
            raise ValueError("Unknown fixed policy")
        self.begin,self.end=FOLDS[fold-1]; self.policy=policy; self.probabilities=probabilities or {}

    def signals(self,candles):
        if not candles or any(not START<=c.open_time<=c.close_time<self.end<=DEV_END for c in candles):
            raise PermissionError("Portfolio candle input exceeds fixed development window")
        raw=BaselineStrategy().signals(candles); output=[]
        # Symbol is supplied by the runner through a per-symbol adapter dispatch (price-independent identity).
        for c,s in zip(candles,raw):
            if not self.begin<=c.close_time<self.end or c.close_time+1+BUFFER>self.end:
                output.append(Signal("NO TRADE","Common fixed evaluation window/horizon cutoff")); continue
            if s.side=="NO TRADE" or self.policy=="baseline": output.append(s); continue
            if self.policy=="no_trade": output.append(Signal("NO TRADE","Cash baseline")); continue
            key=(self.symbol,c.close_time)
            if key not in self.probabilities: raise ValueError("Missing causal admission probability")
            p=float(self.probabilities[key])
            if not math.isfinite(p) or not 0<=p<=1: raise ValueError("Invalid admission probability")
            if p>=.65: output.append(Signal(s.side,f"{s.reason}; {self.policy} p={p:.12g} >= frozen 0.65",s.atr))
            else: output.append(Signal("NO TRADE",f"{self.policy} p={p:.12g} below frozen 0.65"))
        return output


class PairedAdmission:
    """Engine calls signals in sorted symbol order; assert and bind exact input series."""
    version=AdmissionStrategy.version
    def __init__(self,fold,policy,probabilities,markets):
        self.fold,self.policy,self.probabilities=fold,policy,probabilities
        self.identities={id(v):s for s,v in markets.items()}
        # Engine validates into fresh lists; identify the complete immutable candle tuples explicitly.
        self.series={tuple(v):s for s,v in markets.items()}
        if len(self.series)!=len(markets): raise ValueError("Ambiguous symbol candle identity")
    def signals(self,candles):
        symbol=self.series.get(tuple(candles))
        if symbol is None: raise ValueError("Unknown candle series")
        adapter=AdmissionStrategy(self.fold,self.policy,self.probabilities); adapter.symbol=symbol
        return adapter.signals(candles)


def replay(data,fold,policy,probabilities=None,*,doubled_costs=False):
    if type(fold) is not int or not 1<=fold<=3: raise PermissionError("Only fixed development portfolios allowed")
    begin,end=FOLDS[fold-1]
    markets={s:tuple(c for c in bars if c.close_time<end) for s,bars in data.candles.items()}
    if any(not b or b[0].open_time!=START or b[-1].close_time+1!=end for b in markets.values()):
        raise ValueError("Identical complete warmup/evaluation coverage required")
    funding={s:tuple(e for e in events if e.timestamp<end) for s,events in data.funding.items()}
    config=BacktestConfig()
    if doubled_costs: config=replace(config,fee_rate=config.fee_rate*2,slippage_rate=config.slippage_rate*2)
    result=BacktestEngine(config=config,strategy=PairedAdmission(fold,policy,probabilities,markets)).run(markets,funding=funding)
    if any(not begin<=t.signal_time<t.entry_time<=t.exit_time<end or t.signal_time+1+BUFFER>end for t in result.trades):
        raise ArithmeticError("Portfolio timing escaped evaluation boundary")
    curve=[p for p in result.equity if p.timestamp>=begin]
    if not curve or curve[0].timestamp!=begin or curve[0].equity!=config.initial_equity or curve[-1].timestamp!=end-1:
        raise ArithmeticError("Fresh-account evaluation window does not reconcile")
    result.equity=curve; result.start_time=begin; result.bars_per_symbol=(end-begin)//STEP
    result.decisions=[d for d in result.decisions if d.timestamp>=begin]
    result.metrics=metrics(result.trades,curve,config.initial_equity)
    result.no_trade_metrics=metrics([],[],config.initial_equity)
    # Frozen max_positions=1 means occupied intervals are disjoint.
    result.metrics["exposure_time_pct"]=sum((Decimal(t.exit_time+1-t.entry_time) for t in result.trades),Decimal(0))/(end-begin)*100
    gaps=[{"symbol":t.symbol,"entry_time":t.entry_time,"exit_time":t.exit_time,"gap_timestamp":gap}
          for t in result.trades for gap in data.funding_gaps[t.symbol] if t.entry_time<gap<=t.exit_time]
    summary={"metrics":result.metrics,"policy":policy,"scenario":"doubled_fees_and_slippage" if doubled_costs else "default",
             "fold":fold,"begin":begin,"end_exclusive":end,"initial_equity":config.initial_equity,
             "funding_gap_exposures":gaps,"economic_data_quality":"INSUFFICIENT" if gaps else "No detected gap exposure; completeness not guaranteed",
             "entry_days":len({t.entry_time//86_400_000 for t in result.trades}),
             "economic_sample_gate":"SUFFICIENT" if len(result.trades)>=50 and len({t.entry_time//86_400_000 for t in result.trades})>=10 else "INSUFFICIENT",
             "sample_gate_note":"50 trades / 10 entry days is future promotion minimum, shown diagnostically only",
             "average_duration_minutes":sum(t.exit_time-t.entry_time for t in result.trades)/len(result.trades)/60_000 if result.trades else None,
             "long_trades":sum(t.side=="LONG" for t in result.trades),"short_trades":sum(t.side=="SHORT" for t in result.trades),
             "exit_reasons":dict(Counter(t.exit_reason for t in result.trades)),
             "admission_and_risk_rejections":dict(Counter(d.reason for d in result.decisions if d.action=="REJECTED")),
             "realized_budget_overruns":[{"symbol":t.symbol,"signal_time":t.signal_time,"net_pnl":t.net_pnl,
                 "risk_budget":t.risk_budget,"funding_cost":t.funding_cost} for t in result.trades if t.net_pnl < -t.risk_budget-Decimal("1e-12")],
             "risk_evidence":"NOT CLEARED","config":{n:getattr(config,n) for n in config.__dataclass_fields__}}
    return result,summary


def economic_gates(ml,baseline,stress):
    m=ml["metrics"]; b=baseline["metrics"]
    return {"profitable_after_costs":"PASS" if m["net_pnl"]>0 else "FAIL",
            "beats_baseline":"PASS" if m["net_pnl"]>b["net_pnl"] else "FAIL",
            "beats_no_trade":"PASS" if m["net_pnl"]>0 else "FAIL",
            "profit_factor_at_least_1_1":"PASS" if m["profit_factor"] is not None and m["profit_factor"]>=Decimal("1.1") else "FAIL" if m["trades"] else "INSUFFICIENT",
            "drawdown_at_most_10pct":"PASS" if m["maximum_drawdown_pct"]<=10 else "FAIL",
            "doubled_costs_positive":"PASS" if stress["metrics"]["net_pnl"]>0 else "FAIL",
            "economic_sample":ml["economic_sample_gate"],
            "funding_completeness":"INSUFFICIENT" if ml["funding_gap_exposures"] or stress["funding_gap_exposures"] else "No detected gap exposure",
            "risk_clearance":"NOT CLEARED", "scope":"Development diagnostics, not selection-validation acceptance"}
