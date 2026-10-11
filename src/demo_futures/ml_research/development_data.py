"""Read existing engineering CSVs; never regenerate labels or inspect locked periods."""
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
import csv
import json
import math
from ..backtest import Trade
from .features import FeatureRow
from .labels import LabelResult
from .config import START, DEV_END, FOLDS, BUFFER, FEATURE_NAMES
from .dataset import file_hash
from .splits import split_manifest, sufficiency

ENGINEERING_ID = "engineering-65fb33dd258060c94ffd"


@dataclass(frozen=True)
class EngineeringRows:
    features: object
    labels: object
    splits: dict
    provenance: dict


@dataclass(frozen=True)
class TrainingPartition:
    fold: int
    features: tuple
    labels: tuple

    def validate(self):
        if type(self.fold) is not int or not 1 <= self.fold <= 3:
            raise PermissionError("Only three fixed development folds may be fitted")
        begin, _ = FOLDS[self.fold-1]
        if len(self.features) != len(self.labels) or not self.labels:
            raise ValueError("Training identity mismatch")
        ids = []
        for f, r in zip(self.features, self.labels):
            validate_feature(f)
            if (f.row_id != r.row_id or f.decision_time != r.decision_time or f.symbol != r.symbol
                    or r.status != "VALID" or r.y not in (0, 1)
                    or not START <= r.decision_time < begin
                    or r.interval_start != r.decision_time+1
                    or r.interval_end != r.interval_start+BUFFER
                    or r.interval_end > begin-BUFFER):
                raise PermissionError("Training contains unavailable, unpurged or evaluation information")
            ids.append(r.row_id)
        if len(set(ids)) != len(ids) or ids != [r.row_id for r in sorted(self.labels, key=lambda r:(r.decision_time,r.symbol))]:
            raise ValueError("Training rows must be unique and chronological")
        gate = sufficiency(self.labels, "train")
        if gate["status"] != "SUFFICIENT":
            raise ValueError("INSUFFICIENT training sample; frozen boundaries cannot be moved")
        return gate


def validate_feature(f):
    if (f.symbol not in ("BTCUSDT", "ETHUSDT") or f.row_id != f"{f.symbol}:{f.decision_time}"
            or not START <= f.decision_time < DEV_END or f.available_at != f.decision_time
            or len(f.values) != 16 or any(not math.isfinite(v) for v in f.values)
            or f.values[14] != int(f.symbol == "ETHUSDT") or f.values[15] not in (0,1)):
        raise ValueError("Invalid causal development feature schema")


def load_engineering(root):
    directory = Path(root)/"artifacts/ml-research"/ENGINEERING_ID
    manifest = json.loads((directory/"manifest.json").read_text())
    allowed = {"config.json", "provenance.json", "splits.json", "features.csv", "labels.csv", "isolated-trades.csv"}
    if set(manifest["files_sha256"]) != allowed:
        raise ValueError("Unexpected engineering payload")
    for n, expected in manifest["files_sha256"].items():
        if file_hash(directory/n) != expected:
            raise ValueError("Engineering payload hash mismatch")
    def records(name):
        with (directory/name).open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))
    features = {}
    for row in records("features.csv"):
        f = FeatureRow(row["row_id"], row["symbol"], int(row["decision_time"]),
                       int(row["available_at"]), tuple(float(row[n]) for n in FEATURE_NAMES))
        validate_feature(f)
        if f.row_id in features: raise ValueError("Duplicate feature")
        features[f.row_id] = f
    trades = {}
    integer = {"signal_time", "entry_time", "exit_time", "funding_mark_fallbacks", "uncertain_funding_credits_skipped"}
    strings = {"symbol", "side", "entry_reason", "exit_reason"}
    for row in records("isolated-trades.csv"):
        if row["row_id"] in trades: raise ValueError("Duplicate journal row")
        t = Trade(**{n: row[n] if n in strings else int(row[n]) if n in integer else Decimal(row[n])
                     for n in Trade.__dataclass_fields__})
        if not START <= t.signal_time < t.entry_time <= t.exit_time < DEV_END:
            raise PermissionError("Journal contains non-development outcomes")
        if abs(t.gross_pnl-t.slippage_cost-t.fees-t.funding_cost-t.net_pnl) > Decimal("1e-12"):
            raise ArithmeticError("Saved label financial ledger mismatch")
        trades[row["row_id"]] = t
    labels = {}
    for row in records("labels.csv"):
        r = LabelResult(row["row_id"], row["symbol"], int(row["decision_time"]),
                        int(row["interval_start"]), int(row["interval_end"]), row["status"], row["reason"],
                        int(row["y"]) if row["y"] else None, trades.get(row["row_id"]))
        if r.row_id in labels or r.row_id not in features: raise ValueError("Label identity mismatch")
        f = features[r.row_id]
        if (f.symbol != r.symbol or f.decision_time != r.decision_time or r.interval_start != r.decision_time+1
                or r.interval_end != r.interval_start+BUFFER): raise ValueError("Label timing mismatch")
        if r.status == "VALID":
            if (r.trade is None or r.interval_end > DEV_END or r.y != int(r.trade.net_pnl>0)
                    or r.trade.signal_time != r.decision_time or r.trade.symbol != r.symbol
                    or r.trade.side != ("LONG" if f.values[15] else "SHORT")):
                raise ValueError("Saved valid label parity mismatch")
        elif r.y is not None or r.trade is not None:
            raise ValueError("Excluded labels cannot carry outcomes")
        labels[r.row_id] = r
    if set(features) != set(labels) or set(trades) != {n for n,r in labels.items() if r.status=="VALID"}:
        raise ValueError("Engineering row membership mismatch")
    splits = json.loads((directory/"splits.json").read_text())
    if splits != split_manifest(labels.values()): raise ValueError("Saved frozen split manifest mismatch")
    return EngineeringRows(MappingProxyType(features), MappingProxyType(labels), splits,
                           json.loads((directory/"provenance.json").read_text()))


def training_partition(rows, fold):
    if type(fold) is not int or not 1 <= fold <= 3: raise PermissionError("Locked or unknown stage")
    split = rows.splits["folds"][fold-1]
    ids = split["train_ids"]
    partition = TrainingPartition(fold, tuple(rows.features[n] for n in ids), tuple(rows.labels[n] for n in ids))
    partition.validate()
    return partition


def evaluation_rows(rows, fold):
    if type(fold) is not int or not 1 <= fold <= 3: raise PermissionError("Locked or unknown stage")
    begin, end = FOLDS[fold-1]
    ids = rows.splits["folds"][fold-1]["evaluation_ids"]
    result = tuple(rows.labels[n] for n in ids)
    if any(r.status!="VALID" or not begin<=r.decision_time<end or r.interval_end>end for r in result):
        raise PermissionError("Evaluation membership violates fixed development boundaries")
    return result
