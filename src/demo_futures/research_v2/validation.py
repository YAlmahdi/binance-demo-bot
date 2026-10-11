"""Inert split/transform contracts. No split construction, scaler fitting or models."""
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import math
from .config import FEATURES, HOUR, HORIZON, SYMBOLS, BtcEthEncoder, timestamp, require_symbol
from .features import FeatureRow

def ids_hash(ids):
    values = tuple(ids)
    if not values or any(not isinstance(v, str) for v in values) or len(values) != len(set(values)):
        raise ValueError("Nonempty unique row identities required")
    return hashlib.sha256(json.dumps(sorted(values), separators=(",", ":")).encode()).hexdigest()

@dataclass(frozen=True)
class IntervalRow:
    symbol: str
    decision_time: int
    label_end: int

    def __post_init__(self):
        require_symbol(self.symbol); timestamp(self.decision_time); timestamp(self.label_end)
        if (self.decision_time + 1) % HOUR or self.label_end != self.decision_time + 1 + HORIZON:
            raise ValueError("Full conservative hourly opportunity horizon required")

    @property
    def row_id(self): return f"{self.symbol}:{self.decision_time}"
    @property
    def label_start(self): return self.decision_time + 1

@dataclass(frozen=True)
class DevelopmentWindow:
    """Synthetic caller-supplied boundaries only; no historical or hybrid calendar."""
    train_start: int
    evaluation_start: int
    evaluation_end: int
    evidence: str = "SYNTHETIC_ONLY"

    def __post_init__(self):
        for t in (self.train_start, self.evaluation_start, self.evaluation_end): timestamp(t)
        if (self.evidence != "SYNTHETIC_ONLY" or not self.train_start < self.evaluation_start < self.evaluation_end
                or any(t % HOUR for t in (self.train_start, self.evaluation_start, self.evaluation_end))):
            raise ValueError("Synthetic ordered hourly window required")

def partition_reason(row, window, stage):
    if stage not in ("train", "development_evaluation"):
        raise PermissionError("Confirmation/final and historical access unapproved")
    if stage == "train":
        if not window.train_start <= row.decision_time < window.evaluation_start:
            return "OUTSIDE_TRAIN"
        if row.label_end > window.evaluation_start:
            return "PURGED_OVERLAP"
        if row.label_end > window.evaluation_start - HORIZON:
            return "FOUR_HOUR_BUFFER"
    else:
        if not window.evaluation_start <= row.decision_time < window.evaluation_end:
            return "OUTSIDE_EVALUATION"
        if row.label_end > window.evaluation_end:
            return "INCOMPLETE_EVALUATION_HORIZON"
    return "ACCEPT"

def validate_partition(train_rows, evaluation_rows, window):
    """Validate supplied assignments; does not read or construct historical partitions."""
    train, evaluation = tuple(train_rows), tuple(evaluation_rows)
    all_rows = train + evaluation
    if len({r.row_id for r in all_rows}) != len(all_rows):
        raise ValueError("Duplicate or cross-partition row identity")
    if {r.decision_time for r in train} & {r.decision_time for r in evaluation}:
        raise ValueError("BTC/ETH decisions from one timestamp cannot cross partitions")
    for stage, rows in (("train", train), ("development_evaluation", evaluation)):
        if any(partition_reason(r, window, stage) != "ACCEPT" for r in rows):
            raise ValueError("Supplied partition violates chronology/purge/buffer")
        if list(rows) != sorted(rows, key=lambda r: (r.decision_time, r.symbol)):
            raise ValueError("Stable chronological BTC/ETH ordering required")
    return True

def sample_gate(rows, stage):
    if stage not in ("train", "development_evaluation"):
        raise PermissionError("Only synthetic development gate checks permitted")
    rows = tuple(rows)
    if len({r.row_id for r in rows}) != len(rows):
        raise ValueError("Duplicate samples cannot manufacture sufficiency")
    counts = Counter(r.symbol for r in rows)
    minimum, per_symbol = (1000, 300) if stage == "train" else (300, 100)
    # Joint timestamp grouping avoids counting BTC and ETH shocks twice.
    eligible_at, groups = -1, 0
    for t in sorted({r.decision_time for r in rows}):
        start = t + 1
        if start >= eligible_at:
            groups += 1; eligible_at = start + HORIZON
    checks = (len(rows) >= minimum, all(counts[s] >= per_symbol for s in SYMBOLS),
              stage == "train" or groups >= 60)
    return {"status": "SUFFICIENT" if all(checks) else "INSUFFICIENT",
            "rows": len(rows), "per_symbol": dict(counts), "joint_nonoverlapping_groups": groups,
            "minimum_rows": minimum, "minimum_per_symbol": per_symbol,
            "minimum_joint_groups": 0 if stage == "train" else 60}

@dataclass(frozen=True)
class TrainingReceipt:
    """Identity binding for manually supplied synthetic transform statistics."""
    row_ids: tuple[str, ...]
    row_ids_sha256: str
    window: DevelopmentWindow
    evidence: str = "SYNTHETIC_ONLY"
    stage: str = "train"

    def __post_init__(self):
        object.__setattr__(self, "row_ids", tuple(self.row_ids))
        if (self.stage != "train" or self.evidence != "SYNTHETIC_ONLY"
                or ids_hash(self.row_ids) != self.row_ids_sha256):
            raise ValueError("Training-only synthetic provenance required")
        rows=[]
        for identity in self.row_ids:
            try:
                symbol, time = identity.split(":")
                row = IntervalRow(symbol, int(time), int(time) + 1 + HORIZON)
            except (ValueError, TypeError):
                raise ValueError("Malformed training identity") from None
            if row.row_id != identity or partition_reason(row, self.window, "train") != "ACCEPT":
                raise ValueError("Evaluation/future or purged row in training provenance")
            rows.append(row)

@dataclass(frozen=True)
class TransformContract:
    """No fit method. Statistics must be provided explicitly by synthetic fixtures."""
    receipt: TrainingReceipt
    lower: tuple[float, ...]
    upper: tuple[float, ...]
    mean: tuple[float, ...]
    scale: tuple[float, ...]
    feature_names: tuple[str, ...] = FEATURES

    def __post_init__(self):
        for name in ("lower", "upper", "mean", "scale", "feature_names"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        if (self.feature_names != FEATURES or
                any(len(getattr(self,n)) != 8 for n in ("lower","upper","mean","scale"))):
            raise ValueError("Exactly eight continuous inputs plus unchanged symbol flag")
        if any(isinstance(x,bool) or not math.isfinite(x) for n in ("lower","upper","mean","scale") for x in getattr(self,n)):
            raise ValueError("Finite transform metadata required")
        if any(a>b or not a<=c<=b or d<=0 for a,b,c,d in zip(self.lower,self.upper,self.mean,self.scale)):
            raise ValueError("Invalid bounds/mean/scale; constant-scale fitting policy deferred")

@dataclass(frozen=True)
class TransformResult:
    status: str
    breaches: tuple[str, ...]
    values: tuple[float, ...] | None

def apply_transform(row, contract, expected_training_receipt):
    """Transform a synthetic vector only; provenance equality is required before use."""
    if contract.receipt != expected_training_receipt:
        raise ValueError("Wrong fold's training provenance")
    if row.status != "READY":
        return TransformResult("DATA_QUALITY", (), None)
    if row.values[-1] != BtcEthEncoder().encode(row.symbol):
        raise ValueError("Symbol indicator schema mismatch")
    breaches = tuple(FEATURES[i] for i,x in enumerate(row.values[:8])
                     if x < contract.lower[i] or x > contract.upper[i])
    if breaches:
        return TransformResult("OUT_OF_RANGE", breaches, None)
    values = tuple((x-mu)/scale for x,mu,scale in zip(row.values[:8],contract.mean,contract.scale)) + (row.values[-1],)
    if any(not math.isfinite(x) for x in values):
        return TransformResult("DATA_QUALITY", (), None)
    return TransformResult("IN_RANGE", (), values)

@dataclass(frozen=True)
class RangeDecision:
    symbol: str
    decision_time: int
    feature_eligible: bool
    abstained: bool
    breaches: tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "breaches", tuple(self.breaches))
        if (len(self.breaches) != len(set(self.breaches)) or any(n not in FEATURES[:8] for n in self.breaches)
                or (self.breaches and not self.abstained)):
            raise ValueError("Distinct continuous feature breaches require abstention")
        require_symbol(self.symbol); timestamp(self.decision_time)
        if ((self.decision_time+1)%HOUR or type(self.feature_eligible) is not bool
                or type(self.abstained) is not bool or (self.abstained and not self.feature_eligible)):
            raise ValueError("Causal eligibility/range decision required")

def abstention_gate(decisions, window, in_range_valid_rows):
    """Coverage denominator ignores future-label validity; immutable 25% research gate."""
    decisions=tuple(decisions)
    if len({(d.symbol,d.decision_time) for d in decisions})!=len(decisions):
        raise ValueError("Duplicate scheduled decisions")
    if any(not window.evaluation_start <= d.decision_time < window.evaluation_end for d in decisions):
        raise ValueError("Decision outside synthetic evaluation window")
    expected={(s,t-1) for t in range(window.evaluation_start+HOUR,window.evaluation_end+HOUR,HOUR) for s in SYMBOLS}
    if {(d.symbol,d.decision_time) for d in decisions} != expected:
        raise ValueError("Coverage requires every scheduled BTC/ETH pair, including causal exclusions")
    buckets={}; breaches_by_bucket={}; unattributed={}
    for d in decisions:
        block=(d.decision_time-window.evaluation_start)//(7*24*HOUR)
        for key in ("overall",d.symbol,f"{d.symbol}:block-{block}"):
            counts=buckets.setdefault(key,[0,0,0])
            counts[0]+=1;counts[1]+=int(d.feature_eligible);counts[2]+=int(d.abstained)
            breaches_by_bucket.setdefault(key, Counter()).update(d.breaches)
            unattributed[key]=unattributed.get(key,0)+int(d.abstained and not d.breaches)
    coverage={}
    failed=False
    for key,(scheduled,eligible,abstained) in sorted(buckets.items()):
        small=eligible==0 or (":block-" in key and eligible<50)
        excess=eligible>0 and 4*abstained>eligible
        coverage[key]={"scheduled":scheduled,"feature_eligible":eligible,"abstained":abstained,
                       "rate":abstained/eligible if eligible else None,
                       "status":"TOO_SMALL" if small else ("INSUFFICIENT" if excess else "WITHIN_LIMIT"),
                       "per_feature_breaches":dict(breaches_by_bucket[key]),
                       "unattributed_synthetic_abstentions":unattributed[key]}
        failed |= excess and not small
    # Missing symbols cannot silently pass coverage.
    failed |= any(s not in coverage or coverage[s]["feature_eligible"]==0 for s in SYMBOLS)
    rows=tuple(in_range_valid_rows)
    allowed={(d.symbol,d.decision_time) for d in decisions if d.feature_eligible and not d.abstained}
    if any((r.symbol,r.decision_time) not in allowed or partition_reason(r,window,"development_evaluation")!="ACCEPT" for r in rows):
        raise ValueError("In-range sample identities/intervals do not match coverage")
    gate=sample_gate(rows,"development_evaluation")
    return {"status":"INSUFFICIENT" if failed or gate["status"]=="INSUFFICIENT" else "SUFFICIENT",
            "coverage":coverage,"in_range_sample_gate":gate,
            "new_regime_interpretation":"Training-support limitation, not predictive success or failure"}
