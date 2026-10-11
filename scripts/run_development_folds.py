"""One fixed three-fold development experiment; no validation/final/unlock/deploy commands."""
from dataclasses import asdict
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True; sys.path.insert(0,str(ROOT/"src"))
from demo_futures.ml_research.development_runtime import guard


def main():
    if len(sys.argv)!=1: raise PermissionError("No dates, parameters, stages or thresholds may be overridden")
    guard(ROOT)
    from demo_futures.ml_research.development_runtime import environment,write_version
    from demo_futures.ml_research.development_data import load_engineering,training_partition,evaluation_rows,ENGINEERING_ID
    from demo_futures.ml_research.model import fit,RECIPE
    from demo_futures.ml_research.evaluation import compare,scores
    from demo_futures.ml_research.portfolio import replay,economic_gates
    from demo_futures.ml_research.config import canonical,digest,FOLDS,BUFFER,FEATURE_NAMES,utc
    from demo_futures.ml_research.dataset import load_development,file_hash
    from demo_futures.ml_research.artifacts import verify_inputs,csv_text
    from demo_futures.ml_research.audit import risk_diagnostics,payoff_summary
    from demo_futures.ml_research.opportunities import enumerate_opportunities
    from demo_futures.ml_research.splits import sufficiency
    import numpy as np
    versions=environment(ROOT)
    witness=json.loads((ROOT/"artifacts/ml-research/development-fitting-input-witness.json").read_text())
    verify_inputs(ROOT,witness)
    tests=json.loads((ROOT/"reports/ml-research/development-tests.json").read_text())
    if tests["failures"] or tests["errors"] or not tests["network_blocked"]: raise RuntimeError("Passing offline tests required")
    paths=list((ROOT/"src/demo_futures/ml_research").glob("*.py"))+list((ROOT/"tests").glob("test_ml_*.py"))
    paths += [ROOT/"scripts/run_development_folds.py",ROOT/"scripts/verify_development_folds.py"]
    hashes={p.relative_to(ROOT).as_posix():file_hash(p) for p in sorted(paths)}
    if hashes!=tests["research_code_sha256"]: raise RuntimeError("Exactly this source must pass tests before fitting")
    rows=load_engineering(ROOT)
    partitions=[training_partition(rows,n) for n in (1,2,3)]
    if any(sufficiency(evaluation_rows(rows,n),"development_evaluation")["status"]!="SUFFICIENT" for n in (1,2,3)):
        raise RuntimeError("INSUFFICIENT development gates; refusing to change splits")
    data=load_development(ROOT/"data/research-90d.sqlite3",rows.provenance["database_sha256"])
    opportunities,generated,_=enumerate_opportunities(data.candles)
    if {f.row_id:f for f in generated}!=dict(rows.features): raise RuntimeError("Saved causal features differ from source")
    config={"recipe":RECIPE,"stage":"APPROVED_DEVELOPMENT_FITTING_ONLY","folds":FOLDS,"buffer_ms":BUFFER,
            "feature_order":FEATURE_NAMES,"bootstrap":{"unit":"paired 24h UTC blocks","resamples":1000,"seed":42},
            "threshold_tuning":False,"execution_enabled":False,"risk_evidence":"NOT CLEARED",
            "selection_validation":"LOCKED","final":"LOCKED","engineering_id":ENGINEERING_ID}
    dependencies={p.name:file_hash(p) for p in (ROOT/"research/dependencies").glob("*.json")}
    dependencies["requirements.lock"]=file_hash(ROOT/"research/dependencies/requirements.lock")
    provenance={"config_sha256":digest(config),"code_sha256":hashes,"environment":versions,
                "dependencies_sha256":dependencies,"engineering_manifest_sha256":file_hash(ROOT/"artifacts/ml-research"/ENGINEERING_ID/"manifest.json"),
                "database_sha256":data.database_hash,"proposal_sha256":file_hash(ROOT/"docs/PHASE4A_RESEARCH_PROPOSAL.md"),
                "protected_input_witness_sha256":file_hash(ROOT/"artifacts/ml-research/development-fitting-input-witness.json")}
    experiment="development-"+digest(provenance)[:20]
    receipt=ROOT/"artifacts/ml-research/development-fitting-run.json"
    if receipt.exists(): raise FileExistsError("Development experiment already attempted. No automatic refitting or selection is allowed")
    state={"experiment":experiment,"recipe":RECIPE,"historical_fits_attempted":[],"status":"REGISTERED_BEFORE_FITTING",
           "selection_validation":"LOCKED","final":"LOCKED","execution_enabled":False}
    with receipt.open("x",encoding="utf-8") as f:f.write(canonical(state)+"\n")
    artifact_files={"config.json":canonical(config)+"\n","provenance.json":canonical(provenance)+"\n",
                    "splits.json":canonical(rows.splits)+"\n"}
    report_files={"tests.json":canonical(tests)+"\n"}
    fold_reports=[]; pooled_labels=[]; pooled_p=[]; pooled_prior=[]; predictions=[]; coefficients=[]
    for partition in partitions:
        n=partition.fold; begin,end=FOLDS[n-1]
        state["historical_fits_attempted"].append(n); state["status"]="FITTING"
        receipt.write_text(canonical(state)+"\n",encoding="utf-8")
        model=fit(partition)  # Sole historical fit for this fold. Evaluation rows never enter this call.
        artifact_files[f"fold-{n}-model.json"]=canonical(model.manifest())+"\n"
        eval_labels=evaluation_rows(rows,n)  # Outcomes consumed only after that fold's fit is complete.
        eval_features=tuple(rows.features[r.row_id] for r in eval_labels)
        p=model.predict(eval_features); prior=np.full(len(p),model.training_prevalence)
        classification=compare(eval_labels,p,prior)
        all_features=tuple(f for f in rows.features.values() if begin<=f.decision_time<end and f.decision_time+1+BUFFER<=end)
        all_p=model.predict(all_features)
        probability_map={(f.symbol,f.decision_time):float(v) for f,v in zip(all_features,all_p)}
        prior_map={k:model.training_prevalence for k in probability_map}
        majority_map={k:float(model.training_prevalence>.5) for k in probability_map}
        portfolios={}; results={}
        for scenario,stress in (("default",False),("doubled_costs",True)):
            portfolios[scenario]={}; results[scenario]={}
            for policy,prob in (("ml",probability_map),("baseline",None),("no_trade",None),
                                ("training_prevalence",prior_map),("majority_class",majority_map)):
                result,summary=replay(data,n,policy,prob,doubled_costs=stress)
                portfolios[scenario][policy]=summary; results[scenario][policy]=result
                prefix=f"fold-{n}-{scenario}-{policy}"
                cols=tuple(result.trades[0].__dataclass_fields__) if result.trades else tuple(__import__('demo_futures.backtest',fromlist=['Trade']).Trade.__dataclass_fields__)
                report_files[prefix+"-trades.csv"]=csv_text(cols,(asdict(t) for t in result.trades))
                report_files[prefix+"-equity.csv"]=csv_text(("timestamp","equity","kind"),(asdict(e) for e in result.equity))
        repeated,_=replay(data,n,"ml",probability_map)
        if repeated.trades!=results["default"]["ml"].trades or repeated.equity!=results["default"]["ml"].equity:
            raise RuntimeError("Portfolio replay is not deterministic")
        groups={}
        for name,subset in (("BTCUSDT",[i for i,r in enumerate(eval_labels) if r.symbol=="BTCUSDT"]),
                            ("ETHUSDT",[i for i,r in enumerate(eval_labels) if r.symbol=="ETHUSDT"]),
                            ("LONG",[i for i,r in enumerate(eval_labels) if r.trade.side=="LONG"]),
                            ("SHORT",[i for i,r in enumerate(eval_labels) if r.trade.side=="SHORT"])):
            groups[name]=scores([eval_labels[i] for i in subset],p[subset]) if subset else {"status":"INSUFFICIENT: no rows"}
        fold_reports.append({"fold":n,"evaluation_begin_utc":utc(begin),"evaluation_end_exclusive_utc":utc(end),
            "train_gate":partition.validate(),"evaluation_gate":sufficiency(eval_labels,"development_evaluation"),
            "training_prevalence":model.training_prevalence,"iterations":model.iterations,
            "classification":classification,"subgroup_classification":groups,"portfolios":portfolios,
            "economic_gates":economic_gates(portfolios["default"]["ml"],portfolios["default"]["baseline"],portfolios["doubled_costs"]["ml"]),
            "all_causal_window_opportunities":len(all_features),"classification_valid_rows":len(eval_labels),
            "unlabeled_window_opportunities_scored":sum(rows.labels[f.row_id].status!="VALID" for f in all_features),
            "deterministic_prediction_and_portfolio_replay":True})
        for f,v in zip(all_features,all_p):
            predictions.append({"fold":n,"row_id":f.row_id,"symbol":f.symbol,"decision_time":f.decision_time,
                "p":float(v),"admitted":int(v>=.65),"label_status_for_reporting_only":rows.labels[f.row_id].status,
                "evaluation_label":rows.labels[f.row_id].y if f.row_id in {r.row_id for r in eval_labels} else None,
                "training_prevalence":model.training_prevalence})
        for name,value in zip(FEATURE_NAMES,model.coefficients):
            coefficients.append({"fold":n,"feature":name,"coefficient":value,"unit":"one training SD" if name not in FEATURE_NAMES[14:] else "0 to 1 flag"})
        pooled_labels.extend(eval_labels); pooled_p.extend(p); pooled_prior.extend(prior)
        print(f"Fold {n} complete: {len(partition.labels)} train / {len(eval_labels)} evaluated; no later-period access",flush=True)
    protected=verify_inputs(ROOT,witness)
    if hashes!={p.relative_to(ROOT).as_posix():file_hash(p) for p in sorted(paths)}:raise RuntimeError("Code changed during evaluation")
    report={"stage":"DEVELOPMENT_FOLDS_ONLY","experiment":experiment,"folds":fold_reports,
        "pooled_out_of_fold_classification":compare(pooled_labels,pooled_p,pooled_prior),
        "development_label_payoff_asymmetry":payoff_summary(rows.labels.values()),
        "risk_diagnostics":risk_diagnostics(rows.labels.values()),"risk_evidence":"NOT CLEARED",
        "protected_inputs":protected,"provenance":provenance,"models_fitted":3,"threshold":.65,
        "selection_validation":"LOCKED / NOT EVALUATED","final":"LOCKED / NOT EVALUATED","execution_enabled":False,
        "no_trade_predictive_metrics":"Not applicable: cash policy makes no target prediction; zero PnL compared separately",
        "limitations":["Only existing Demo development data; no exchange or account access.",
            "Isolated fresh-account targets overlap and differ from shared-portfolio admissions/daily halts.",
            "Few UTC blocks and correlated overlapping labels limit uncertainty estimates; nonoverlap sensitivity is descriptive.",
            "Probability of a winning isolated trade is not expected PnL; payoff asymmetry is material.",
            "Missing funding events are unknown costs; retrospective exclusions never gate portfolio admission.",
            "Each fold resets to 10000 simulated units. Do not concatenate equity curves as one account.",
            "Costs, OHLC stop-first ordering, adverse daily marks and skipped uncertain funding credits are fixed assumptions.",
            "No real order-book, maintenance margin, liquidation, ADL or exchange execution simulation.",
            "Final period was previously inspected for baseline research; remains locked for ML, not truly untouched.",
            "No selection-validation, final evaluation, threshold tuning, calibration fitting or activation approved."]}
    report_files["evaluation.json"]=canonical(report)+"\n"
    report_files["coefficients.csv"]=csv_text(tuple(coefficients[0]),coefficients)
    report_files["predictions.csv"]=csv_text(tuple(predictions[0]),predictions)
    lines=["# Phase 4A development-fold logistic research", "",f"Experiment: `{experiment}`. Three fixed historical fits; models inactive.",
        "Risk evidence: **NOT CLEARED**. Selection validation and final outcomes remain locked.","", "## Predictive results", "",
        "Lower log loss and Brier score are better. Prior probabilities use only each fold's training labels.",
        "Hard majority predictions have infinite log loss when they assign zero probability to an observed class.","",
        "| Fold | Train / Eval | Model log loss | Training-prior log loss | Model / prior Brier | Accuracy / majority accuracy |", "|---|---|---|---|---|---|"]
    for f in fold_reports:
        c=f["classification"]["policies"];m=c["model"];b=c["training_prevalence"]
        lines.append(f"| {f['fold']} | {f['train_gate']['row_count']} / {f['evaluation_gate']['row_count']} | {m['log_loss']:.6f} | {b['log_loss']:.6f} | {m['brier_score']:.6f} / {b['brier_score']:.6f} | {m['accuracy_at_0_5']:.3%} / {c['majority_class']['accuracy_at_0_5']:.3%} |")
    lines += ["", "## Shared-portfolio outcomes after costs", "", "Fresh 10000 account per fold; same window and common full-horizon cutoff for every policy. No outcomes used to filter admission.",
        "", "| Fold | ML trades | ML net | Baseline net | Cash net | ML PF | ML drawdown % | ML doubled-cost net |", "|---|---|---|---|---|---|---|---|"]
    for f in fold_reports:
        d=f["portfolios"]["default"];m=d["ml"]["metrics"];stress=f["portfolios"]["doubled_costs"]["ml"]["metrics"]
        lines.append(f"| {f['fold']} | {m['trades']} | {m['net_pnl']:.4f} | {d['baseline']['metrics']['net_pnl']:.4f} | 0 | {m['profit_factor']} | {m['maximum_drawdown_pct']:.4f} | {stress['net_pnl']:.4f} |")
    lines += ["", "## Gates and uncertainty", "", "Hard sample gates and chronological boundaries were unchanged. The 0.65 admission threshold was never optimized.",
        "Paired 24h UTC block bootstrap: 1000 resamples, seed 42. See evaluation.json for 95% intervals, class counts, ten fixed calibration buckets, sparse buckets and nonoverlap sensitivity."]
    for f in fold_reports:
        lines += ["",f"Fold {f['fold']} predictive gates: `{canonical(f['classification']['predictive_gates'])}`.",
                  f"Economic gates: `{canonical(f['economic_gates'])}`."]
    lines += ["",f"Pooled OOF predictive gates: `{canonical(report['pooled_out_of_fold_classification']['predictive_gates'])}`.",
        "", "## What the model learned", "", "Logistic coefficients describe associations with a positive net isolated trade. Positive coefficients increase estimated win probability, negative coefficients decrease it. Continuous coefficients are per training standard deviation; flags are 0-to-1 effects. Correlated indicators prevent a causal interpretation.",
        "The full fixed coefficient table is coefficients.csv. Scaling parameters and coefficients are stored as inert JSON, never executable pickle files.",
        "", "## Funding-reserve overruns", "",f"{len(report['risk_diagnostics']['realized_loss_budget_overruns'])} saved isolated labels exceed their 50-unit risk budgets. Their stop ledgers reconcile as net = -planned_loss + sizing_reserve - actual funding debit. Funding exceeded the fixed reserve; it was not charged twice. Some rows share funding events and are not independent losses. No labels or risk rules were changed. Risk evidence stays NOT CLEARED regardless of model admissions.",
        "", "## Test and preservation evidence", "",f"{tests['passed']} passed, {tests['failures']} failures, {tests['errors']} errors, {len(tests['skipped'])} skipped. The skipped test requires network access and was disabled. {protected['files_checked']} protected files are unchanged, including source databases, frozen code, original journals and engineering evidence. Test fitting uses synthetic fixtures only.",
        "", "## Limitations", ""]+["- "+s for s in report["limitations"]]
    lines += ["", "## Approval boundary", "", "Stop here. Selection validation needs explicit new approval. No deployment, execution, Dashboard, Phase 3 or VPS work is enabled."]
    report_files["report.md"]="\n".join(lines)+"\n"
    write_version(ROOT/"artifacts/ml-research"/experiment,artifact_files)
    write_version(ROOT/"reports/ml-research"/experiment,report_files)
    state["status"]="COMPLETED_INACTIVE_DEVELOPMENT_ONLY";receipt.write_text(canonical(state)+"\n",encoding="utf-8")
    print("Completed:",experiment,"Risk NOT CLEARED. Await explicit selection-validation approval.",flush=True)


if __name__=="__main__":main()
