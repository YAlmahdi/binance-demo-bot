from datetime import datetime,timezone
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys
import unittest

from demo_futures.backtest import Decision,EquityPoint
from demo_futures.research_evaluation import trade_statistics,monthly_statistics,rejection_statistics,funding_gap_exposure


def timestamp(value):
    return int(datetime.fromisoformat(value.replace("Z","+00:00")).timestamp()*1000)


def trade(side="LONG",net=20,entry=0,exit=600000,fees=2,slip=1,funding=3):
    return SimpleNamespace(side=side,net_pnl=D(net),entry_time=entry,exit_time=exit,
        fees=D(fees),slippage_cost=D(slip),funding_cost=D(funding),
        execution_price_pnl=D(net)+D(fees)+D(funding),uncertain_funding_credits_skipped=0,symbol="BTCUSDT")


class ResearchEvaluationTests(unittest.TestCase):
    def test_long_short_durations_and_cost_decomposition_hand_calculated(self):
        trades=[trade(),trade("SHORT",-10,entry=0,exit=1200000,funding=-1)]
        stats=trade_statistics(trades)
        self.assertEqual((stats["trades"],stats["long_trades"],stats["short_trades"]),(2,1,1))
        self.assertEqual(stats["average_trade_duration_minutes"],15)
        self.assertEqual(stats["net_pnl"],10)
        self.assertEqual(stats["pnl_after_fees_slippage_before_funding"],12)
        self.assertEqual(stats["win_rate_pct"],50)
        self.assertEqual(stats["profit_factor"],2)

    def test_no_trade_metrics_stay_undefined(self):
        stats=trade_statistics([])
        self.assertEqual(stats["net_pnl"],0)
        for key in ("average_trade_duration_minutes","win_rate_pct","profit_factor"):
            self.assertIsNone(stats[key])

    def test_monthly_carried_equity_and_exit_attribution_reconcile(self):
        july=timestamp("2026-07-31T23:55:00Z")
        august=timestamp("2026-08-01T00:00:00Z")
        closed=trade(net=30,entry=july,exit=august+299999)
        result=SimpleNamespace(config=SimpleNamespace(initial_equity=D(10000)),trades=[closed],
            equity=[EquityPoint(july,D(10000),"open"),EquityPoint(july+299999,D(10010),"close"),
                    EquityPoint(august,D(10005),"open"),EquityPoint(august+299999,D(10030),"final")])
        rows=monthly_statistics(result)
        self.assertEqual(rows[0]["trades"],0)
        self.assertEqual(rows[0]["marked_equity_change"],10)
        self.assertEqual(rows[1]["marked_equity_start"],10010)
        self.assertEqual(rows[1]["net_pnl"],30)
        self.assertEqual(rows[1]["marked_equity_change"],20)
        self.assertEqual(sum(r["marked_equity_change"] for r in rows),30)
        self.assertGreater(rows[1]["maximum_drawdown_pct"],0)

    def test_risk_rejections_not_confused_with_baseline_no_trade_filters(self):
        decisions=[Decision("BTCUSDT",1,"LONG","REJECTED","position cap"),
                   Decision("ETHUSDT",1,"NO TRADE","NO_TRADE","warm-up"),
                   Decision("ETHUSDT",2,"SHORT","NO_NEXT_BAR","last")]
        stats=rejection_statistics(decisions)
        self.assertEqual(stats["risk_rejections_total"],1)
        self.assertEqual(stats["risk_rejections_by_reason"],{"position cap":1})
        self.assertEqual(stats["baseline_no_trade_by_reason"],{"warm-up":1})
        self.assertEqual(stats["final_bar_unfilled_signals"],1)

    def test_potential_funding_exposure_excludes_entry_boundary_includes_exit(self):
        closed=trade(entry=600000,exit=1200000)
        absent=["1970-01-01T00:10:00+00:00","1970-01-01T00:20:00+00:00","1970-01-01T00:25:00+00:00"]
        audit={"funding":{"BTCUSDT":{"absent_under_modal_schedule_utc":absent}}}
        exposure=funding_gap_exposure(SimpleNamespace(trades=[closed]),audit)
        self.assertEqual(exposure["exposed_trades"],1)
        self.assertEqual(exposure["details"][0]["potential_missing_funding_times_utc"],[absent[1]])

    def test_research_runtime_guard_blocks_secrets_and_authenticated_requests(self):
        script=Path(__file__).resolve().parents[1]/"scripts"/"research_history.py"
        code="""
import runpy,sys
from pathlib import Path
scope=runpy.run_path(sys.argv[1]);scope['guard'](True)
cases=[
 lambda:sys.audit('urllib.Request','https://demo-fapi.binance.com/fapi/v1/time?signature=dummy',None,{},'GET'),
 lambda:sys.audit('urllib.Request','https://demo-fapi.binance.com/fapi/v3/balance',None,{},'GET'),
 lambda:sys.audit('urllib.Request','https://fapi.binance.com/fapi/v1/klines',None,{},'GET'),
 lambda:sys.audit('urllib.Request','https://demo-fapi.binance.com/fapi/v1/klines',None,{'X-MBX-APIKEY':'dummy'},'GET'),
 lambda:sys.audit('urllib.Request','https://demo-fapi.binance.com/fapi/v1/klines',None,{},'POST'),
 lambda:sys.audit('open',str(Path('.env').resolve()),'r',0),
 lambda:sys.audit('import','demo_futures.config',None,None,None,None),
]
for check in cases:
 try:check()
 except RuntimeError:continue
 raise AssertionError('Guard failed')
sys.audit('urllib.Request','https://demo-fapi.binance.com/fapi/v1/time',None,{},'GET')
print('guard cases passed')
"""
        result=subprocess.run([sys.executable,"-c",code,str(script)],capture_output=True,text=True,check=False)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn("guard cases passed",result.stdout)
