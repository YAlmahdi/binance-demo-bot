"""Guarded metadata-only verification. No SQLite fixtures or saved-market inputs."""
from pathlib import Path
import argparse
import hashlib
import json
import sys
import unittest

from verify_research_v2 import guard_for
from verify_v2_contracts import RecordedResult

ROOT = Path(__file__).resolve().parents[1]
SUITES = (
    "test_v2_adapter_access_contract", "test_v2_loader_boundary", "test_v2_contracts",
    "test_research_v2.ConfigurationTests", "test_research_v2.FeatureTests",
    "test_research_v2.SafetyTests", "test_indicators",
)
_FILESYSTEM_WRITES = frozenset(("os.mkdir", "os.remove", "os.rmdir", "os.rename",
    "os.chmod", "os.chown", "os.link", "os.symlink", "os.truncate", "shutil.rmtree",
    "shutil.copyfile", "tempfile.mkdtemp", "tempfile.mkstemp"))


def make_guard(report, event_log):
    base = guard_for(report, event_log=event_log)

    def guard(event, args):
        if (event.startswith("socket.") or event in _FILESYSTEM_WRITES
                or event in ("http.client.connect", "os.system")):
            event_log.append(event)
            raise RuntimeError("Metadata verification prohibits network, workers and fixture lifecycle I/O")
        if event == "open":
            if type(args[0]) is int:
                event_log.append("open.descriptor")
                raise RuntimeError("Unscoped file descriptors prohibited")
            if isinstance(args[0], (str, bytes)):
                p = Path(args[0]).resolve()
                if p.is_relative_to(ROOT / "logs"):
                    event_log.append("open.private-log")
                    raise RuntimeError("Private logs prohibited")
        base(event, args)
    return guard


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-directory", required=True)
    args = parser.parse_args()
    raw = Path(args.report_directory).absolute()
    report = raw.resolve()
    if (raw != report or report.parent != ROOT / "reports/research-v2"
            or not report.name.startswith("V2-ADAPTER-ACCESS-CONTRACT-")
            or not report.is_dir() or report.is_symlink()):
        parser.error("Prepared versioned metadata-only evidence directory required")
    blocked = []
    sys.dont_write_bytecode = True
    sys.addaudithook(make_guard(report, blocked))
    sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests"), str(ROOT / "scripts")]
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(name) for name in SUITES)
    tested = unittest.TextTestRunner(verbosity=2, resultclass=RecordedResult).run(suite)
    failures, errors, skipped = len(tested.failures), len(tested.errors), len(tested.skipped)
    new_ids = [name for name in tested.executed if name.startswith("test_v2_adapter_access_contract.")]
    code_paths = ["src/demo_futures/research_v2/adapter_access_contract.py",
                  "tests/test_v2_adapter_access_contract.py",
                  "scripts/verify_v2_adapter_access_contract.py"]
    baseline = json.loads((report / "source-baseline.json").read_text(encoding="utf-8"))
    preserved = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == digest
                 for p, digest in baseline["protected_sha256"].items()}
    record = {
        "scope": "INVENTED_METADATA_ONLY", "suites": SUITES, "tests_run": tested.testsRun,
        "new_tests": len(new_ids), "regression_tests": tested.testsRun - len(new_ids),
        "passed": tested.testsRun - failures - errors - skipped,
        "failures": failures, "errors": errors, "skipped": skipped,
        "test_ids": tested.executed, "failure_ids": [t.id() for t, _ in tested.failures],
        "error_ids": [t.id() for t, _ in tested.errors], "blocked_runtime_events": blocked,
        "fixture_creation_or_sqlite_connections": 0,
        "protected_code_preserved": preserved,
        "source_sha256": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in code_paths},
        "successful": tested.wasSuccessful() and not skipped and not blocked and all(preserved.values()),
        "limitations": ["No real source identity/content verification", "No SQLite filesystem tests selected",
                        "Audit guard is not an operating-system sandbox", "No financial or ML evaluation"],
    }
    attempt = len(list(report.glob("synthetic-tests-attempt-*.json"))) + 1
    with (report / f"synthetic-tests-attempt-{attempt:02d}.json").open("x", encoding="utf-8") as f:
        json.dump(record, f, indent=2)
        f.write("\n")
    return 0 if record["successful"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
