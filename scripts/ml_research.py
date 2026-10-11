"""Explicit approved engineering stage only. No train/evaluate/execute command."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import platform
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "src"))
from demo_futures.ml_research.safety import offline_guard


def prepare_development(root=ROOT):
    offline_guard(root)
    from demo_futures.ml_research.artifacts import (verify_inputs, write_bundle, feature_csv,
                                                   label_csv, isolated_journal_csv)
    from demo_futures.ml_research.audit import development_audit, markdown_report
    from demo_futures.ml_research.config import ExperimentConfig, canonical, digest
    from demo_futures.ml_research.dataset import file_hash, load_development
    from demo_futures.ml_research.labels import label_opportunity
    from demo_futures.ml_research.opportunities import enumerate_opportunities
    from demo_futures.ml_research.splits import split_manifest
    root = Path(root).resolve()
    witness = json.loads((root / "artifacts/ml-research/engineering-input-witness.json").read_text(encoding="utf-8"))
    verify_inputs(root, witness)
    collection = json.loads((root / "reports/historical-90d/collection.json").read_text(encoding="utf-8"))
    for name, expected in collection["frozen_source_hashes"].items():
        if file_hash(root / "src/demo_futures" / name) != expected:
            raise ValueError("Frozen source differs from historical collection provenance")
    tests = root / "reports/ml-research/engineering-tests.json"
    if not tests.is_file():
        raise ValueError("Run offline engineering tests before preparation")
    test_evidence = json.loads(tests.read_text(encoding="utf-8"))
    if test_evidence["failures"] or test_evidence["errors"]:
        raise ValueError("Engineering test failures must be resolved first")
    data = load_development(root / "data/research-90d.sqlite3", collection["database_sha256"])
    config = ExperimentConfig().manifest()
    source_paths = sorted((root / "src/demo_futures/ml_research").glob("*.py"))
    source_paths += [root / "scripts/ml_research.py", root / "scripts/verify_phase4a.py"]
    source_paths += sorted((root / "tests").glob("test_ml_*.py"))
    provenance = {"protected_inputs": verify_inputs(root, witness),
                  "research_code_sha256": {p.relative_to(root).as_posix():file_hash(p) for p in source_paths},
                  "proposal_sha256": file_hash(root / "docs/PHASE4A_RESEARCH_PROPOSAL.md"),
                  "python_version": platform.python_version(), "dependencies": "Python standard library only",
                  "database_sha256": data.database_hash, "config_sha256": digest(config)}
    if test_evidence["research_code_sha256"] != provenance["research_code_sha256"]:
        raise ValueError("Tests must verify exactly the current research source version")
    experiment_id = "engineering-" + digest(provenance)[:20]
    opportunities, features, counts = enumerate_opportunities(data.candles)
    print("Development opportunity enumeration complete:", len(opportunities), flush=True)
    labels = tuple(label_opportunity(op, data.candles[op.symbol], data.funding[op.symbol],
                                     data.funding_gaps[op.symbol]) for op in opportunities)
    splits = split_manifest(labels)
    provenance["post_processing_verification"] = verify_inputs(root, witness)
    report = development_audit(data, opportunities, features, labels, splits, counts, provenance)
    artifact_files = {"config.json": canonical(config)+"\n", "provenance.json": canonical(provenance)+"\n",
                      "features.csv": feature_csv(features), "labels.csv": label_csv(labels),
                      "isolated-trades.csv": isolated_journal_csv(labels),
                      "splits.json": canonical(splits)+"\n"}
    write_bundle(root / "artifacts/ml-research" / experiment_id, artifact_files)
    report_files = {"audit.json": canonical(report)+"\n", "report.md": markdown_report(report, experiment_id)}
    report_files["tests.json"] = canonical(test_evidence)+"\n"
    write_bundle(root / "reports/ml-research" / experiment_id, report_files)
    verify_inputs(root, witness)
    print("Experiment:", experiment_id)
    print("Label counts:", report["label_counts"])
    for fold in report["folds"]:
        print("Fold",fold["fold"],"train",fold["train_gate"]["status"],
              fold["train_gate"]["row_count"],"evaluation",fold["evaluation_gate"]["status"],
              fold["evaluation_gate"]["row_count"])
    print("Inputs unchanged. No fitting/predictions. Validation/final locked.")
    return experiment_id


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("prepare-development",))
    parser.parse_args()
    prepare_development()


if __name__ == "__main__":
    main()
