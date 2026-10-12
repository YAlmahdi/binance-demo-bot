"""Task-scoped guarded synthetic contract/regression verification; no real inputs."""
from pathlib import Path
import argparse
import hashlib
import json
import sys
import unittest
from verify_research_v2 import guard_for

ROOT = Path(__file__).resolve().parents[1]
SUITES = ("test_v2_contracts", "test_research_v2", "test_indicators", "test_risk")


class RecordedResult(unittest.TextTestResult):
    def startTest(self, test):
        self.executed.append(test.id())
        super().startTest(test)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.executed = []


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-directory", required=True)
    args = parser.parse_args()
    report = Path(args.report_directory).resolve()
    if (report.parent != ROOT / "reports/research-v2"
            or not report.name.startswith("V2-CONTRACT-HARDENING-") or not report.is_dir()
            or report.is_symlink()):
        parser.error("Pre-created versioned contract-only evidence folder required")
    blocked = []
    base_guard = guard_for(report, event_log=blocked)

    def guard(event, values):
        if event.startswith("socket.") or event in ("http.client.connect", "os.system"):
            blocked.append(event)
            raise RuntimeError("Synthetic verification prohibits network or external workers")
        if event == "open" and isinstance(values[0], (str, bytes)):
            p = Path(values[0]).resolve()
            if p.is_relative_to(ROOT / "logs"):
                raise RuntimeError("Private logs prohibited")
        base_guard(event, values)

    sys.addaudithook(guard)
    sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests"), str(ROOT / "scripts")]
    suites = [unittest.defaultTestLoader.loadTestsFromName(name) for name in SUITES]
    r = unittest.TextTestRunner(verbosity=2, resultclass=RecordedResult).run(unittest.TestSuite(suites))
    failures, errors, skipped = len(r.failures), len(r.errors), len(r.skipped)
    record = {"scope": "INVENTED_SYNTHETIC_ONLY", "suites": SUITES,
              "tests_run": r.testsRun, "passed": r.testsRun - failures - errors - skipped,
              "failures": failures, "errors": errors, "skipped": skipped,
              "test_ids": r.executed, "failure_ids": [t.id() for t, _ in r.failures],
              "error_ids": [t.id() for t, _ in r.errors], "blocked_runtime_events": blocked,
              "successful": r.wasSuccessful() and not blocked,
              "sources_sha256": {str(p.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in sorted((ROOT / "src/demo_futures/research_v2").glob("*.py"))},
              "test_and_runner_sha256": {str(p.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in [ROOT / "scripts/verify_v2_contracts.py"] + [ROOT / "tests" / (s + ".py") for s in SUITES]}}
    attempt = len(list(report.glob("synthetic-tests-attempt-*.json"))) + 1
    with (report / f"synthetic-tests-attempt-{attempt:02d}.json").open("x", encoding="utf-8") as f:
        json.dump(record, f, indent=2); f.write("\n")
    return 0 if record["successful"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
