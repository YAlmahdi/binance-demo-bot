"""Guarded synthetic authorization/query declarations, never SQL or real sources."""
from pathlib import Path
import argparse
import hashlib
import json
import sys
import unittest

from verify_v2_adapter_access_contract import make_guard, SUITES as REGRESSIONS
from verify_v2_contracts import RecordedResult

ROOT = Path(__file__).resolve().parents[1]
NEW_SUITES = ("test_v2_authorization_binding", "test_v2_fixed_query_plan")
SUITES = NEW_SUITES + REGRESSIONS
SOURCES = ("src/demo_futures/research_v2/authorization_binding.py",
           "src/demo_futures/research_v2/fixed_query_plan.py",
           "tests/test_v2_authorization_binding.py", "tests/test_v2_fixed_query_plan.py",
           "scripts/verify_v2_authorization_query.py")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-directory", required=True)
    args = parser.parse_args()
    raw = Path(args.report_directory).absolute()
    report = raw.resolve()
    if (raw != report or report.parent != ROOT / "reports/research-v2"
            or not report.name.startswith("V2-AUTHORIZATION-QUERY-")
            or not report.is_dir() or report.is_symlink()):
        parser.error("Prepared versioned authorization/query evidence directory required")
    blocked = []
    sys.dont_write_bytecode = True
    sys.addaudithook(make_guard(report, blocked))
    sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests"), str(ROOT / "scripts")]
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(name) for name in SUITES)
    tested = unittest.TextTestRunner(verbosity=2, resultclass=RecordedResult).run(suite)
    failures, errors, skipped = len(tested.failures), len(tested.errors), len(tested.skipped)
    counts = {name: sum(t.startswith(name + ".") for t in tested.executed) for name in NEW_SUITES}
    baseline = json.loads((report / "source-baseline.json").read_text(encoding="utf-8"))
    preserved = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == h
                 for p, h in baseline["protected_sha256"].items()}
    record = {
        "scope": "INVENTED_APPROVAL_AND_INERT_SQL_ONLY", "suites": SUITES,
        "tests_run": tested.testsRun, "new_tests_by_module": counts,
        "new_tests": sum(counts.values()), "regression_tests": tested.testsRun - sum(counts.values()),
        "passed": tested.testsRun - failures - errors - skipped,
        "failures": failures, "errors": errors, "skipped": skipped,
        "test_ids": tested.executed, "failure_ids": [t.id() for t, _ in tested.failures],
        "error_ids": [t.id() for t, _ in tested.errors], "blocked_runtime_events": blocked,
        "sql_executions_or_fixture_connections": 0, "protected_code_preserved": preserved,
        "source_sha256": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in SOURCES},
        "successful": tested.wasSuccessful() and not skipped and not blocked and all(preserved.values()),
        "limits": ["Invented approval is not user authorization", "No ledger/snapshot authenticity",
                   "No real schema, SQLite execution, filesystem or physical-page isolation verified",
                   "No financial or model research"],
    }
    attempt = len(list(report.glob("synthetic-tests-attempt-*.json"))) + 1
    with (report / f"synthetic-tests-attempt-{attempt:02d}.json").open("x", encoding="utf-8") as f:
        json.dump(record, f, indent=2)
        f.write("\n")
    return 0 if record["successful"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
