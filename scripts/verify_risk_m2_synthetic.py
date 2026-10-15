"""Guarded source-bound M2/M1 synthetic verification; no real data or integration."""
import argparse
from datetime import datetime, timezone
from decimal import DefaultContext, getcontext
import hashlib
import json
import os
from pathlib import Path
import sys
import unittest

import verify_risk_m1_synthetic as m1

ROOT = Path(__file__).resolve().parents[1]
NEW_PATHS = ("src/demo_futures/risk_remediation/plan_budget_contract.py",
             "tests/test_risk_plan_budget_contract.py", "scripts/verify_risk_m2_synthetic.py")
PATHS = m1.PATHS + NEW_PATHS
SUITES = ("test_risk_plan_budget_contract",) + m1.SUITES


def hashes():
    return {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in PATHS}


def make_guard(report, receipt, blocked):
    base = m1.make_guard(report, receipt, blocked)
    extra = {(ROOT / p).resolve() for p in NEW_PATHS}
    def guard(event, args):
        # Expand only the exact read-only source allowlist; all denials remain.
        if event == "open" and type(args[0]) is not int:
            path = Path(os.fsdecode(args[0])).resolve()
            mode, flags = args[1:3]
            writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
            if path in extra and not writing:
                return
        base(event, args)
    return guard


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-directory", required=True)
    parser.add_argument("--attempt", type=int, required=True)
    args = parser.parse_args()
    raw = Path(args.report_directory).absolute()
    report = raw.resolve()
    if (raw != report or report.parent != ROOT / "reports/risk-remediation"
            or not report.name.startswith("M2-SYNTHETIC-") or not report.is_dir()
            or report.is_symlink() or args.attempt < 1):
        parser.error("Prepared versioned M2 evidence directory and positive attempt required")
    receipt = report / f"attempt-{args.attempt:02d}.json"
    if receipt.exists():
        parser.error("Preserve previous receipts; choose a fresh attempt")
    # Read only this task's fixed starting-code baseline before installing guard.
    baseline = json.loads((report / "starting-identities.json").read_text(encoding="utf-8"))
    if set(baseline) != set(m1.PATHS):
        parser.error("Exact reviewed M1 dependency inventory required")
    blocked = []
    sys.dont_write_bytecode = True
    sys.addaudithook(make_guard(report, receipt, blocked))
    sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
    before = hashes()
    results, contexts = [], []
    for name in SUITES:
        context_before = {"default": m1.context_state(DefaultContext), "current": m1.context_state(getcontext())}
        suite = unittest.defaultTestLoader.loadTestsFromName(name)
        result = unittest.TextTestRunner(verbosity=2, resultclass=m1.RecordedResult).run(suite)
        results.append(result)
        contexts.append({"suite": name, "before": context_before,
            "after": {"default": m1.context_state(DefaultContext), "current": m1.context_state(getcontext())}})
    after = hashes()
    preserved = {p: baseline[p] == after[p] for p in m1.PATHS}
    context_ok = all(c["before"]["default"] == c["after"]["default"] and
        all(c["before"]["current"][k] == c["after"]["current"][k] for k in c["before"]["current"] if k != "flags") and
        (c["suite"] == "test_risk" or c["before"]["current"]["flags"] == c["after"]["current"]["flags"]) for c in contexts)
    record = {"scope": "M2_SYNTHETIC_DIAGNOSTIC_ONLY", "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "environment": {"python": sys.version, "executable": sys.executable, "platform": sys.platform, "bytecode_writes": False},
        "suites": [{"name": name, "tests_run": r.testsRun,
            "passed": sum(o["outcome"] == "PASS" for o in r.outcomes),
            "failures": len(r.failures), "errors": len(r.errors), "skipped": len(r.skipped),
            "test_ids": r.ids, "outcomes": r.outcomes} for name, r in zip(SUITES, results)],
        "tests_run": sum(r.testsRun for r in results),
        "passed": sum(sum(o["outcome"] == "PASS" for o in r.outcomes) for r in results),
        "failures": sum(len(r.failures) for r in results), "errors": sum(len(r.errors) for r in results),
        "skipped": sum(len(r.skipped) for r in results), "blocked_events": blocked,
        "source_before": before, "source_after": after, "starting_dependencies_preserved": preserved,
        "in_run_source_preserved": before == after, "decimal_contexts": contexts,
        "context_policy_preserved": context_ok,
        "guard": "M1 exact-source/read-only runtime guard plus three exact M2 source reads; one exclusive receipt write",
        "limitations": ["Not an OS sandbox", "Synthetic binding/decomposition is unauthenticated",
            "No financial/risk clearance or resource policy established", "Legacy risk tests may set arithmetic flags"],
        "successful": all(r.wasSuccessful() and not r.skipped for r in results) and not blocked
            and before == after and all(preserved.values()) and context_ok}
    with receipt.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, indent=2)
        stream.write("\n")
    return 0 if record["successful"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
