"""Source-bound M1 synthetic verification; no market inputs or financial clearance."""
import argparse
from datetime import datetime, timezone
from decimal import DefaultContext, getcontext
import hashlib
import json
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SUITES = ("test_risk_funding_budget", "test_risk", "test_v2_contracts.FundingContractTests")
PATHS = (
    "src/demo_futures/__init__.py", "src/demo_futures/risk_remediation/__init__.py",
    "src/demo_futures/risk_remediation/funding_budget.py", "src/demo_futures/risk.py",
    "src/demo_futures/research_v2/__init__.py", "src/demo_futures/research_v2/config.py",
    "src/demo_futures/research_v2/contracts.py", "src/demo_futures/research_v2/funding_contracts.py",
    "src/demo_futures/research_v2/source_contracts.py", "src/demo_futures/research_v2/quality_contracts.py",
    "src/demo_futures/research_v2/features.py", "src/demo_futures/data.py",
    "src/demo_futures/indicators.py", "tests/test_risk_funding_budget.py", "tests/test_risk.py",
    "tests/test_v2_contracts.py", "scripts/verify_risk_m1_synthetic.py",
)


def identities():
    return {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in PATHS}


def context_state(context):
    return {**{n: str(getattr(context, n)) for n in
        ("prec", "rounding", "Emin", "Emax", "capitals", "clamp")},
        "traps": {s.__name__: v for s, v in context.traps.items()},
        "flags": {s.__name__: v for s, v in context.flags.items()}}


def make_guard(report, receipt, blocked):
    allowed = {(ROOT / p).resolve() for p in PATHS} | {report / "baseline.json"}
    def refuse(event):
        blocked.append(event)
        raise RuntimeError("M1 verification boundary: " + event)
    def guard(event, args):
        if (event.startswith(("socket.", "subprocess.", "sqlite3.connect"))
                or event in ("urllib.Request", "http.client.connect", "http.client.send", "os.system",
                    "os.mkdir", "os.remove", "os.rmdir", "os.rename", "os.chmod", "os.chown",
                    "os.link", "os.symlink", "os.truncate", "shutil.rmtree", "shutil.copyfile",
                    "tempfile.mkdtemp", "tempfile.mkstemp", "os.putenv", "os.unsetenv")):
            refuse(event)
        if event == "import" and (args[0].startswith(("demo_futures.ml_research", "sklearn", "numpy",
                "pandas", "joblib", "dotenv")) or args[0] in ("demo_futures.client", "demo_futures.config",
                "demo_futures.cli", "demo_futures.collector", "demo_futures.public_history",
                "demo_futures.backtest", "demo_futures.backtest_cli")):
            refuse("import.prohibited")
        if event == "open":
            if type(args[0]) is int:
                refuse("open.descriptor")
            path = Path(os.fsdecode(args[0])).resolve()
            if (path.name.lower().startswith(".env") or "credential" in path.name.lower()
                    or path.suffix.lower() in (".db", ".sqlite", ".sqlite3", ".key", ".pem", ".pkl", ".joblib")):
                refuse("open.sensitive")
            mode, flags = args[1:3]
            writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
            if writing:
                if path != receipt or not flags & os.O_EXCL:
                    refuse("open.write-outside-exclusive-receipt")
            elif path.is_relative_to(ROOT):
                if path.suffix == ".pyc":
                    raise FileNotFoundError("Source-only verification")
                if path not in allowed:
                    refuse("open.unscoped-project-file")
            elif not path.is_relative_to(Path(sys.base_prefix).resolve()):
                refuse("open.unscoped-runtime-file")
    return guard


class RecordedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ids, self.outcomes = [], []
    def startTest(self, test):
        self.ids.append(test.id())
        super().startTest(test)
    def addSuccess(self, test):
        self.outcomes.append({"id": test.id(), "outcome": "PASS"})
        super().addSuccess(test)
    def addFailure(self, test, err):
        self.outcomes.append({"id": test.id(), "outcome": "FAIL", "exception": self._exc_info_to_string(err, test)})
        super().addFailure(test, err)
    def addError(self, test, err):
        self.outcomes.append({"id": test.id(), "outcome": "ERROR", "exception": self._exc_info_to_string(err, test)})
        super().addError(test, err)
    def addSkip(self, test, reason):
        self.outcomes.append({"id": test.id(), "outcome": "SKIP", "reason": reason})
        super().addSkip(test, reason)
    def addSubTest(self, test, subtest, err):
        if err is not None:
            self.outcomes.append({"id": test.id(), "subtest": str(subtest), "outcome": "FAIL" if issubclass(err[0], test.failureException) else "ERROR",
                "exception": self._exc_info_to_string(err, test)})
        super().addSubTest(test, subtest, err)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-directory", required=True)
    parser.add_argument("--phase", choices=("baseline", "final"), required=True)
    args = parser.parse_args()
    raw = Path(args.report_directory).absolute()
    report = raw.resolve()
    if (raw != report or report.parent != ROOT / "reports/risk-remediation"
            or not report.name.startswith("M1-SYNTHETIC-") or not report.is_dir()
            or report.is_symlink()):
        parser.error("Pre-created versioned M1 report directory required")
    receipt = report / (args.phase + ".json")
    if receipt.exists():
        parser.error("Receipt already exists; preserve it and use a new version")
    blocked = []
    sys.dont_write_bytecode = True
    sys.addaudithook(make_guard(report, receipt, blocked))
    sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
    start = identities()
    baseline = start if args.phase == "baseline" else json.loads((report / "baseline.json").read_text())["source_before"]
    results, contexts = [], []
    for name in SUITES:
        before = {"default": context_state(DefaultContext), "current": context_state(getcontext())}
        suite = unittest.defaultTestLoader.loadTestsFromName(name)
        result = unittest.TextTestRunner(verbosity=2, resultclass=RecordedResult).run(suite)
        results.append(result)
        contexts.append({"suite": name, "before": before,
            "after": {"default": context_state(DefaultContext), "current": context_state(getcontext())}})
    end = identities()
    preservation = {p: baseline[p] == end[p] for p in PATHS if p != "tests/test_risk_funding_budget.py"}
    context_ok = all(c["before"]["default"] == c["after"]["default"] and
        all(c["before"]["current"][k] == c["after"]["current"][k] for k in c["before"]["current"] if k != "flags") and
        (c["suite"] == "test_risk" or c["before"]["current"]["flags"] == c["after"]["current"]["flags"]) for c in contexts)
    record = {"scope": "SYNTHETIC_DIAGNOSTIC_ONLY", "phase": args.phase,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "environment": {"python": sys.version, "executable": sys.executable, "platform": sys.platform, "bytecode_writes": False},
        "suites": [{"name": name, "tests_run": r.testsRun, "passed": sum(v["outcome"] == "PASS" for v in r.outcomes),
            "failures": len(r.failures), "errors": len(r.errors), "skipped": len(r.skipped),
            "test_ids": r.ids, "outcomes": r.outcomes} for name, r in zip(SUITES, results)],
        "tests_run": sum(r.testsRun for r in results), "passed": sum(sum(v["outcome"] == "PASS" for v in r.outcomes) for r in results),
        "failures": sum(len(r.failures) for r in results), "errors": sum(len(r.errors) for r in results), "skipped": sum(len(r.skipped) for r in results),
        "source_before": start, "source_after": end, "baseline_preserved": preservation,
        "in_run_source_preserved": start == end, "decimal_contexts": contexts, "context_policy_preserved": context_ok,
        "blocked_events": blocked, "guard": "Exact project read allowlist; bundled runtime reads; one exclusive receipt write; network/SQLite/workers/filesystem mutation/account/model imports denied",
        "limitations": ["Audit hook is not an OS sandbox", "Legacy risk suite may set informational arithmetic flags",
            "No financial clearance, historical funding truth, resource cap or execution readiness established"],
        "successful": all(r.wasSuccessful() and not r.skipped for r in results) and not blocked and start == end and all(preservation.values()) and context_ok}
    with receipt.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, indent=2)
        stream.write("\n")
    return 0 if record["successful"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
