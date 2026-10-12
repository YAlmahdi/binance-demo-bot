"""Guarded invented-fixture boundary checks; no financial or real-market suites."""
from pathlib import Path
import argparse
import hashlib
import json
import sys
import time
import unittest

from verify_research_v2 import guard_for
from verify_v2_contracts import RecordedResult

ROOT = Path(__file__).resolve().parents[1]
SUITES = (
    "test_v2_loader_boundary", "test_v2_contracts",
    "test_research_v2.ConfigurationTests", "test_research_v2.FeatureTests",
    "test_research_v2.SafetyTests", "test_indicators",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-directory", required=True)
    args = parser.parse_args()
    supplied_report = Path(args.report_directory).absolute()
    report = supplied_report.resolve()
    if (report.parent != ROOT / "reports/research-v2" or not report.is_dir()
            or supplied_report.is_symlink() or getattr(supplied_report.lstat(), "st_file_attributes", 0) & 0x400
            or not report.name.startswith("V2-LOADER-BOUNDARY-SYNTHETIC-")):
        parser.error("Pre-created isolated boundary evidence folder required")
    blocked = []
    base_guard = guard_for(report, event_log=blocked)

    def guard(event, values):
        if event.startswith("socket.") or event in ("http.client.connect", "os.system"):
            blocked.append(event)
            raise RuntimeError("Boundary verification prohibits network and external workers")
        if event == "open" and isinstance(values[0], (str, bytes)):
            path = Path(values[0]).resolve()
            if path.is_relative_to(ROOT / "logs"):
                raise RuntimeError("Private logs prohibited")
            if path.suffix == ".pyc" and any(path.is_relative_to(ROOT / folder)
                                            for folder in ("src", "tests", "scripts")):
                raise FileNotFoundError("Use verified source rather than local bytecode caches")
        base_guard(event, values)

    sys.addaudithook(guard)
    sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests"), str(ROOT / "scripts")]
    started = time.monotonic()
    suites = [unittest.defaultTestLoader.loadTestsFromName(name) for name in SUITES]
    r = unittest.TextTestRunner(verbosity=2, resultclass=RecordedResult).run(unittest.TestSuite(suites))
    failures, errors, skipped = len(r.failures), len(r.errors), len(r.skipped)
    tested = [p for p in sorted((ROOT / "src/demo_futures/research_v2").glob("*.py"))]
    tested += [ROOT / "src/demo_futures" / (name + ".py")
               for name in ("data", "indicators", "strategy", "risk", "backtest")]
    tested += [ROOT / "tests" / (name + ".py")
               for name in ("test_v2_loader_boundary", "test_v2_contracts", "test_research_v2", "test_indicators")]
    tested += [Path(__file__), ROOT / "scripts/verify_research_v2.py", ROOT / "scripts/verify_v2_contracts.py"]
    record = {
        "scope": "INVENTED_SYNTHETIC_ONLY", "suites": SUITES,
        "python_version": sys.version.split()[0], "tests_run": r.testsRun,
        "passed": r.testsRun - failures - errors - skipped,
        "failures": failures, "errors": errors, "skipped": skipped,
        "test_ids": r.executed, "failure_ids": [t.id() for t, _ in r.failures],
        "error_ids": [t.id() for t, _ in r.errors], "blocked_runtime_events": blocked,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "successful": r.wasSuccessful() and not blocked,
        "source_test_runner_sha256": {
            p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in tested},
        "excludes_financial_label_and_portfolio_test_suites": True,
        "risk_clearance": "NOT CLEARED",
    }
    attempt = len(list(report.glob("synthetic-tests-attempt-*.json"))) + 1
    with (report / f"synthetic-tests-attempt-{attempt:02d}.json").open("x", encoding="utf-8") as f:
        json.dump(record, f, indent=2)
        f.write("\n")
    return 0 if record["successful"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
