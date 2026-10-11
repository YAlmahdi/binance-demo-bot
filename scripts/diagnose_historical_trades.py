"""Read-only journal diagnostics. Never runs a strategy, execution client or optimizer."""
from __future__ import annotations
import csv
from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
D = Decimal
ZERO = D(0)
DAY = 86_400_000
STEP = 300_000
FINANCIAL = ('quantity','entry_reference','entry_price','exit_reference','exit_price','stop_price','target_price','risk_budget','planned_loss','margin','gross_pnl','execution_price_pnl','fees','slippage_cost','funding_cost','net_pnl')


def offline_guard(root):
    """Deny networking and credential-file access before reading any research inputs."""
    def audit(event,args):
        if event in ('socket.connect','socket.getaddrinfo','urllib.Request'):
            raise RuntimeError('Diagnostics prohibit all network access')
        if event == 'open' and args and isinstance(args[0],(str,bytes)):
            name = Path(os.fsdecode(args[0])).name.lower()
            if name.startswith('.env') or name.endswith(('.pem','.key','.p12','.pfx','.keystore')):
                raise RuntimeError('Diagnostics prohibit credential-file access')
        if event == 'import' and args[0] in ('demo_futures.config','demo_futures.client','demo_futures.cli','demo_futures.collector'):
            raise RuntimeError('Authenticated client imports prohibited in diagnostics')
    sys.addaudithook(audit)


def utc(timestamp):
    return datetime.fromtimestamp(timestamp/1000,timezone.utc).isoformat()


def parse_trade(row):
    out=dict(row)
    for key in FINANCIAL: out[key]=D(row[key])
    for key in ('signal_time','entry_time','exit_time','funding_mark_fallbacks','uncertain_funding_credits_skipped'):
        out[key]=int(row[key])
    if any(not out[k].is_finite() for k in FINANCIAL): raise ValueError('Nonfinite journal number')
    if out['side'] not in ('LONG','SHORT') or out['quantity']<=0 or out['risk_budget']<=0:
        raise ValueError('Invalid trade side, quantity or risk budget')
    if out['signal_time']>=out['entry_time'] or out['entry_time']>out['exit_time']:
        raise ValueError('Invalid trade chronology')
    for actual,expected in [(out['execution_price_pnl'],out['gross_pnl']-out['slippage_cost']),
                            (out['net_pnl'],out['execution_price_pnl']-out['fees']-out['funding_cost'])]:
        if abs(actual-expected)>D('1e-12'): raise ArithmeticError('Trade accounting mismatch')
    return out


def summarize(rows,key='net_pnl'):
    values=[r[key] for r in rows]
    wins=[v for v in values if v>0]
    losses=[v for v in values if v<0]
    negative=-sum(losses,ZERO)
    total=sum(values,ZERO)
    return {'trades':len(rows),'wins':len(wins),'losses':len(losses),'breakeven':len(rows)-len(wins)-len(losses),
            'pnl':total,'win_rate_pct':D(len(wins))*100/len(rows) if rows else None,
            'profit_factor':sum(wins,ZERO)/negative if negative else None,
            'average_trade':total/len(rows) if rows else None,
            'average_winner':sum(wins,ZERO)/len(wins) if wins else None,
            'average_loser':sum(losses,ZERO)/len(losses) if losses else None,
            'winning_pnl':sum(wins,ZERO),'losing_pnl':sum(losses,ZERO),
            'gross_pnl':sum((r['gross_pnl'] for r in rows),ZERO),
            'fees':sum((r['fees'] for r in rows),ZERO),
            'slippage_cost':sum((r['slippage_cost'] for r in rows),ZERO),
            'funding_cost':sum((r['funding_cost'] for r in rows),ZERO),
            'average_net_risk_units':sum((r['net_pnl']/r['risk_budget'] for r in rows),ZERO)/len(rows) if rows else None}


def group_summary(rows,key):
    groups=defaultdict(list)
    for row in rows: groups[row[key]].append(row)
    return {name:summarize(values) for name,values in sorted(groups.items())}


def cost_attribution(rows,scale):
    """Fixed original entries/sizes/exits/funding: arithmetic only, never an engine rerun."""
    scale=D(str(scale))
    if scale<0: raise ValueError('Cost scale cannot be negative')
    return sum((r['gross_pnl']-scale*(r['fees']+r['slippage_cost'])-r['funding_cost'] for r in rows),ZERO)


def entry_conditions(candles,features,index):
    """Only the signal candle and prior candles; descriptive bins are not trading rules."""
    if index<24 or features[index].atr14 is None: raise ValueError('Insufficient causal history')
    changes=[abs(candles[i].close-candles[i-1].close) for i in range(index-23,index+1)]
    path=sum(changes)
    efficiency=abs(candles[index].close-candles[index-24].close)/path if path else 0.0
    volatility=features[index].atr14/candles[index].close*100
    trend='choppy_ER_le_0.20' if efficiency<=.20 else ('mixed_ER_le_0.50' if efficiency<=.50 else 'directional_ER_gt_0.50')
    vol='low_ATR_pct_lt_0.10' if volatility<.10 else ('moderate_ATR_pct_lt_0.30' if volatility<.30 else 'high_ATR_pct_ge_0.30')
    return {'trend_condition':trend,'volatility_condition':vol,'signal_efficiency_ratio_24':efficiency,
            'signal_atr_pct':volatility,'signal_relative_volume':features[index].relative_volume}


def exit_family(reason):
    if reason.startswith('stop_'): return 'stop_loss'
    if reason in ('take_profit','target_gap_no_improvement'): return 'take_profit'
    if reason.startswith('daily_loss_'): return 'daily_halt'
    if reason=='holding_time_limit': return 'holding_limit'
    return reason


def drawdown(points,initial):
    peak=D(initial); largest=ZERO
    for value in points:
        peak=max(peak,value)
        if peak>0: largest=max(largest,(peak-value)/peak*100)
    return largest


def number(value):
    return 'undefined' if value is None else (f'{value:.2f}' if isinstance(value,(D,float)) else str(value))


def table(groups):
    lines=['| Group | Trades | Raw price PnL | Net PnL | Win % | PF | Avg win | Avg loss | Avg net / risk budget |',
           '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for key,row in groups.items():
        lines.append('| '+' | '.join(number(v) for v in (key,row['trades'],row['gross_pnl'],row['pnl'],row['win_rate_pct'],row['profit_factor'],row['average_winner'],row['average_loser'],row['average_net_risk_units']))+' |')
    return lines


def main():
    offline_guard(ROOT)
    sys.dont_write_bytecode=True
    sys.path.insert(0,str(ROOT/'src'))
    from demo_futures.data import Candle,validate_candles
    from demo_futures.indicators import build_features
    from demo_futures.history_audit import audit_candles,funding_audit
    from demo_futures.risk import BacktestConfig,ContractSpec,fill_price
    base=ROOT/'reports'/'historical-90d'
    output=ROOT/'reports'/'historical-90d-diagnostics'
    inputs=[ROOT/'data'/'market.sqlite3',ROOT/'data'/'research-90d.sqlite3']
    inputs += [base/'default'/n for n in ('report.json','trades.csv','decisions.csv','equity.csv')]
    inputs += [base/'doubled-costs'/'report.json',base/'evaluation.json',base/'collection.json']
    inputs += [ROOT/'src'/'demo_futures'/n for n in ('strategy.py','indicators.py','risk.py','backtest.py','reporting.py')]
    before={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    collection=json.loads((base/'collection.json').read_text())
    if before['data/research-90d.sqlite3']!=collection['database_sha256'] or before['data/market.sqlite3']!=collection['original_database_sha256']:
        raise ValueError('Historical database hash differs from the frozen snapshot')
    for name,value in collection['frozen_source_hashes'].items():
        if before['src/demo_futures/'+name]!=value: raise ValueError('Frozen source differs: '+name)
    report=json.loads((base/'default'/'report.json').read_text())
    stress=json.loads((base/'doubled-costs'/'report.json').read_text())
    evaluation=json.loads((base/'evaluation.json').read_text())
    with (base/'default'/'trades.csv').open(newline='',encoding='utf-8') as stream:
        trades=[parse_trade(row) for row in csv.DictReader(stream)]
    if len(trades)!=851: raise ValueError('Expected exactly 851 original baseline trades')
    candles={}; features={}; indices={}; audit={'candles':{},'funding':{}}
    dbpath=ROOT/'data'/'research-90d.sqlite3'
    with closing(sqlite3.connect(dbpath.as_uri()+'?mode=ro&immutable=1',uri=True)) as db:
        db.execute('PRAGMA query_only=ON')
        audit['integrity']=db.execute('PRAGMA integrity_check').fetchone()[0]
        if audit['integrity']!='ok': raise ValueError('Database integrity failed')
        for symbol in ('BTCUSDT','ETHUSDT'):
            records=db.execute('SELECT open_time,open,high,low,close,volume,close_time,quote_volume,trades FROM candles WHERE symbol=? AND interval=? ORDER BY open_time',(symbol,'5m')).fetchall()
            candles[symbol]=validate_candles([Candle(*row) for row in records],'5m')
            if len(records)!=25920: raise ValueError('Unexpected historical coverage')
            indices[symbol]={c.close_time:i for i,c in enumerate(candles[symbol])}
            features[symbol]=build_features(candles[symbol])
            audit['candles'][symbol]=audit_candles(candles[symbol],'5m')
            events=db.execute('SELECT timestamp,rate,mark_price FROM funding WHERE symbol=? ORDER BY timestamp',(symbol,)).fetchall()
            audit['funding'][symbol]=funding_audit(events,candles[symbol][0].open_time,candles[symbol][-1].close_time+1)
    ambiguity=[]; daily_target=[]; windows_large=[]; gap_losses=[]
    config=BacktestConfig(**report['configuration']['risk_and_costs'])
    specs={key:ContractSpec(**value) for key,value in report['configuration']['offline_contract_assumptions'].items()}
    for index,row in enumerate(trades,1):
        symbol=row['symbol']; bars=candles[symbol]
        sig_index=indices[symbol][row['signal_time']]
        if row['entry_time']!=bars[sig_index].close_time+1: raise ValueError('Not a next-candle entry')
        if row['planned_loss']>row['risk_budget']: raise ValueError('Planned risk exceeded budget')
        row.update(entry_conditions(bars,features[symbol],sig_index))
        row['symbol_side']=symbol+'/'+row['side']; row['exit_family']=exit_family(row['exit_reason'])
        row['trade_number']=index; row['entry_utc']=utc(row['entry_time']); row['exit_utc']=utc(row['exit_time'])
        row['duration_minutes']=D(row['exit_time']-row['entry_time'])/60000
        end_index=(row['exit_time']-bars[0].open_time)//STEP
        bar=bars[end_index]; long=row['side']=='LONG'
        stop_hit=D(str(bar.low))<=row['stop_price'] if long else D(str(bar.high))>=row['stop_price']
        target_hit=D(str(bar.high))>=row['target_price'] if long else D(str(bar.low))<=row['target_price']
        row['exit_bar_stop_touched']=stop_hit; row['exit_bar_target_touched']=target_hit
        alternative=fill_price(row['target_price'],not long,specs[symbol],config)
        alt_net=(1 if long else -1)*row['quantity']*(alternative-row['entry_price'])-row['quantity']*row['entry_price']*config.fee_rate-row['quantity']*alternative*config.fee_rate-row['funding_cost']
        evidence={'trade_number':index,'original_net_pnl':row['net_pnl'],'same_trade_target_net_pnl':alt_net,'mechanical_net_difference':alt_net-row['net_pnl']}
        if row['exit_reason']=='stop_loss_both_touched': ambiguity.append(evidence)
        if row['exit_reason']=='daily_loss_intrabar_conservative' and target_hit and not stop_hit: daily_target.append(evidence)
        if row['exit_reason']=='stop_gap':
            sign=1 if long else -1
            gap_losses.append({'trade_number':index,'extra_reference_loss_vs_stop':sign*row['quantity']*(row['stop_price']-row['exit_reference'])})
        left=(row['entry_time']-bars[0].open_time)//STEP
        if any((c.high-c.low)/c.open>.05 for c in bars[left:end_index+1]): windows_large.append(index)
    stages={}
    for label,key in [('raw_reference_prices','gross_pnl'),('after_slippage_before_fees_funding','execution_price_pnl'),('after_fees_slippage_before_funding','before_funding'),('after_all_recorded_costs','net_pnl')]:
        if key=='before_funding':
            for row in trades: row[key]=row['execution_price_pnl']-row['fees']
        stages[label]=summarize(trades,key)
    for key in ('gross_pnl','execution_price_pnl','fees','slippage_cost','funding_cost','net_pnl'):
        if abs(sum((r[key] for r in trades),ZERO)-D(report['strategy'][key]))>D('1e-12'):
            raise ArithmeticError('Aggregate report mismatch: '+key)
    groups={key:group_summary(trades,key) for key in ('side','symbol','symbol_side','trend_condition','volatility_condition','exit_family','exit_reason')}
    entries_by_day=Counter(r['entry_utc'][:10] for r in trades)
    with (base/'default'/'decisions.csv').open(newline='',encoding='utf-8') as stream:
        decisions=list(csv.DictReader(stream))
    actions=Counter(r['action'] for r in decisions)
    rejected=Counter(r['reason'] for r in decisions if r['action']=='REJECTED')
    if actions['ENTERED']!=len(trades): raise ArithmeticError('Entry decisions do not reconcile')
    with (base/'default'/'equity.csv').open(newline='',encoding='utf-8') as stream:
        points=[{'timestamp':int(r['timestamp']),'equity':D(r['equity']),'kind':r['kind']} for r in csv.DictReader(stream)]
    days=defaultdict(list)
    for p in points: days[utc(p['timestamp'])[:10]].append(p)
    daily_losses={}
    for day,values in days.items():
        anchor=next(v['equity'] for v in values if v['kind']=='bar_open')
        daily_losses[day]=(anchor-min(v['equity'] for v in values))/anchor*100 if anchor>0 else None
    duration_days=D(str((candles['BTCUSDT'][-1].close_time+1-candles['BTCUSDT'][0].open_time)/DAY))
    cost=sum((r['fees']+r['slippage_cost'] for r in trades),ZERO)
    net=stages['after_all_recorded_costs']['pnl']
    sensitivity={'fixed_trade_cost_attribution':[{'fee_slippage_scale':scale,'net_pnl_with_original_funding':cost_attribution(trades,scale)} for scale in (0,.5,1,2)],
        'saved_doubled_cost_full_run':stress['strategy'],'saved_default_no_trade':report['no_trade'],
        'both_touched_stop_exits':{'count':len(ambiguity),'mechanical_target_first_delta':sum((r['mechanical_net_difference'] for r in ambiguity),ZERO),'trades':ambiguity},
        'daily_halt_overrides_touched_target':{'count':len(daily_target),'mechanical_target_priority_delta':sum((r['mechanical_net_difference'] for r in daily_target),ZERO),'trades':daily_target},
        'stop_gap_extra_reference_loss':sum((r['extra_reference_loss_vs_stop'] for r in gap_losses),ZERO),'stop_gap_trades':gap_losses,
        'bar_close_only_drawdown_pct_same_run':drawdown([p['equity'] for p in points if p['kind'] in ('bar_close','final_realized_equity')],10000),
        'reported_conservative_drawdown_pct':D(report['strategy']['maximum_drawdown_pct']),
        'funding_mark_fallbacks':sum(r['funding_mark_fallbacks'] for r in trades),
        'uncertain_funding_credits_skipped':sum(r['uncertain_funding_credits_skipped'] for r in trades),
        'potential_missing_funding_exposure':evaluation['scenarios']['default']['potential_missing_funding_exposure'],
        'holding_windows_including_over_5pct_range_bar':windows_large,
        'realized_loss_over_planned_budget':[{'trade_number':r['trade_number'],'net_pnl':r['net_pnl'],'risk_budget':r['risk_budget']} for r in trades if -r['net_pnl']>r['risk_budget']+D('1e-12')]}
    frequency={'coverage_days':duration_days,'calendar_days_touched':len(days),'days_with_entries':len(entries_by_day),
        'entries_per_24h':D(len(trades))/duration_days,'entries_per_active_day':D(len(trades))/len(entries_by_day),
        'maximum_entries_in_utc_day':max(entries_by_day.values()),'entries_by_day':dict(sorted(entries_by_day.items())),
        'average_duration_minutes':sum((r['duration_minutes'] for r in trades),ZERO)/len(trades),
        'one_bar_trades':sum(r['exit_time']-r['entry_time']<STEP for r in trades),
        'exposure_time_pct':D(report['strategy']['exposure_time_pct']),'two_sided_notional_turnover':D(report['strategy']['turnover']),
        'turnover_divided_by_initial_equity':D(report['strategy']['turnover'])/10000,
        'average_fee_slippage_cost_per_trade':cost/len(trades),'fees_slippage_pct_initial_equity':cost/100,
        'fee_slippage_share_of_observed_net_loss_pct':cost/-net*100,
        'gross_winners_that_become_net_losers':sum(r['gross_pnl']>0 and r['net_pnl']<0 for r in trades),
        'signal_and_action_counts':dict(actions),'risk_rejections_by_reason':dict(rejected),
        'utc_days_reaching_conservative_2pct_threshold':sum(v is not None and v>=2 for v in daily_losses.values()),
        'maximum_conservative_intraday_loss_pct':max(v for v in daily_losses.values() if v is not None),
        'daily_conservative_loss_pct':daily_losses}
    metadata={'scope':'Read-only diagnosis of existing 851 default trades; no backtest rerun or optimization',
        'approved_phase':'research and diagnostics only','network_requests':0,'credential_files_read':0,'orders':0,
        'condition_definitions':{'trend':'At signal close, absolute 24-bar close change / sum of 24 absolute close changes; <=0.20 choppy, (0.20,0.50] mixed, >0.50 directional',
                                 'volatility':'At signal close ATR14/close*100; <0.10 low, [0.10,0.30) moderate, >=0.30 high'},
        'grouping_caveat':'Descriptive analyst bins, chosen without tuning strategy rules; no independent predictive or causal evidence. Symbol sizes differ and equity compounds. Average net/risk-budget helps compare scale.',
        'cost_caveat':'Fixed-size/fill accounting scenarios retain original funding, quantities, trades, risk state and exit references. They are not alternative portfolio backtests.',
        'sensitivity_caveat':'Target-first and daily-target deltas replace one recorded exit mechanically; subsequent equity, sizing, halts and funding are not rerun. These are illustrations, not achievable PnL bounds.',
        'source_and_input_sha256_before':before}
    payload={'metadata':metadata,'coverage_audit':audit,'cost_stages':stages,'groups':groups,'frequency':frequency,'assumption_sensitivity':sensitivity}
    after={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    if before!=after: raise RuntimeError('Frozen input changed during diagnostics')
    payload['metadata']['source_and_input_hashes_unchanged']=True
    lines=['# Read-only diagnosis of 851 historical baseline trades','','Current approval: research and diagnostics only. No network, credentials, orders, model training or new execution. Trading rules, risk parameters and frozen inputs were not changed.','',
        '## Evidence and method','','Existing default trade, decision and equity CSVs; default/stress report JSON; saved research SQLite opened mode=ro, immutable=1, query_only. Database integrity, contiguous candles, known frozen hashes, every trade accounting identity, next-candle timing, planned budgets and aggregate totals are checked. No simulation is rerun. See diagnostic.json for full precision, evidence hashes and per-group costs.','',
        'The dataset is 2026-07-11 06:50 UTC to 2026-10-09 06:50 UTC exclusive: 90 days, 25,920 five-minute candles and 268 available funding events per symbol. Funding gaps, Demo realism and fill limitations described below still apply.','',
        '## Performance before and after costs','','All amounts are USDT. Raw PnL uses original reference entries/exits and original quantities; it does not recreate a zero-cost portfolio.','',
        '| Stage | PnL | Winners | Losers | Win % | Profit factor |','|---|---:|---:|---:|---:|---:|']
    for label,r in stages.items(): lines.append('| '+' | '.join(number(v) for v in (label,r['pnl'],r['wins'],r['losses'],r['win_rate_pct'],r['profit_factor']))+' |')
    lines += ['',f"Fees: {number(report['strategy']['fees'] if isinstance(report['strategy']['fees'],D) else D(report['strategy']['fees']))}; slippage/adverse tick rounding: {number(D(report['strategy']['slippage_cost']))}; net recorded funding cost: {number(D(report['strategy']['funding_cost']))} (negative means a receipt). Raw price PnL is already negative; costs magnify rather than create the entire weakness.",'']
    lines += ['## Main diagnostic findings','',
        f"Both directions and both symbols lose after costs. LONG loses {number(groups['side']['LONG']['pnl'])}, SHORT {number(groups['side']['SHORT']['pnl'])}; BTC {number(groups['symbol']['BTCUSDT']['pnl'])}, ETH {number(groups['symbol']['ETHUSDT']['pnl'])}. Dollar losses reflect unequal samples and changing position sizes.",
        f"Low-volatility trades have raw price PnL {number(groups['volatility_condition']['low_ATR_pct_lt_0.10']['gross_pnl'])}, but net PnL {number(groups['volatility_condition']['low_ATR_pct_lt_0.10']['pnl'])}. Narrow price moves can be small relative to fee/slippage burden. This descriptive bin is not a recommended new filter.",
        f"Take-profit exits include {groups['exit_family']['take_profit']['losses']} net losers out of {groups['exit_family']['take_profit']['trades']}: hitting the target does not guarantee a profit after costs.",
        'All observed trend and volatility buckets lose net. The directional group has only 24 trades, so its slightly positive raw result is too small a sample for an edge claim.','']
    for key,title in [('side','LONG versus SHORT'),('symbol','By symbol'),('symbol_side','By symbol and direction'),('trend_condition','By signal-time trend condition'),('volatility_condition','By signal-time volatility'),('exit_family','By exit family'),('exit_reason','Exact recorded exit reasons')]:
        lines += ['## '+title,'']+table(groups[key])+['']
    lines += ['Condition definitions: '+metadata['condition_definitions']['trend']+'. '+metadata['condition_definitions']['volatility']+'.',
        'These are descriptive bins on prior/signal candles, not optimized trading thresholds. Full-series indicator calculation uses the existing causal implementation; each trade only reads the signal-index feature. Groups have unequal sample sizes, different position sizes and changing equity; correlations do not prove a cause. All bucket assignments partition the same 851 trades.','',
        '## Average outcomes and turnover','',
        f"Net average winning trade: {number(stages['after_all_recorded_costs']['average_winner'])}; average losing trade: {number(stages['after_all_recorded_costs']['average_loser'])}; average all trades: {number(stages['after_all_recorded_costs']['average_trade'])}.",
        f"{frequency['gross_winners_that_become_net_losers']} raw-price winners become net losers. Mean fee/slippage cost is {number(frequency['average_fee_slippage_cost_per_trade'])} per trade.",
        f"851 entries over 90 days: {number(frequency['entries_per_24h'])} per 24h; {len(entries_by_day)} entry-active UTC days; maximum {frequency['maximum_entries_in_utc_day']} entries in one day. The window touches {len(days)} UTC calendar dates, with partial first/last days.",
        f"Average recorded duration {number(frequency['average_duration_minutes'])} minutes; {frequency['one_bar_trades']} trades close in their entry bar; exposure {number(frequency['exposure_time_pct'])}%. Intrabar exit timestamps are approximate bar-close assignments.",
        f"Two-sided turnover {number(frequency['two_sided_notional_turnover'])}, or {number(frequency['turnover_divided_by_initial_equity'])} times initial capital. Fee/slippage cost equals {number(frequency['fees_slippage_pct_initial_equity'])}% of initial equity and {number(frequency['fee_slippage_share_of_observed_net_loss_pct'])}% of the observed net loss. This is accounting attribution, not proof that reducing frequency would fix the edge.",
        'Repeated qualifying signals are possible without a cooldown; one-position/pyramiding rules reject conflicting entries. Existing daily halts also suppress trading. Frequency is expensive relative to this sample\'s weak raw price edge; there is no universal trade-count limit that makes turnover excessive.',
        'Recorded risk rejections: '+json.dumps(dict(rejected),sort_keys=True)+'.',
        f"{frequency['utc_days_reaching_conservative_2pct_threshold']} UTC days reach the 2% threshold on the saved conservative curve; worst conservative daily excursion {number(frequency['maximum_conservative_intraday_loss_pct'])}%. This is not a guaranteed realized daily-loss cap.",'',
        '## Sensitivity to known assumptions','',
        '| Original trades: fee/slippage scale | Net PnL with original recorded funding |','|---|---:|']
    for r in sensitivity['fixed_trade_cost_attribution']: lines.append(f"| {r['fee_slippage_scale']} | {number(r['net_pnl_with_original_funding'])} |")
    lines += ['',metadata['cost_caveat'],
        f"The previously saved full doubled-cost run has {stress['strategy']['trades']} trades and {number(D(stress['strategy']['net_pnl']))} net PnL, versus 851/{number(net)} at default costs. It is not paired trade-by-trade: higher costs change sizing, equity, halts and accepted trades. NO TRADE stays at 10,000 with zero PnL and drawdown.",
        f"Both-stop-and-target exits: {len(ambiguity)}; replacing those exits mechanically with target fills changes journal net by +{number(sensitivity['both_touched_stop_exits']['mechanical_target_first_delta'])}. Stop-first is intentionally conservative.",
        f"Daily-halt exits whose recorded exit bar touches a target without touching the stop: {len(daily_target)}; a mechanical target-priority substitution changes net by +{number(sensitivity['daily_halt_overrides_touched_target']['mechanical_target_priority_delta'])}. The bar cannot reveal whether target or daily threshold occurred first.",
        metadata['sensitivity_caveat'],
        f"Stop-gap exits: {len(gap_losses)}; extra reference-price loss beyond planned stop {number(sensitivity['stop_gap_extra_reference_loss'])}. {len(sensitivity['realized_loss_over_planned_budget'])} trades have net loss above their planned budget. Budgets are planned exposure constraints, not realized-loss guarantees.",
        f"Reported adverse-intrabar drawdown {number(sensitivity['reported_conservative_drawdown_pct'])}% versus {number(sensitivity['bar_close_only_drawdown_pct_same_run'])}% when sampling only saved closes. Same original run; daily rules have not been rerun using closes.",
        f"{len(windows_large)} holding windows include a >5% range bar. This flags Demo-data realism/large-range exposure, not proof the entire range happened before an intrabar exit.",
        f"Funding mark fallbacks: {sensitivity['funding_mark_fallbacks']}; uncertain funding credits skipped: {sensitivity['uncertain_funding_credits_skipped']}. Available funding has potential modal-schedule gaps at August 17 and September 1 08:00 UTC; one default trade overlaps the August gap. Unknown rates/signs remain unknown. No missing rates were fabricated.",'',
        '## Interpretation and limits','',
        'Verified on the fixed saved journal: baseline net performance is negative; cost stages, directions, symbols, exits, descriptive conditions and counts are reconciled. Tests cover synthetic implementation behavior, not future profitability. Status and test scope are in docs/PROJECT_STATUS.md and this folder\'s tests.json.',
        'This is the same already-reviewed sample, not a new untouched holdout. No tuning, significance certification, causal explanation, ML or execution promotion is performed. Short descriptive buckets do not establish a tradable regime. Fixed fees/slippage/contract filters are assumptions; tick rounding is included in slippage. Missing funding and unknown intrabar ordering prevent exact exchange realism. Liquidity, latency, liquidation/maintenance tiers, outages, pending orders and restartable account risk are not modeled.',
        'All source/data/journal hashes match before and after. Stop here and await approval.']
    output.mkdir(parents=True,exist_ok=True)
    (output/'diagnostic.json').write_text(json.dumps(payload,indent=2,default=str,allow_nan=False)+'\n',encoding='utf-8')
    (output/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    with (output/'trade-attribution.csv').open('w',newline='',encoding='utf-8') as stream:
        fields=['trade_number','symbol','side','entry_utc','exit_utc','trend_condition','volatility_condition','signal_efficiency_ratio_24','signal_atr_pct','signal_relative_volume','gross_pnl','execution_price_pnl','fees','slippage_cost','funding_cost','net_pnl','risk_budget','exit_reason','exit_family','duration_minutes','exit_bar_stop_touched','exit_bar_target_touched']
        writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore'); writer.writeheader(); writer.writerows(trades)
    print(json.dumps({'trades':851,'net_pnl':str(net),'output':str(output),'frozen_inputs_unchanged':True,'network_requests':0,'orders':0}))


if __name__=='__main__': main()
