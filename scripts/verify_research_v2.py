"""Run only synthetic engineering checks; never load saved markets or models."""
from pathlib import Path
import argparse
import hashlib
import json
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
BLOCKED_EVENTS=[]

def guard_for(report, *, event_log=None):
    report=Path(report).resolve()
    events=BLOCKED_EVENTS if event_log is None else event_log
    def guard(event,args):
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
            if p.is_relative_to(ROOT/"reports") and not p.is_relative_to(report):
                raise RuntimeError("Prior outcome/report access prohibited")
            if p.is_relative_to(ROOT/"src") and p.suffix==".pyc":
                raise FileNotFoundError("Source-only verification")
            mode,flags=args[1:3]
            writing=(isinstance(mode,str) and any(c in mode for c in "wax+")) or (isinstance(flags,int) and flags&3!=0)
            if writing and not p.is_relative_to(report):
                raise RuntimeError("Verification writes only new report evidence")
    return guard

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-directory",required=True)
    args=parser.parse_args()
    report=Path(args.report_directory).resolve()
    if report.parent!=(ROOT/"reports/research-v2").resolve() or not report.name.startswith("V2-ENGINEERING-SYNTHETIC-") or not report.is_dir():
        parser.error("Prepared isolated V2 synthetic report folder required")
    sys.addaudithook(guard_for(report))
    sys.path[:0]=[str(ROOT/"src"),str(ROOT/"tests"),str(ROOT/"scripts")]
    suites=[unittest.defaultTestLoader.loadTestsFromName(n) for n in ("test_research_v2","test_indicators","test_risk")]
    result=unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(suites))
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
