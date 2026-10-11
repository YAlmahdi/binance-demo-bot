"""Development data-engineering diagnostics; no prediction or policy evaluation."""
from collections import Counter
from decimal import Decimal
from .config import DEV_END, START, utc
from ..risk import BacktestConfig


def payoff_summary(labels):
    trades = [r.trade for r in labels if r.status == "VALID"]
    zero = Decimal(0)
    winning = [t.net_pnl for t in trades if t.net_pnl > 0]
    losing = [t.net_pnl for t in trades if t.net_pnl < 0]
    average_win = sum(winning, zero)/len(winning) if winning else None
    average_loss = sum(losing, zero)/len(losing) if losing else None
    return {"isolated_outcomes": len(trades), "class_1": len(winning),
            "class_0": len(trades)-len(winning), "breakeven": sum(t.net_pnl == 0 for t in trades),
            "mean_winning_net_pnl": average_win, "mean_losing_net_pnl": average_loss,
            "payoff_ratio": average_win / -average_loss if average_win and average_loss else None,
            "descriptive_break_even_win_fraction": -average_loss/(average_win-average_loss)
                if average_win and average_loss else None,
            "mean_net_risk_units": sum((t.net_pnl/t.risk_budget for t in trades),zero)/len(trades) if trades else None,
            "fees_per_outcome": sum((t.fees for t in trades),zero)/len(trades) if trades else None,
            "slippage_per_outcome": sum((t.slippage_cost for t in trades),zero)/len(trades) if trades else None,
            "funding_per_outcome": sum((t.funding_cost for t in trades),zero)/len(trades) if trades else None,
            "exits": dict(sorted(Counter(t.exit_reason for t in trades).items())),
            "losses_exceeding_planned_budget": sum(t.net_pnl < -t.risk_budget-Decimal("1e-12") for t in trades),
            "funding_mark_fallbacks": sum(t.funding_mark_fallbacks for t in trades),
            "uncertain_funding_credits_skipped": sum(t.uncertain_funding_credits_skipped for t in trades),
            "interpretation": "Overlapping fresh-account labels; not a portfolio return or independent trades"}


def risk_diagnostics(labels):
    """Describe verified label ledgers; never change labels or frozen sizing."""
    config = BacktestConfig()
    valid = [r for r in labels if r.status == "VALID"]
    tolerance = Decimal("1e-12")
    overruns = []
    for row in valid:
        t = row.trade
        if t.net_pnl >= -t.risk_budget-tolerance:
            continue
        reserve = t.quantity*t.entry_price*config.funding_reserve_rate
        accounted_stop_loss = -t.planned_loss + reserve - t.funding_cost
        matches_stop_accounting = (t.exit_reason.startswith("stop_loss")
                                  and abs(t.net_pnl-accounted_stop_loss) <= tolerance)
        overruns.append({"row_id": row.row_id, "symbol": row.symbol, "side": t.side,
                         "entry_utc": utc(t.entry_time), "exit_utc": utc(t.exit_time),
                         "risk_budget": t.risk_budget, "planned_loss": t.planned_loss,
                         "actual_net_pnl": t.net_pnl, "funding_reserve_sizing_only": reserve,
                         "recorded_funding_cost": t.funding_cost, "exit_reason": t.exit_reason,
                         "stop_ledger_reconciles": matches_stop_accounting,
                         "cause": "Recorded funding debit exceeded sizing reserve"
                            if matches_stop_accounting and t.funding_cost > reserve else "Requires further investigation"})
    return {"planned_entry_budget_violations": sum(r.trade.planned_loss > r.trade.risk_budget+tolerance for r in valid),
            "entry_leverage_violations": sum(r.trade.quantity*r.trade.entry_price > config.initial_equity*config.leverage+tolerance for r in valid),
            "realized_loss_budget_overruns": overruns,
            "risk_clearance": "NOT CLEARED: realized-loss overruns require review" if overruns else "No observed overruns; no model candidate evaluated",
            "note": "Overlapping isolated opportunities may share a funding event; these are not independent portfolio losses."
            }


def development_audit(data, opportunities, features, labels, splits, counts, provenance):
    if any(r.decision_time >= DEV_END for r in features) or len(features) != len(opportunities):
        raise ValueError("Audit input violates development feature contract")
    ids = {r.row_id for r in features}
    if ids != {r.row_id for r in labels} or len(ids) != len(features):
        raise ValueError("Feature/label identity mismatch")
    label_counts = Counter(r.status for r in labels)
    for row in labels:
        if row.status == "VALID" and row.interval_end > DEV_END:
            raise PermissionError("Development labels must mature before the locked period")
    return {"stage": "DEVELOPMENT_ENGINEERING_AUDIT", "engineering_checks": "PASS",
            "period": {"start_utc": utc(START), "end_exclusive_utc": utc(DEV_END)},
            "feature_count": 16, "features": len(features), "opportunities": len(opportunities),
            "enumeration_counts": counts, "label_counts": dict(sorted(label_counts.items())),
            "source_data_audit": data.audit, "folds": [{k:v for k,v in fold.items()
                if k not in ("train_ids", "evaluation_ids", "excluded_ids")}
                for fold in splits["folds"]],
            "isolated_development_payoffs": payoff_summary(labels),
            "risk_diagnostics": risk_diagnostics(labels),
            "isolated_payoffs_by_symbol": {s:payoff_summary([r for r in labels if r.symbol == s])
                for s in ("BTCUSDT", "ETHUSDT")},
            "probability_buckets": "NOT AVAILABLE: no model fitted or predictions generated",
            "admission_threshold": "0.65 (frozen, not optimized)",
            "model_fit": "NOT IMPLEMENTED / NOT APPROVED",
            "selection_validation": "LOCKED / NOT EVALUATED", "final": "LOCKED / NOT EVALUATED",
            "execution_enabled": False, "provenance": provenance,
            "limitations": [
                "Retrospective label exclusions are not decision-time filters.",
                "OHLC availability at candle close is assumed; real latency/revisions unknown.",
                "Conservative stop-first, daily adverse marks and uncertain funding-credit omissions are inherited.",
                "Funding modal schedule is diagnostic, not verified historical completeness.",
                "Fixed Demo fees/filters/slippage, no liquidity/maintenance margin/liquidation model.",
                "Overlapping fresh-account outcomes cannot be summed as a shared-account return.",
                "No classification/calibration or trading-policy model performance evaluated.",
                "Final period was previously inspected in baseline research; locked now but not truly untouched.",
            ]}


def markdown_report(report, experiment_id):
    pay = report["isolated_development_payoffs"]
    lines = ["# Phase 4A development engineering audit", "",
             f"Experiment: `{experiment_id}`. Offline engineering only. No fitted model or predictions.", "",
             f"UTC period: {report['period']['start_utc']} to {report['period']['end_exclusive_utc']} (exclusive).",
             f"Fixed 16 features; {report['features']} baseline opportunities.", "",
             "## Outcomes and exclusions", ""]
    lines += [f"- {name}: {number}" for name,number in report["label_counts"].items()]
    lines += ["", "Fresh accounts do not inherit previous losses, halts or position conflicts. These are overlapping",
              "isolated labels, not the original 851 trades, an executable portfolio, or independent observations.",
              "", "## Fixed sample gates", "",
              "| Fold | Train rows / class 0 / class 1 | Train gate | Eval rows / class 0 / class 1 / nonoverlap | Eval gate |",
              "|---|---|---|---|---|"]
    for fold in report["folds"]:
        t,e = fold["train_gate"],fold["evaluation_gate"]
        lines.append(f"| {fold['fold']} | {t['row_count']} / {t['class_0']} / {t['class_1']} | {t['status']} | "
                     f"{e['row_count']} / {e['class_0']} / {e['class_1']} / {e['nonoverlap_count']} | {e['status']} |")
    lines += ["", "All gates are hard. No boundaries, horizon, features or thresholds were adjusted.",
              "Membership and exact exclusion reasons are recorded in splits.json; nominal later boundaries have no outcomes.",
              "", "## Development label payoff asymmetry", "",
              f"Mean winner: {pay['mean_winning_net_pnl']} USDT; mean loser: {pay['mean_losing_net_pnl']} USDT.",
              f"Payoff ratio: {pay['payoff_ratio']}; descriptive break-even fraction: {pay['descriptive_break_even_win_fraction']}.",
              f"Mean net/risk-budget: {pay['mean_net_risk_units']}; losses beyond planned budget: {pay['losses_exceeding_planned_budget']}.",
              "These descriptive values do not optimize or replace the frozen p >= 0.65 admission threshold.",
              "Probability-bucket outcomes: NOT AVAILABLE (no fitted model or predictions).",
              "", "## Realized risk evidence", "",
              f"Planned entry-budget violations: {report['risk_diagnostics']['planned_entry_budget_violations']}; entry-leverage violations: {report['risk_diagnostics']['entry_leverage_violations']}.",
              f"Risk clearance: {report['risk_diagnostics']['risk_clearance']}.",
              f"Realized-budget overruns: {len(report['risk_diagnostics']['realized_loss_budget_overruns'])}. Detailed row identities, funding costs and reconciliation are in audit.json.",
              "The detailed audit reconciles net = -planned_loss + sizing_reserve - recorded_funding_cost for these stop exits.",
              "The reserve is used for sizing and is not charged twice. Identified causes are recorded per overrun.",
              "Some opportunities overlap the same funding event, so five rows do not mean five independent account losses.",
              "No losing row was removed and no risk/label parameter was changed. Review remains necessary before clearing future candidate risk evidence.",
              "", "## Verified boundaries", "",
              "Protected source database, frozen code and original journals: UNCHANGED (see provenance.json).",
              "Selection validation and final period: LOCKED / NOT EVALUATED. No fitting, ML selection, exchange activity or activation.",
              "The test report separately records engineering test evidence; sample sufficiency is not predictive merit.",
              "", "## Limitations", ""]
    lines += ["- " + value for value in report["limitations"]]
    return "\n".join(lines) + "\n"
