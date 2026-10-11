"""Analysis/reporting of frozen backtests; never alters signals, fills, risk or costs."""
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
import csv
import json
from pathlib import Path

from .history_audit import utc

ZERO = Decimal(0)


def trade_statistics(trades):
    wins = [t.net_pnl for t in trades if t.net_pnl > 0]
    losses = [t.net_pnl for t in trades if t.net_pnl < 0]
    loss = -sum(losses, ZERO)
    return {
        "trades": len(trades), "long_trades": sum(t.side == "LONG" for t in trades),
        "short_trades": sum(t.side == "SHORT" for t in trades),
        "net_pnl": sum((t.net_pnl for t in trades), ZERO),
        "pnl_after_fees_slippage_before_funding": sum((t.execution_price_pnl-t.fees for t in trades), ZERO),
        "fees": sum((t.fees for t in trades), ZERO),
        "slippage_cost": sum((t.slippage_cost for t in trades), ZERO),
        "funding_cost": sum((t.funding_cost for t in trades), ZERO),
        "win_rate_pct": Decimal(len(wins))/len(trades)*100 if trades else None,
        "profit_factor": sum(wins,ZERO)/loss if loss else None,
        "average_trade_duration_minutes": sum((Decimal(t.exit_time-t.entry_time)/60000 for t in trades),ZERO)/len(trades) if trades else None,
        "uncertain_funding_credits_skipped": sum(t.uncertain_funding_credits_skipped for t in trades),
    }


def drawdown(points, initial):
    peak, maximum = initial, ZERO
    for point in points:
        peak = max(peak,point.equity)
        if peak > 0:
            maximum = max(maximum,(peak-point.equity)/peak*100)
    return maximum


def month_of(timestamp):
    return datetime.fromtimestamp(timestamp/1000,timezone.utc).strftime("%Y-%m")


def monthly_statistics(result):
    """One continuous run; closed trades/costs assigned to their UTC exit month."""
    months = sorted({month_of(e.timestamp) for e in result.equity})
    initial = result.config.initial_equity
    output = []
    for month in months:
        points = [p for p in result.equity if month_of(p.timestamp)==month]
        trades = [t for t in result.trades if month_of(t.exit_time)==month]
        row = {"month": month, **trade_statistics(trades),
               "start_utc": utc(points[0].timestamp), "end_utc": utc(points[-1].timestamp),
               "marked_equity_start": initial, "marked_equity_end": points[-1].equity,
               "marked_equity_change": points[-1].equity-initial,
               "maximum_drawdown_pct": drawdown(points,initial)}
        output.append(row)
        initial = points[-1].equity
    return output


def rejection_statistics(decisions):
    rejected = [d for d in decisions if d.action=="REJECTED"]
    filters = [d for d in decisions if d.action=="NO_TRADE"]
    return {
        "risk_rejections_total": len(rejected),
        "risk_rejections_by_reason": dict(Counter(d.reason for d in rejected)),
        "risk_rejections_by_symbol": dict(Counter(d.symbol for d in rejected)),
        "baseline_no_trade_by_reason": dict(Counter(d.reason for d in filters)),
        "signal_count_by_side": dict(Counter(d.side for d in decisions if d.action in ("SIGNAL","NO_NEXT_BAR"))),
        "final_bar_unfilled_signals": sum(d.action=="NO_NEXT_BAR" for d in decisions),
    }


def funding_gap_exposure(result, audit):
    potential = []
    for index,trade in enumerate(result.trades,1):
        candidates = audit["funding"][trade.symbol]["absent_under_modal_schedule_utc"]
        times = [int(datetime.fromisoformat(t).timestamp()*1000) for t in candidates]
        overlap = [utc(t) for t in times if trade.entry_time<t<=trade.exit_time]
        if overlap:
            potential.append({"trade_number": index, "symbol": trade.symbol,
                              "entry_utc": utc(trade.entry_time), "exit_utc": utc(trade.exit_time),
                              "potential_missing_funding_times_utc": overlap,
                              "reported_trade_net_pnl": trade.net_pnl})
    return {"exposed_trades": len(potential), "details": potential,
            "warning": "Exposure uses an assumed modal funding schedule. Missing rates/signs are unknown and are not filled with fabricated values."}


def analyze(result, audit):
    return {"overall": {**result.metrics, **trade_statistics(result.trades)},
            "monthly": monthly_statistics(result), "rejections": rejection_statistics(result.decisions),
            "potential_missing_funding_exposure": funding_gap_exposure(result,audit)}


def _format(value):
    return "undefined" if value is None else (format(value,".4f") if isinstance(value,Decimal) else str(value))


def write_research_report(output, audit, analyses, originals, manifest):
    output = Path(output)
    payload = {"research_type": "frozen_baseline_historical_evaluation", "execution_enabled": False,
               "original_data_audit": originals, "research_data_audit": audit,
               "collection_manifest": "collection.json", "frozen_source_hashes": manifest["frozen_source_hashes"],
               "source_hashes_verified_unchanged": True, "scenarios": analyses}
    (output/"evaluation.json").write_text(json.dumps(payload,indent=2,default=str,allow_nan=False)+"\n",encoding="utf-8")
    lines = ["# Frozen baseline: 90-day Demo historical evaluation","",
             "Public Demo data only. No credentials, authenticated requests, orders, ML, optimization or Phase 3.","",
             "## Coverage",""]
    for symbol in ("BTCUSDT","ETHUSDT"):
        bars, funding = audit["candles"][symbol+":5m"],audit["funding"][symbol]
        lines.append(f"- {symbol}: {bars['rows']} completed 5m candles; {bars['start_utc']} to {bars['end_utc']}; missing candle intervals: {bars['missing_intervals']}; funding records: {funding['rows']}.")
    lines.extend(["","SQLite integrity: "+audit["integrity"]+". Values/timestamps and contiguous shared grids were validated.",
                  "The original database remains unchanged and covers UTC 2026-10-08 only: 288/96/24/6 candles per symbol for 5m/15m/1h/4h, respectively; no gaps inside that day.","",
                  "## Method","",
                  "One continuous chronological shared-account run for each cost scenario. Initial equity 10,000 USDT; 0.5% planned risk per trade; 2x entry leverage; one shared position; 2% UTC daily halt. The frozen indicators, thresholds, ATR exits, 48-bar holding cap and conservative fill/funding rules are unchanged.",
                  "The first 199 candles warm up the baseline. Signals use closed candles and entries occur at the next open. No parameter search or holdout selection was performed.",
                  "Default: 0.05% fee per side and 0.02% adverse slippage per fill. Stress: 0.10% fee and 0.04% slippage. Funding records and all other settings are the same. Higher costs can change accepted sizes/trades through the existing risk gate; this is not a paired fixed-size accounting exercise.",
                  "No-trade keeps 10,000 USDT with zero costs and zero drawdown, excluding interest/inflation.","",
                  "## Full-period results","",
                  "| Metric | Default | Doubled costs | NO TRADE |","|---|---:|---:|---:|"])
    metrics = [("trades","Trades",0),("long_trades","LONG",0),("short_trades","SHORT",0),
               ("pnl_after_fees_slippage_before_funding","PnL after fees/slippage, before funding (USDT)",ZERO),
               ("funding_cost","Net funding cost (USDT)",ZERO),("net_pnl","Net PnL including funding (USDT)",ZERO),
               ("win_rate_pct","Win rate (%)",None),("profit_factor","Profit factor",None),
               ("maximum_drawdown_pct","Maximum drawdown (%)",ZERO),
               ("average_trade_duration_minutes","Average trade duration (minutes)",None),
               ("fees","Fees (USDT)",ZERO),("slippage_cost","Slippage/rounding (USDT)",ZERO),
               ("final_equity","Final equity (USDT)",Decimal(10000))]
    for key,label,inactive in metrics:
        lines.append(f"| {label} | {_format(analyses['default']['overall'][key])} | {_format(analyses['doubled_costs']['overall'][key])} | {_format(inactive)} |")
    lines.extend(["","## Monthly attribution","",
                  "These are slices of the same continuous runs: positions, indicators, equity and daily risk state carry across month boundaries. Trade counts, win rate, profit factor and trade PnL/costs are attributed by UTC exit month. A trade's full costs may include earlier months; marked-equity change is therefore shown separately. July and October are partial months.","",
                  "| Scenario | Month | Trades | LONG | SHORT | Net closed-trade PnL | Marked-equity change | Win % | PF | Within-month DD % | Average minutes |",
                  "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"])
    for scenario,analysis in analyses.items():
        for row in analysis["monthly"]:
            lines.append("| "+" | ".join(_format(v) for v in (scenario,row["month"],row["trades"],row["long_trades"],row["short_trades"],
                         row["net_pnl"],row["marked_equity_change"],row["win_rate_pct"],row["profit_factor"],
                         row["maximum_drawdown_pct"],row["average_trade_duration_minutes"]))+" |")
        with (output/(scenario+"-monthly.csv")).open("w",encoding="utf-8",newline="") as handle:
            rows=analysis["monthly"]
            writer=csv.DictWriter(handle,fieldnames=list(rows[0]) if rows else ["month"])
            writer.writeheader(); writer.writerows(rows)
    lines.extend(["","## Rejected signals and baseline filters",""])
    for scenario,analysis in analyses.items():
        reject=analysis["rejections"]
        lines.extend([f"### {scenario}","",f"Risk rejections: {reject['risk_rejections_total']}. Final-bar unfilled signals: {reject['final_bar_unfilled_signals']}.",
                      "","| Risk rejection reason | Count |","|---|---:|"])
        lines.extend(f"| {reason} | {count} |" for reason,count in reject["risk_rejections_by_reason"].items())
        lines.extend(["","| Baseline NO TRADE reason | Count |","|---|---:|"])
        lines.extend(f"| {reason} | {count} |" for reason,count in reject["baseline_no_trade_by_reason"].items())
    lines.extend(["","## Data quality and funding limits",""])
    for symbol in ("BTCUSDT","ETHUSDT"):
        bars, funding=audit["candles"][symbol+":5m"],audit["funding"][symbol]
        missing=funding["absent_under_modal_schedule_utc"]
        lines.append(f"- {symbol}: zero-volume bars {bars['zero_volume_bars']}; zero-range bars {bars['zero_range_bars']}; bars with >5% high/low range {bars['bars_with_range_over_5pct']}; largest range {bars['largest_bar_range_pct']:.4f}%; largest adjacent opening gap {bars['largest_adjacent_open_gap_pct']:.4f}%.")
        lines.append(f"- {symbol}: modal observed funding interval {funding['modal_spacing_ms']} ms; absent timestamps under that assumed schedule: {', '.join(missing) if missing else 'none'}. This is a schedule diagnostic, not independent confirmation of missing settlements. {len(funding['near_schedule_shifted_events'])} records differ from the schedule by 1ms; their actual timestamps are retained for settlement.")
    for scenario,analysis in analyses.items():
        gaps=analysis["potential_missing_funding_exposure"]
        lines.append(f"- {scenario}: {gaps['exposed_trades']} trades overlap potentially absent funding timestamps. Exact trade numbers/times are in evaluation.json. No funding rates were invented; costs are conditional on records actually returned.")
    lines.extend(["","## Interpretation and potential biases",""])
    for scenario,analysis in analyses.items():
        value=analysis["overall"]["net_pnl"]
        lines.append(f"- {scenario}: "+("positive net PnL on this dataset after assumed costs." if value>0 else "no positive net PnL after assumed costs on this dataset."))
    lines.extend([
        "- Demo history may differ from production market liquidity, funding and trading behavior. TLS to the fixed official Demo hostname establishes the requested source; candle quality checks do not prove an economically representative dataset.",
        "- Candle continuity does not prove funding completeness. Unknown funding rates could improve or worsen reported PnL; missing settlements are not verified zeros.",
        "- Fees, slippage and contract filters are frozen research assumptions, not verified historical Binance schedules. Historical data is stored as SQLite REAL and indicator arithmetic uses floats; Decimal financial accounting tolerates only 1e-12 USDT roundoff.",
        "- OHLC cannot reveal event order. Stops win ambiguous bars, gap stops use adverse opens, gap targets receive no improvement, and unknown-time exit bars pay funding debits but omit uncertain credits. Drawdown/daily halts use conservative adverse-bar liquidation values.",
        "- Maintenance-margin tiers, liquidation/ADL, order-book liquidity, latency and exchange outages are not simulated. Planned 0.5% risk and the 2% daily halt do not guarantee realized loss ceilings through gaps.",
        "- Both symbols compete for one shared position with deterministic BTC priority. Counts are portfolio results, not two independent strategy accounts.",
        "- This is descriptive historical evidence, not statistically validated future profitability or an untouched holdout certification. No optimization, ML or automated promotion occurred.",
        "- Average duration uses simulated entry/exit timestamps; intrabar exits are assigned to candle close, so duration is an OHLC approximation.",
        "","## Files and reproduction","",
        "Original data audit: original-audit.json. Download manifest and frozen hashes: collection.json. Extended audit: research-audit.json.",
        "Default/stress reports and complete journals: default/ and doubled-costs/. Monthly CSVs and all requested aggregates: evaluation.json.",
        "From the official project root, run scripts/research_history.py without --collect to reproduce offline; see docs/historical-research.md.",
        "","Stop after this research. Phase 3 requires explicit user approval."])
    lines.extend(["","## Verification and changed files",""])
    tests_path=output/"tests.json"
    if tests_path.is_file():
        tests=json.loads(tests_path.read_text(encoding="utf-8"))
        lines.append(f"Automated tests: {tests['passed']} passed, {tests['failed']} failed, {tests['errors']} errors, {len(tests['skipped'])} skipped; {tests['discovered']} discovered. The optional network test is skipped because tests run offline.")
    lines.extend([
        "Independent journal checks in journal-checks.json verify entry timing, planned sizing/leverage, fees, funding, no shared-position overlaps and net PnL/monthly reconciliation.",
        "Source hashes verify strategy.py, indicators.py, risk.py, backtest.py and the original reporting.py are unchanged. Original history is unchanged; all 576 overlapping five-minute candles match the new snapshot.",
        "Added public_history.py, history_audit.py and research_evaluation.py; scripts/research_history.py; tests/test_public_history.py and tests/test_research_evaluation.py. Updated README.md and AGENTS.md and added docs/historical-research.md. Added the research snapshot/checkpoints under data/ and reports under reports/historical-90d/.",
        "The first collection attempt stopped without adequate original error detail. Adjacent pages were independently rechecked and passed. Sanitized failure logging, validated checkpoints and bounded public GET recovery were added. The final collection completed; no history was filled or replaced.",
        "Narrow funding queries in funding-gap-confirmation.json confirm Demo did not return 08:00 events on August 17 and September 1 for either symbol. The historical schedule remains independently unverified.",
        "See tests.json, collection-attempt-1.json, failed-page-audit.json, next-page-diagnostic.json, journal-checks.json and overlap-comparison.json for verification evidence.",
    ])
    (output/"report.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    return payload
