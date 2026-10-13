"""Guarded synthetic SQL tests; SQLite is limited to newly registered temp fixtures."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import sys
import unittest

from verify_research_v2 import guard_for
from verify_v2_contracts import RecordedResult

ROOT = Path(__file__).resolve().parents[1]
SUITES = ("test_v2_sqlite_fixtures", "test_v2_loader_boundary", "test_v2_contracts",
          "test_research_v2.ConfigurationTests", "test_research_v2.FeatureTests",
          "test_research_v2.SafetyTests", "test_indicators")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-directory", required=True)
    parser.add_argument("--preflight-only", action="store_true", help="One bounded create/seal/remove check; no SQL or suite")
    args = parser.parse_args()
    supplied = Path(args.report_directory).absolute()
    report = supplied.resolve()
    if (report.parent != ROOT / "reports/research-v2" or not report.is_dir()
            or supplied.is_symlink() or getattr(supplied.lstat(), "st_file_attributes", 0) & 0x400
            or not report.name.startswith(("V2-SQLITE-FIXTURE-CONTRACT-", "V2-SQLITE-REMEDIATION-"))):
        parser.error("New isolated fixture-verification evidence folder required")
    configured = os.environ.get("TEMP") if os.name == "nt" else os.environ.get("TMPDIR", "/tmp")
    if not configured or not Path(configured).is_absolute():
        parser.error("Explicit normal temporary root required; no fallback or write probes")
    temp_base = Path(configured).absolute()
    owned_roots, known_handles, blocked = set(), set(), []
    mkdir_attempts = set()
    connections = []
    base = guard_for(report, event_log=blocked)

    def owned(path):
        return any(path.is_relative_to(root) for root in owned_roots)

    def guard(event, values):
        if event == "tempfile.mkdtemp":
            path = Path(values[0]).absolute()
            if path.parent != temp_base or not path.name.startswith("v2_sqlite_contract_") or path.exists():
                raise RuntimeError("Only freshly minted task fixture directories permitted")
            owned_roots.add(path)
            return
        if event == "os.mkdir" and Path(values[0]).absolute() in owned_roots:
            mkdir_attempts.add(Path(values[0]).absolute())
        if event == "sqlite3.connect":
            module = sys.modules.get("demo_futures.research_v2.sqlite_fixture_contract")
            if module is None or not module._audited_connection(values[0]):
                blocked.append("sqlite3.connect:unowned")
                raise RuntimeError("Unowned/real SQLite access prohibited")
            connections.append("READ_ONLY_FIXTURE" if values[0].endswith("?mode=ro") else "BUILD_FIXTURE")
            return
        if event == "sqlite3.connect/handle":
            known_handles.add(values[0])
            return
        if event == "sqlite3.enable_load_extension":
            if values[0] not in known_handles or values[1] is not False:
                raise RuntimeError("Extensions prohibited")
            return
        if event == "sqlite3.load_extension":
            raise RuntimeError("Extensions prohibited")
        if event.startswith("socket.") or event in ("http.client.connect", "os.system"):
            blocked.append(event)
            raise RuntimeError("No network/external workers in fixture verification")
        if event in ("os.chmod", "shutil.rmtree", "os.rename"):
            raise RuntimeError("Permission changes, recursive cleanup and renames prohibited")
        if event in ("os.remove", "os.rmdir"):
            for value in values[:2] if event == "os.rename" else values[:1]:
                if isinstance(value, (str, bytes)) and not owned(Path(value).absolute()):
                    raise RuntimeError("Cleanup restricted to newly minted fixture roots")
        if event == "open" and isinstance(values[0], (str, bytes)):
            path = Path(values[0]).absolute()
            if owned(path):
                if path.resolve().parent != path.parent:
                    raise RuntimeError("Fixture path alias refused")
                return
            path = path.resolve()
            if path.is_relative_to(ROOT / "logs"):
                raise RuntimeError("Private logs prohibited")
            if path.suffix == ".pyc" and any(path.is_relative_to(ROOT / p) for p in ("src", "tests", "scripts")):
                raise FileNotFoundError("Source-only verification")
        base(event, values)

    sys.addaudithook(guard)
    sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests"), str(ROOT / "scripts")]
    if args.preflight_only:
        from demo_futures.research_v2.sqlite_fixture_contract import temporary_fixture, _FIXTURES
        def error_record(exc):
            if isinstance(exc, BaseExceptionGroup):
                return {"category": type(exc).__name__, "errors": [error_record(e) for e in exc.exceptions]}
            return {"category": type(exc).__name__, "reason": getattr(exc, "reason", None),
                    "errno": getattr(exc, "errno", None), "winerror": getattr(exc, "winerror", None)}
        failure = None
        witness = None
        try:
            with temporary_fixture() as owner:
                lease = _FIXTURES[owner.token.fixture_id]
                witness = {"root": str(lease["root"]), "root_key": lease["root_key"],
                           "file_key": lease["file_key"]}
                owner.seal()
        except BaseException as exc:
            failure = error_record(exc)
        removed = all(not p.exists() for p in owned_roots)
        record = {"scope": "ONE_NORMAL_SANDBOX_FIXTURE_PREFLIGHT", "attempts": 1,
                  "normal_sandbox_only": True, "witness": witness, "failure": failure,
                  "attempted_roots": [str(p) for p in sorted(owned_roots)],
                  "fixture_roots_removed": removed, "active_leases": len(_FIXTURES),
                  "sqlite_connections": len(connections), "unit_tests_run": 0,
                  "blocked_runtime_events": blocked,
                  "successful": failure is None and witness is not None and removed and not _FIXTURES and not blocked and not connections,
                  "source_sha256": hashlib.sha256((ROOT / "src/demo_futures/research_v2/sqlite_fixture_contract.py").read_bytes()).hexdigest(),
                  "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
        with (report / "permission-preflight.json").open("x", encoding="utf-8") as f:
            json.dump(record, f, indent=2); f.write("\n")
        print(json.dumps(record, indent=2))
        return 0 if record["successful"] else 1
    suites = [unittest.defaultTestLoader.loadTestsFromName(name) for name in SUITES]
    result = unittest.TextTestRunner(verbosity=2, resultclass=RecordedResult).run(unittest.TestSuite(suites))
    files = list(sorted((ROOT / "src/demo_futures/research_v2").glob("*.py")))
    files += [ROOT / "src/demo_futures" / (n + ".py") for n in ("data", "indicators", "strategy", "risk", "backtest")]
    files += [ROOT / "tests" / (n + ".py") for n in ("test_v2_sqlite_fixtures", "test_v2_loader_boundary", "test_v2_contracts", "test_research_v2", "test_indicators")]
    files += [Path(__file__), ROOT / "scripts/verify_research_v2.py", ROOT / "scripts/verify_v2_contracts.py"]
    failures, errors, skips = len(result.failures), len(result.errors), len(result.skipped)
    fixture_module = sys.modules["demo_futures.research_v2.sqlite_fixture_contract"]
    active_leases = len(fixture_module._FIXTURES)
    record = {"scope": "INVENTED_TEMPORARY_SQLITE_FIXTURES_ONLY", "suites": SUITES,
              "tests_run": result.testsRun, "passed": result.testsRun - failures - errors - skips,
              "failures": failures, "errors": errors, "skipped": skips, "test_ids": result.executed,
              "failure_ids": [t.id() for t, _ in result.failures], "error_ids": [t.id() for t, _ in result.errors],
              "blocked_runtime_events": blocked, "fixture_connections": {kind: connections.count(kind) for kind in set(connections)},
              "fixture_root_registrations": len(owned_roots), "os_root_mkdir_attempts": len(mkdir_attempts),
              "virtual_registration_count": len(owned_roots - mkdir_attempts),
              "active_leases_after_suite": active_leases,
              "fixture_directories_removed": all(not p.exists() for p in owned_roots),
              "successful": result.wasSuccessful() and not active_leases and not blocked and all(not p.exists() for p in owned_roots),
              "python_version": sys.version.split()[0], "source_test_runner_sha256": {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
              "no_whole_database_hashes": True, "risk_clearance": "NOT CLEARED"}
    attempt = len(list(report.glob("synthetic-tests-attempt-*.json"))) + 1
    with (report / f"synthetic-tests-attempt-{attempt:02d}.json").open("x", encoding="utf-8") as f:
        json.dump(record, f, indent=2)
        f.write("\n")
    return 0 if record["successful"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
