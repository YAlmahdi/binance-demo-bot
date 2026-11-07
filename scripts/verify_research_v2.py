"""Run only synthetic engineering checks; never load saved markets or models."""
from pathlib import Path
import argparse
from contextlib import ExitStack
import hashlib
import json
import os
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
BLOCKED_EVENTS=[]
ENGINEERING_SUITES = (
    "test_research_v2.ConfigurationTests", "test_research_v2.FeatureTests",
    "test_research_v2.SchedulingTests", "test_research_v2.ValidationTests",
    "test_research_v2.ArtifactTests", "test_research_v2.SafetyTests",
    "test_research_v2.RefinementTests.test_coverage_refuses_omitted_slots_and_reports_feature_breaches",
    "test_research_v2.RefinementTests.test_artifact_source_order_is_canonical",
    "test_v2_contracts", "test_v2_loader_boundary", "test_v2_adapter_access_contract",
    "test_v2_authorization_binding", "test_v2_fixed_query_plan",
    "test_v2_preprocessing_validation", "test_v2_preprocessing_estimator",
    "test_v2_assembly", "test_v2_eligibility", "test_v2_pipeline_regression",
    "test_v2_engineering_runner",
    "test_v2_loader_readiness",
    "test_v2_historical_validators",
)

def guard_for(report, *, event_log=None, allow_report_writes=True):
    report=Path(report).resolve()
    events=BLOCKED_EVENTS if event_log is None else event_log
    def guard(event,args):
        if not allow_report_writes and event in (
                "os.mkdir", "os.remove", "os.rmdir", "os.rename", "os.link",
                "os.symlink", "os.truncate", "os.chmod", "os.chown"):
            events.append(event)
            raise RuntimeError("Report-free verification cannot mutate the filesystem")
        if event in ("urllib.Request","socket.getaddrinfo","socket.connect","http.client.send","sqlite3.connect","subprocess.Popen"):
            events.append(event)
            raise RuntimeError("Synthetic-only verification: network/database/worker prohibited")
        if event=="import" and (args[0] in ("demo_futures.client","demo_futures.config","demo_futures.cli","demo_futures.collector","demo_futures.public_history")
                                or args[0].startswith(("demo_futures.ml_research","sklearn","numpy","pandas","joblib","dotenv"))):
            raise RuntimeError("Account, network and fitted research modules prohibited")
        if event=="open" and isinstance(args[0],(str,bytes)):
            p=Path(args[0]).resolve()
            if (p.name.lower().startswith(".env") or "credential" in p.name.lower()
                    or p.suffix.lower() in (".db",".sqlite",".sqlite3",".key",".pem",".pkl",".joblib")):
                raise RuntimeError("Credential/database/model file prohibited")
            if any(p.is_relative_to(ROOT/v) for v in ("data","artifacts","manual-public-metadata")):
                raise RuntimeError("Saved market/model artifacts prohibited")
            if p.is_relative_to(ROOT/"reports") and (not allow_report_writes or not p.is_relative_to(report)):
                raise RuntimeError("Prior outcome/report access prohibited")
            if p.is_relative_to(ROOT/"src") and p.suffix==".pyc":
                raise FileNotFoundError("Source-only verification")
            mode,flags=args[1:3]
            writing=(isinstance(mode,str) and any(c in mode for c in "wax+")) or (isinstance(flags,int) and flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
            if writing and (not allow_report_writes or not p.is_relative_to(report)):
                raise RuntimeError("Verification writes only new report evidence")
    return guard

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-directory")
    parser.add_argument("--engineering-only",action="store_true",
                        help="Explicit no-simulator/no-label/no-SQLite execution suite")
    parser.add_argument("--no-report",action="store_true",
                        help="Engineering-only mode with no filesystem writes or report reads")
    args=parser.parse_args()
    if args.no_report and (not args.engineering_only or args.report_directory):
        parser.error("--no-report requires --engineering-only and no report directory")
    if not args.no_report and not args.report_directory:
        parser.error("--report-directory or --engineering-only --no-report required")
    report=(ROOT/"reports/research-v2/V2-ENGINEERING-SYNTHETIC-NO-REPORT" if args.no_report else Path(args.report_directory)).resolve()
    if not args.no_report and (report.parent!=(ROOT/"reports/research-v2").resolve() or not report.name.startswith("V2-ENGINEERING-SYNTHETIC-") or not report.is_dir()):
        parser.error("Prepared isolated V2 synthetic report folder required")
    sys.dont_write_bytecode=True
    sys.addaudithook(guard_for(report,allow_report_writes=not args.no_report))
    sys.path[:0]=[str(ROOT/"src"),str(ROOT/"tests"),str(ROOT/"scripts")]
    names=ENGINEERING_SUITES if args.engineering_only else ("test_research_v2","test_indicators","test_risk")
    with ExitStack() as stack:
        if args.engineering_only:
            from demo_futures.backtest import BacktestEngine
            from demo_futures.research_v2 import labels
            def forbidden(*unused_args,**unused_kwargs):
                BLOCKED_EVENTS.append("SIMULATOR_OR_LABEL_PRODUCTION")
                raise RuntimeError("Engineering-only verification forbids simulation/label production")
            stack.enter_context(patch.object(BacktestEngine,"run",side_effect=forbidden))
            stack.enter_context(patch.object(labels,"paired_outcome",side_effect=forbidden))
        suites=[unittest.defaultTestLoader.loadTestsFromName(n) for n in names]
        result=unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(suites))
    if args.no_report:
        return 0 if result.wasSuccessful() and not result.skipped and not BLOCKED_EVENTS else 1
    number=len(list(report.glob("synthetic-tests-attempt-*.json")))+1
    sources={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/"src/demo_futures/research_v2").glob("*.py")}
    receipt={"scope":"SYNTHETIC_ONLY","tests_run":result.testsRun,"failures":len(result.failures),"errors":len(result.errors),
             "skipped":len(result.skipped),"successful":result.wasSuccessful(),"failure_ids":[t.id() for t,_ in result.failures],
             "error_ids":[t.id() for t,_ in result.errors],"blocked_runtime_events":list(BLOCKED_EVENTS),
             "actual_network_requests":0,"saved_market_data_or_models_opened":False,"fitting_run":False,
             "new_source_sha256":sources,"test_source_sha256":hashlib.sha256((ROOT/"tests/test_research_v2.py").read_bytes()).hexdigest(),
             "runner_source_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    with (report/f"synthetic-tests-attempt-{number:02d}.json").open("x",encoding="utf-8",newline="\n") as f:
        json.dump(receipt,f,indent=2);f.write("\n")
    return 0 if result.wasSuccessful() else 1

if __name__=="__main__":raise SystemExit(main())
