"""Hand-calculated journal attribution and causal descriptive-bin regressions."""
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.diagnose_historical_trades import parse_trade,summarize,group_summary,cost_attribution,entry_conditions,exit_family,drawdown
from demo_futures.data import Candle
from demo_futures.indicators import build_features


def row(gross='10',side='LONG'):
    from scripts.diagnose_historical_trades import FINANCIAL
    result={key:'0' for key in FINANCIAL}
    result.update(symbol='BTCUSDT',side=side,quantity='1',risk_budget='50',gross_pnl=gross,
                  execution_price_pnl=str(D(gross)-D('.4')),fees='.1',slippage_cost='.4',funding_cost='-.5',
                  net_pnl=gross,signal_time='299999',entry_time='300000',exit_time='599999',
                  funding_mark_fallbacks='0',uncertain_funding_credits_skipped='0',exit_reason='stop_loss')
    return parse_trade(result)


class TradeDiagnosticTests(unittest.TestCase):
    def test_signed_funding_and_costs_reconcile(self):
        trade=row()
        self.assertEqual(trade['execution_price_pnl'],D('9.6'))
        self.assertEqual(trade['net_pnl'],D('10'))
        self.assertEqual(cost_attribution([trade],0),D('10.5'))
        self.assertEqual(cost_attribution([trade],2),D('9.5'))

    def test_inconsistent_accounting_rejected(self):
        trade=row(); trade={k:str(v) for k,v in trade.items()}; trade['net_pnl']='11'
        with self.assertRaises(ArithmeticError): parse_trade(trade)

    def test_invalid_timing_and_quantity_rejected(self):
        for key,value in [('entry_time','299999'),('quantity','0'),('risk_budget','0')]:
            trade={k:str(v) for k,v in row().items()}; trade[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError): parse_trade(trade)

    def test_average_wins_losses_and_risk_units(self):
        stats=summarize([row('10'),row('-20','SHORT')])
        self.assertEqual(stats['pnl'],D('-10'))
        self.assertEqual(stats['average_winner'],D(10))
        self.assertEqual(stats['average_loser'],D(-20))
        self.assertEqual(stats['win_rate_pct'],D(50))
        self.assertEqual(stats['profit_factor'],D('.5'))
        self.assertEqual(stats['average_net_risk_units'],D('-.1'))

    def test_group_counts_and_net_partition(self):
        trades=[row('10'),row('-20','SHORT'),row('5')]
        groups=group_summary(trades,'side')
        self.assertEqual(sum(r['trades'] for r in groups.values()),3)
        self.assertEqual(sum(r['pnl'] for r in groups.values()),D(-5))

    def test_empty_and_zero_outcomes_not_reported_as_wins(self):
        self.assertIsNone(summarize([])['win_rate_pct'])
        self.assertIsNone(summarize([])['profit_factor'])
        self.assertEqual(summarize([row('0')])['breakeven'],1)

    def test_negative_cost_scale_rejected(self):
        with self.assertRaises(ValueError): cost_attribution([row()],-1)

    def test_condition_bins_boundary_and_flat_path(self):
        bars=[SimpleNamespace(close=100) for _ in range(30)]
        features=[SimpleNamespace(atr14=.1,relative_volume=1) for _ in bars]
        info=entry_conditions(bars,features,29)
        self.assertEqual(info['trend_condition'],'choppy_ER_le_0.20')
        self.assertEqual(info['volatility_condition'],'moderate_ATR_pct_lt_0.30')
        features[29].atr14=.3
        self.assertEqual(entry_conditions(bars,features,29)['volatility_condition'],'high_ATR_pct_ge_0.30')
        features[29].atr14=.099
        self.assertEqual(entry_conditions(bars,features,29)['volatility_condition'],'low_ATR_pct_lt_0.10')

    def test_condition_features_unchanged_when_future_is_perturbed(self):
        bars=[Candle(i*300000,100+i,102+i,99+i,101+i,10,(i+1)*300000-1,1000,10) for i in range(260)]
        original=entry_conditions(bars,build_features(bars),220)
        later=bars[:221]+[Candle(i*300000,1000,2000,100,1500,5000,(i+1)*300000-1,100000,10) for i in range(221,260)]
        self.assertEqual(original,entry_conditions(later,build_features(later),220))
        self.assertEqual(original['trend_condition'],'directional_ER_gt_0.50')

    def test_exit_reason_families_keep_gap_and_halt_distinction(self):
        for reason,family in [('stop_gap','stop_loss'),('stop_loss_both_touched','stop_loss'),('target_gap_no_improvement','take_profit'),('holding_time_limit','holding_limit'),('daily_loss_open','daily_halt'),('end_of_data','end_of_data')]:
            self.assertEqual(exit_family(reason),family)

    def test_drawdown_uses_peak_and_recovery(self):
        self.assertEqual(drawdown([D(100),D(120),D(90),D(130)],D(100)),D(25))

    def test_runtime_guard_rejects_network_and_credential_audit_events(self):
        script=Path(__file__).resolve().parents[1]/'scripts'/'diagnose_historical_trades.py'
        code="""import runpy,sys
from pathlib import Path
module=runpy.run_path(sys.argv[1]);module['offline_guard'](Path('.'))
checks=[lambda:sys.audit('socket.connect',None,('127.0.0.1',443)),lambda:sys.audit('socket.getaddrinfo','example.com',443,0,0,0),lambda:sys.audit('urllib.Request','https://demo-fapi.binance.com/fapi/v1/time',None,{},'GET'),lambda:sys.audit('open','unopened/.env','r',0),lambda:sys.audit('import','demo_futures.config',None,None,None,None)]
for check in checks:
 try:check()
 except RuntimeError:continue
 raise AssertionError('Diagnostic guard failed')
print('guard passed')
"""
        result=subprocess.run([sys.executable,'-B','-c',code,str(script)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('guard passed',result.stdout)
