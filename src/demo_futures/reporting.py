"""Serializable experiment and cost journals, plus a simple human-readable report."""
import csv
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path


def _json(value):
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError("Unsupported report value")


def _utc(timestamp):
    return datetime.fromtimestamp(timestamp / 1000, timezone.utc).isoformat()


def _csv(path, records, columns):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for record in records:
            writer.writerow(asdict(record))


def write_report(result, output):
    from .backtest import Trade, Decision, EquityPoint
    from dataclasses import fields
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    configuration = {"risk_and_costs": asdict(result.config),
                     "offline_contract_assumptions": {s: asdict(spec) for s, spec in result.specs.items()},
                     "strategy_version": result.strategy_version, "interval": result.interval}
    config_json = json.dumps(configuration, sort_keys=True, default=_json)
    report = {
        "schema_version": 1, "mode": "offline_backtest", "execution_enabled": False,
        "strategy_version": result.strategy_version, "data_sha256": result.data_hash,
        "configuration_sha256": hashlib.sha256(config_json.encode()).hexdigest(),
        "configuration": configuration, "symbols": sorted(result.specs),
        "start_utc": _utc(result.start_time), "end_utc": _utc(result.end_time),
        "bars_per_symbol": result.bars_per_symbol,
        "strategy": result.metrics, "no_trade": result.no_trade_metrics,
        "warnings": result.warnings,
        "profitable_on_this_sample_after_assumed_costs": result.metrics["net_pnl"] > 0,
        "general_profitability_established": False,
        "journals": {"trades": "trades.csv", "decisions": "decisions.csv", "equity": "equity.csv"},
    }
    (output / "report.json").write_text(json.dumps(report, indent=2, default=_json, allow_nan=False) + "\n", encoding="utf-8")
    for filename, records, model in (("trades.csv", result.trades, Trade),
                                     ("decisions.csv", result.decisions, Decision),
                                     ("equity.csv", result.equity, EquityPoint)):
        _csv(output / filename, records, [f.name for f in fields(model)])
    def fmt(value):
        return "undefined" if value is None else (format(value, ".6f") if isinstance(value, Decimal) else str(value))
    names = (("trades", "Closed trades"), ("net_pnl", "Net PnL (USDT)"),
             ("win_rate_pct", "Win rate (%)"), ("profit_factor", "Profit factor"),
             ("maximum_drawdown_pct", "Maximum drawdown (%)"), ("gross_pnl", "Raw price PnL (USDT)"),
             ("fees", "Fees (USDT)"), ("slippage_cost", "Slippage and adverse rounding (USDT)"),
             ("funding_cost", "Net funding cost (USDT)"), ("final_equity", "Final equity (USDT)"))
    lines = ["# Historical backtest report", "", "Offline only. No credentials, network, exchange orders, or ML.",
             "", f"Period: {_utc(result.start_time)} to {_utc(result.end_time)}",
             f"Markets: {', '.join(sorted(result.specs))}; interval: {result.interval}; bars per symbol: {result.bars_per_symbol}.",
             f"Strategy: {result.strategy_version}", "", "| Metric | Strategy | NO TRADE |", "|---|---:|---:|"]
    lines.extend(f"| {label} | {fmt(result.metrics[key])} | {fmt(result.no_trade_metrics[key])} |" for key, label in names)
    lines.extend(["", "Positive funding cost means paid; negative means received. Slippage is embedded in fill-price PnL and is not deducted twice.",
                  "", f"Profit-factor status: {result.metrics['profit_factor_status']}. Undefined metrics are not replaced with fabricated values.",
                  "", "## Interpretation", ""])
    if not result.trades:
        lines.append("No trades were executed. The strategy was NOT demonstrated profitable: zero PnL equals the inactive baseline.")
    elif result.metrics["net_pnl"] > 0:
        lines.append("Net PnL is positive AFTER all assumed simulated costs on this dataset. This does not establish future or general profitability.")
    else:
        lines.append("The strategy was NOT profitable AFTER all assumed simulated costs on this dataset.")
    lines.extend(["", "## Assumptions and limits", ""])
    lines.extend("- " + warning for warning in result.warnings)
    lines.extend(["", "Default assumptions: 10,000 USDT simulated equity; 0.5% trade-risk ceiling; 2x leverage; 2% UTC daily loss halt; one shared position; 2x ATR stop; 3x ATR target; maximum holding 48 bars.",
                  "Default costs: 0.05% fee per side, 0.02% adverse slippage per fill, and 0.1% notional funding reserve in sizing. The reserve is not deducted as a cost; actual recorded funding events are settled instead.",
                  "Inspect report.json for the exact configuration used in this run; configurable values may differ from these defaults.",
                  "", "## Reproducibility", "", f"Data SHA-256: {result.data_hash}",
                  f"Configuration SHA-256: {report['configuration_sha256']}",
                  "", "See trades.csv for entry/exit/PnL/costs/reasons, decisions.csv for signals and risk rejections, and equity.csv for the marked equity path."])
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report
