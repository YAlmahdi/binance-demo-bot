"""Descriptive development metrics: no fitting, threshold search or later-period access."""
from collections import Counter
import numpy as np
from sklearn.metrics import roc_auc_score, average_precision_score
from .config import START, DEV_END
from .splits import nonoverlapping
from .audit import payoff_summary

DAY = 86_400_000


def checked(labels, probabilities):
    labels = tuple(labels); p = np.asarray(probabilities,dtype=np.float64)
    if (not labels or p.shape != (len(labels),) or not np.isfinite(p).all()
            or (p<0).any() or (p>1).any() or len({r.row_id for r in labels})!=len(labels)
            or any(r.status!="VALID" or r.y not in (0,1) or not START<=r.decision_time<DEV_END
                   or r.interval_end>DEV_END for r in labels)):
        raise ValueError("Metrics require aligned valid development rows and finite probabilities")
    return labels,np.asarray([r.y for r in labels],dtype=np.int64),p


def losses(y,p):
    with np.errstate(divide="ignore"):
        ll = -np.log(np.where(y==1,p,1-p))
    return ll,(p-y)**2


def payoff_bucket_uncertainty(labels):
    if not labels:
        return {"status":"INSUFFICIENT: empty bucket"}
    days=np.asarray([r.decision_time//DAY for r in labels]);unique=np.unique(days)
    if len(unique)<10:
        return {"status":"INSUFFICIENT: fewer than 10 UTC blocks","blocks":len(unique),"resamples":1000,"seed":42}
    sums=np.asarray([[len(idx),sum(labels[i].y for i in idx),sum(float(labels[i].trade.net_pnl) for i in idx),
                      sum(float(labels[i].trade.net_pnl/labels[i].trade.risk_budget) for i in idx)]
                     for d in unique for idx in [np.where(days==d)[0]]])
    rng=np.random.default_rng(42);sampled=sums[rng.integers(0,len(unique),size=(1000,len(unique)))].sum(axis=1)
    values=sampled[:,1:]/sampled[:,0,None]
    return {"status":"ESTIMATED","blocks":len(unique),"resamples":1000,"seed":42,
            "ci_95":{name:[float(v) for v in np.quantile(values[:,i],[.025,.975],method="linear")]
                     for i,name in enumerate(("win_fraction","average_net_pnl","mean_net_risk_units"))},
            "note":"Paired UTC-block bootstrap, few blocks and serial dependence limit evidence"}


def calibration(labels, probabilities):
    labels,y,p = checked(labels,probabilities)
    bucket = np.minimum((p*10).astype(int),9)
    rows=[]; ece=0
    for k in range(10):
        indexes=np.where(bucket==k)[0]; count=len(indexes)
        pred=float(p[indexes].mean()) if count else None
        observed=float(y[indexes].mean()) if count else None
        if count: ece += count/len(y)*abs(pred-observed)
        pay = payoff_summary([labels[i] for i in indexes])
        rows.append({"lower": k/10,"upper": (k+1)/10,"upper_inclusive": k==9,"rows":count,
                     "status":"SUFFICIENT" if count>=10 else "INSUFFICIENT / sparse (<10)",
                     "predicted_mean":pred,"observed_win_fraction":observed,"isolated_payoff":pay,
                     "uncertainty":payoff_bucket_uncertainty([labels[i] for i in indexes])})
    return {"equal_width_buckets":rows,"expected_calibration_error":float(ece),
            "note":"Fixed buckets, overlapping outcomes; no calibrator fitted and no threshold optimized"}


def scores(labels, probabilities):
    labels,y,p=checked(labels,probabilities); ll,brier=losses(y,p)
    hard=(p>=.5).astype(int); tp=int(((hard==1)&(y==1)).sum()); tn=int(((hard==0)&(y==0)).sum())
    fp=int(((hard==1)&(y==0)).sum()); fn=int(((hard==0)&(y==1)).sum())
    counts=Counter(int(v) for v in y)
    return {"rows":len(y),"class_0":counts[0],"class_1":counts[1],
            "log_loss":float(ll.mean()) if np.isfinite(ll).all() else None,
            "log_loss_status":"FINITE" if np.isfinite(ll).all() else "INFINITE (hard baseline assigned zero to observed class)",
            "brier_score":float(brier.mean()),"accuracy_at_0_5":float((hard==y).mean()),
            "confusion_at_0_5":{"TP":tp,"TN":tn,"FP":fp,"FN":fn},
            "precision_at_0_5":tp/(tp+fp) if tp+fp else None,"recall_at_0_5":tp/(tp+fn) if tp+fn else None,
            "roc_auc":float(roc_auc_score(y,p)) if len(counts)==2 else None,
            "average_precision":float(average_precision_score(y,p)) if counts[1] else None,
            "admitted_at_frozen_0_65":int((p>=.65).sum()),"calibration":calibration(labels,p)}


def block_uncertainty(labels, probabilities, prior_probabilities):
    labels,y,p=checked(labels,probabilities); _,_,prior=checked(labels,prior_probabilities)
    ll,brier=losses(y,p); prior_ll,prior_brier=losses(y,prior)
    if not np.isfinite(ll).all() or not np.isfinite(prior_ll).all():
        return {"status":"INSUFFICIENT: nonfinite loss","resamples":1000,"seed":42}
    days=np.asarray([r.decision_time//DAY for r in labels]); unique=np.unique(days)
    if len(unique)<10:
        return {"status":"INSUFFICIENT: fewer than 10 UTC blocks","blocks":len(unique),"resamples":1000,"seed":42}
    # Aggregate paired symbols and policies in each UTC block. Keep unequal block counts.
    sums=np.asarray([[len(idx),ll[idx].sum(),brier[idx].sum(),(prior_ll[idx]-ll[idx]).sum(),
                      (prior_brier[idx]-brier[idx]).sum()] for d in unique for idx in [np.where(days==d)[0]]])
    rng=np.random.default_rng(42); sampled=sums[rng.integers(0,len(unique),size=(1000,len(unique)))].sum(axis=1)
    values=sampled[:,1:]/sampled[:,0,None]
    names=("model_log_loss","model_brier","prior_minus_model_log_loss","prior_minus_model_brier")
    intervals={n:[float(v) for v in np.quantile(values[:,i],[.025,.975],method="linear")] for i,n in enumerate(names)}
    return {"status":"ESTIMATED","blocks":len(unique),"resamples":1000,"seed":42,
            "ci_95":intervals,"unit":"24h UTC blocks; both symbols and both policies paired",
            "limitations":"10-day folds have few blocks; serial regimes and repeated expanding training remain dependent"}


def compare(labels, probabilities, prior_probabilities):
    labels,y,p=checked(labels,probabilities); _,_,prior=checked(labels,prior_probabilities)
    majority=(prior>.5).astype(float)  # deterministic tie -> class 0, training information only
    results={"model":scores(labels,p),"training_prevalence":scores(labels,prior),"majority_class":scores(labels,majority)}
    uncertainty=block_uncertainty(labels,p,prior)
    improvement=results["training_prevalence"]["log_loss"]-results["model"]["log_loss"]
    percent=improvement/results["training_prevalence"]["log_loss"]*100
    ci=uncertainty.get("ci_95",{}).get("prior_minus_model_log_loss")
    evidence="INSUFFICIENT" if ci is None or ci[0]<=0<=ci[1] else "PASS" if ci[0]>0 else "FAIL"
    nonoverlap=set(nonoverlapping(labels)); idx=[i for i,r in enumerate(labels) if r.row_id in nonoverlap]
    return {"policies":results,"uncertainty":uncertainty,"log_loss_improvement_pct":percent,
            "predictive_gates":{"log_loss_improves_at_least_1pct":"PASS" if percent>=1 else "FAIL",
                "brier_no_worse":"PASS" if results["model"]["brier_score"]<=results["training_prevalence"]["brier_score"] else "FAIL",
                "positive_paired_log_loss_evidence":evidence,
                "selection_validation_calibration_gate":"LOCKED / NOT EVALUATED"},
            "nonoverlap_sensitivity":{"rows":len(idx),"model":scores([labels[i] for i in idx],p[idx]),
                "training_prevalence":scores([labels[i] for i in idx],prior[idx])},
            "interpretation":"Predictive loss is scored on isolated labels; it is not shared-portfolio profitability"}
