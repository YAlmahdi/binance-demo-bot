"""Independent saved-artifact checks and descriptive diagnostics; never call fit."""
import csv
from dataclasses import fields
from decimal import Decimal
import io
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT/"src"))
from demo_futures.ml_research.development_runtime import guard,environment,write_version

def main():
    if len(sys.argv)!=1:raise PermissionError("Only the registered development result may be verified")
    guard(ROOT)
    import numpy as np
    from sklearn.metrics import log_loss,brier_score_loss
    from demo_futures.ml_research.model import FrozenModel,RECIPE
    from demo_futures.ml_research.development_data import load_engineering,training_partition,evaluation_rows
    from demo_futures.ml_research.config import digest,FOLDS,BUFFER,FEATURE_NAMES,canonical,utc
    from demo_futures.ml_research.dataset import file_hash
    from demo_futures.ml_research.artifacts import verify_inputs,csv_text
    environment(ROOT)
    state=json.loads((ROOT/"artifacts/ml-research/development-fitting-run.json").read_text())
    if state["historical_fits_attempted"]!=[1,2,3] or state["status"]!="COMPLETED_INACTIVE_DEVELOPMENT_ONLY":
        raise ValueError("Exactly the completed three historical fits are required")
    experiment=state["experiment"];artifacts=ROOT/"artifacts/ml-research"/experiment;reports=ROOT/"reports/ml-research"/experiment
    checks=[]
    def passed(name,condition):
        if not condition:raise AssertionError(name)
        checks.append({"check":name,"status":"PASS"})
    for directory in (artifacts,reports):
        m=json.loads((directory/"manifest.json").read_text())
        passed(directory.parent.name+" payload hashes",all(file_hash(directory/n)==h for n,h in m["files_sha256"].items()))
        passed(directory.parent.name+" inactive locked manifest",not m["execution_enabled"] and m["selection_validation"]=="LOCKED" and m["final"]=="LOCKED")
    report=json.loads((reports/"evaluation.json").read_text());provenance=report["provenance"]
    passed("tested source still matches fitted-version provenance",all(file_hash(ROOT/n)==h for n,h in provenance["code_sha256"].items()))
    witness=json.loads((ROOT/"artifacts/ml-research/development-fitting-input-witness.json").read_text())
    protection=verify_inputs(ROOT,witness);passed("92 frozen and engineering inputs unchanged",protection["files_checked"]==92)
    rows=load_engineering(ROOT)
    with (reports/"predictions.csv").open(newline="") as handle:predictions=list(csv.DictReader(handle))
    bucket_rows=[];outlier_rows=[];model_info=[]
    for n in (1,2,3):
        info=json.loads((artifacts/f"fold-{n}-model.json").read_text())
        passed(f"Fold {n} fixed recipe and inactive schema",info["recipe"]==RECIPE and not info["execution_enabled"])
        kwargs={f.name:info[f.name] for f in fields(FrozenModel)}
        for name in ("mean","scale","coefficients","feature_order"):kwargs[name]=tuple(kwargs[name])
        model=FrozenModel(**kwargs);model.validate();part=training_partition(rows,n);evals=evaluation_rows(rows,n)
        passed(f"Fold {n} exact training IDs",model.training_ids_sha256==digest([r.row_id for r in part.labels]))
        x=np.asarray([f.values for f in part.features])
        passed(f"Fold {n} training-only scaler parameters",np.allclose(model.mean,x[:,:14].mean(axis=0),rtol=0,atol=1e-12)
               and np.allclose(model.scale,np.where(x[:,:14].std(axis=0)==0,1,x[:,:14].std(axis=0)),rtol=0,atol=1e-12))
        saved=[d for d in predictions if int(d["fold"])==n];begin,end=FOLDS[n-1]
        expected={r.row_id for r in rows.features.values() if begin<=r.decision_time<end and r.decision_time+1+BUFFER<=end}
        passed(f"Fold {n} causal-window predictions include retrospective exclusions",set(d["row_id"] for d in saved)==expected and len(saved)==len(expected))
        p=model.predict([rows.features[d["row_id"]] for d in saved])
        passed(f"Fold {n} inert model prediction parity",np.allclose(p,[float(d["p"]) for d in saved],rtol=0,atol=1e-12))
        pp=model.predict([rows.features[r.row_id] for r in evals]);y=[r.y for r in evals];reported=report["folds"][n-1]["classification"]["policies"]["model"]
        passed(f"Fold {n} independent sklearn scoring parity",abs(log_loss(y,pp)-reported["log_loss"])<1e-12 and abs(brier_score_loss(y,pp)-reported["brier_score"])<1e-12)
        passed(f"Fold {n} exact evaluation labels and admission threshold",{d["row_id"] for d in saved if d["evaluation_label"]!=""}=={r.row_id for r in evals}
            and all(int(d["admitted"])==int(float(d["p"])>=.65) for d in saved))
        for b in reported["calibration"]["equal_width_buckets"]:
            indexes=[i for i,v in enumerate(pp) if min(int(v*10),9)==int(round(b["lower"]*10))]
            subset=[evals[i] for i in indexes];count=len(subset)
            bucket_rows.append({"fold":n,"lower":b["lower"],"upper":b["upper"],"rows":count,
                "status":b["status"],"mean_probability":b["predicted_mean"],"win_fraction":b["observed_win_fraction"],
                "mean_net_pnl":sum((r.trade.net_pnl for r in subset),Decimal(0))/count if count else None,
                "mean_win":b["isolated_payoff"]["mean_winning_net_pnl"],"mean_loss":b["isolated_payoff"]["mean_losing_net_pnl"],
                "payoff_ratio":b["isolated_payoff"]["payoff_ratio"],"descriptive_break_even_win_fraction":b["isolated_payoff"]["descriptive_break_even_win_fraction"],
                "mean_risk_units":b["isolated_payoff"]["mean_net_risk_units"],"mean_fees":b["isolated_payoff"]["fees_per_outcome"],
                "mean_slippage":b["isolated_payoff"]["slippage_per_outcome"],"mean_funding":b["isolated_payoff"]["funding_per_outcome"],
                "uncertainty":canonical(b["uncertainty"])})
        # Descriptive extrapolation diagnosis, never a filter or a parameter search.
        for d in saved:
            if not int(d["admitted"]):continue
            f=rows.features[d["row_id"]];z=(np.array(f.values[:14])-np.array(model.mean))/np.array(model.scale)
            contributions=z*np.array(model.coefficients[:14]);order=np.argsort(-np.abs(contributions))[:4]
            for i in order:
                outlier_rows.append({"fold":n,"row_id":f.row_id,"decision_utc":utc(f.decision_time),"p":float(d["p"]),
                    "label_status_for_reporting_only":rows.labels[f.row_id].status,"y":rows.labels[f.row_id].y,
                    "feature":FEATURE_NAMES[i],"value":f.values[i],"training_min":float(x[:,i].min()),
                    "training_max":float(x[:,i].max()),"training_standard_deviations":float(z[i]),
                    "logit_contribution":float(contributions[i]),"outside_training_range":bool(f.values[i]<x[:,i].min() or f.values[i]>x[:,i].max())})
        for scenario in ("default","doubled_costs"):
            for policy,summary in report["folds"][n-1]["portfolios"][scenario].items():
                with (reports/f"fold-{n}-{scenario}-{policy}-trades.csv").open(newline="") as h:trades=list(csv.DictReader(h))
                net=sum((Decimal(t["net_pnl"]) for t in trades),Decimal(0))
                passed(f"Fold {n} {scenario} {policy} journal accounting and timing",len(trades)==summary["metrics"]["trades"] and abs(net-Decimal(summary["metrics"]["net_pnl"]))<Decimal("1e-12")
                    and all(begin<=int(t["signal_time"])<int(t["entry_time"])<=int(t["exit_time"])<end
                        and int(t["signal_time"])+1+BUFFER<=end and abs(Decimal(t["gross_pnl"])-Decimal(t["slippage_cost"])-Decimal(t["fees"])-Decimal(t["funding_cost"])-Decimal(t["net_pnl"]))<Decimal("1e-12") for t in trades))
        model_info.append({"fold":n,"p_min":float(min(p)),"p_max":float(max(p)),"admitted":sum(int(d["admitted"]) for d in saved),"scored":len(saved)})
    passed("funding-overrun labels unchanged and reconciled",len(report["risk_diagnostics"]["realized_loss_budget_overruns"])==5 and all(r["stop_ledger_reconciles"] for r in report["risk_diagnostics"]["realized_loss_budget_overruns"]))
    evidence={"experiment":experiment,"checks":checks,"passed":len(checks),"failures":0,"historical_fits_in_this_verification":0,
        "models_replayed":3,"protected_inputs":protection,"prediction_ranges":model_info,
        "risk_evidence":"NOT CLEARED","selection_validation":"LOCKED / NOT EVALUATED","final":"LOCKED / NOT EVALUATED",
        "network_blocked":True,"credential_files_blocked":True,"verification_script_sha256":file_hash(Path(__file__)),
        "note":"Extrapolation is descriptive after evaluation; never used to alter a model or admission."}
    out=ROOT/"reports/ml-research"/(experiment+"-verification")
    files={"verification.json":canonical(evidence)+"\n","probability-bucket-payoffs.csv":csv_text(tuple(bucket_rows[0]),bucket_rows),
           "admitted-feature-contributions.csv":csv_text(tuple(outlier_rows[0]),outlier_rows)}
    if out.exists():
        manifest=json.loads((out/"manifest.json").read_text())
        if any((out/n).read_text()!=s for n,s in files.items()):raise ValueError("Verification replay differs; no overwrite")
        print("Byte-identical verification replay",len(checks),"checks PASS")
    else:
        write_version(out,files);print(len(checks),"saved-artifact checks PASS; no fitting; original inputs unchanged")

if __name__=="__main__":main()
