"""Deterministic, inactive research artifacts and frozen-input verification."""
from dataclasses import asdict
import csv
import io
import json
from pathlib import Path

from .config import canonical, digest, FEATURE_NAMES
from .dataset import file_hash


def verify_inputs(root, witness):
    changed = []
    for name, expected in witness.items():
        path = Path(root) / name
        if not path.is_file() or file_hash(path) != expected:
            changed.append(name)
    if changed:
        raise ValueError("Protected offline inputs changed: " + ", ".join(changed))
    return {"status": "UNCHANGED", "files_checked": len(witness), "sha256": witness}


def csv_text(columns, rows):
    handle = io.StringIO(newline="")
    writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return handle.getvalue()


def feature_csv(features):
    columns = ("row_id", "symbol", "decision_time", "available_at") + FEATURE_NAMES
    return csv_text(columns, ({"row_id": r.row_id, "symbol": r.symbol,
                              "decision_time": r.decision_time, "available_at": r.available_at,
                              **dict(zip(FEATURE_NAMES, r.values))} for r in features))


def label_csv(labels):
    columns = ("row_id", "symbol", "decision_time", "interval_start", "interval_end",
               "status", "reason", "y", "outcome_time", "net_pnl", "net_risk_units", "exit_reason")
    rows = []
    for r in labels:
        record = {k: getattr(r, k) for k in columns[:8]}
        record.update({"y": r.y, "outcome_time": r.trade.exit_time if r.trade else None,
                       "net_pnl": r.trade.net_pnl if r.trade else None,
                       "net_risk_units": r.trade.net_pnl / r.trade.risk_budget if r.trade else None,
                       "exit_reason": r.trade.exit_reason if r.trade else None})
        rows.append(record)
    return csv_text(columns, rows)


def isolated_journal_csv(labels):
    from ..backtest import Trade
    columns = ("row_id",) + tuple(Trade.__dataclass_fields__)
    return csv_text(columns, ({"row_id": r.row_id, **asdict(r.trade)}
                              for r in labels if r.trade is not None))


def write_bundle(directory, files):
    """Exclusive new version; identical replay verifies every byte, never overwrites."""
    directory = Path(directory)
    allowed = {"config.json", "provenance.json", "features.csv", "labels.csv", "isolated-trades.csv",
               "splits.json", "audit.json", "report.md", "tests.json"}
    if not files or any(name not in allowed for name in files):
        raise ValueError("Artifact paths must be plain filenames")
    hashes = {name: digest_bytes(text.encode("utf-8")) for name, text in sorted(files.items())}
    manifest = canonical({"status": "OFFLINE_RESEARCH_ONLY", "execution_enabled": False,
                          "fitted_model": False, "files_sha256": hashes}) + "\n"
    payload = {**files, "manifest.json": manifest}
    if directory.exists():
        if set(p.name for p in directory.iterdir()) != set(payload):
            raise FileExistsError("Existing immutable bundle has different contents")
        if any((directory/name).read_bytes() != text.encode("utf-8") for name,text in payload.items()):
            raise FileExistsError("Existing immutable bundle differs; refusing overwrite")
        return hashes
    directory.mkdir(parents=True, exist_ok=False)
    for name, text in payload.items():
        with (directory/name).open("x", encoding="utf-8", newline="") as handle:
            handle.write(text)
    return hashes


def digest_bytes(value):
    import hashlib
    return hashlib.sha256(value).hexdigest()
