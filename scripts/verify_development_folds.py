"""Offline regression and synthetic fitting tests, separate from immutable engineering evidence."""
from collections import Counter
import json
import os
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path[:0]=[str(ROOT/"src"),str(ROOT/"tests")]
from demo_futures.ml_research.development_runtime import guard, environment
from demo_futures.ml_research.dataset import file_hash
from demo_futures.ml_research.artifacts import verify_inputs


def source_hashes():
    paths=list((ROOT/"src/demo_futures/ml_research").glob("*.py"))+list((ROOT/"tests").glob("test_ml_*.py"))
    paths += [ROOT/"scripts/run_development_folds.py",ROOT/"scripts/verify_development_folds.py"]
    return {p.relative_to(ROOT).as_posix():file_hash(p) for p in sorted(paths)}


def main():
    os.chdir(ROOT); os.environ["RUN_DEMO_INTEGRATION"]="0"; os.environ["PYTHONDONTWRITEBYTECODE"]="1"
    guard(ROOT,test_mode=True); versions=environment(ROOT)
    witness=json.loads((ROOT/"artifacts/ml-research/development-fitting-input-witness.json").read_text())
    verify_inputs(ROOT,witness); before=source_hashes()
    suite=unittest.defaultTestLoader.discover(str(ROOT/"tests"))
    def flatten(node):
        if isinstance(node,unittest.TestSuite):
            for child in node: yield from flatten(child)
        else: yield node
    cases=list(flatten(suite)); modules=Counter(t.__class__.__module__ for t in cases)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    failures=[t.id() for t,_ in result.failures]; errors=[t.id() for t,_ in result.errors]
    skipped=[{"id":t.id(),"reason":r} for t,r in result.skipped]
    verified=verify_inputs(ROOT,witness)
    if source_hashes()!=before: raise ValueError("Research source changed during tests")
    evidence={"stage":"OFFLINE_DEVELOPMENT_FITTING_TESTS","discovered":len(cases),"run":result.testsRun,
              "passed":result.testsRun-len(failures)-len(errors)-len(skipped),"failures":len(failures),"errors":len(errors),
              "failed_ids":failures,"error_ids":errors,"skipped":skipped,"modules_discovered":dict(sorted(modules.items())),
              "research_code_sha256":before,"protected_files_checked":verified["files_checked"],
              "protected_inputs_status":verified["status"],"environment":versions,
              "historical_models_fitted_in_tests":0,"synthetic_fits_only":True,
              "network_blocked":True,"project_credentials_blocked":True,
              "selection_validation_evaluated":False,"final_evaluated":False}
    out=ROOT/"reports/ml-research/development-tests.json"
    out.write_text(json.dumps(evidence,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:evidence[k] for k in ("discovered","passed","failures","errors","skipped")}))
    return 0 if result.wasSuccessful() else 1


if __name__=="__main__": sys.exit(main())
