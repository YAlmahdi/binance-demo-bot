"""All offline tests; network and actual project credential access blocked."""
from collections import Counter
import json
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
from demo_futures.ml_research.safety import offline_guard


def main():
    os.chdir(ROOT)
    os.environ["RUN_DEMO_INTEGRATION"] = "0"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    offline_guard(ROOT, test_mode=True)
    from demo_futures.ml_research.artifacts import verify_inputs
    from demo_futures.ml_research.dataset import file_hash
    witness=json.loads((ROOT/"artifacts/ml-research/engineering-input-witness.json").read_text(encoding="utf-8"))
    verify_inputs(ROOT,witness)
    paths=sorted((ROOT/"src/demo_futures/ml_research").glob("*.py"))
    paths+=sorted((ROOT/"tests").glob("test_ml_*.py"))
    paths+=[ROOT/"scripts/ml_research.py",ROOT/"scripts/verify_phase4a.py"]
    source_hashes={p.relative_to(ROOT).as_posix():file_hash(p) for p in paths}
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    def flatten(node):
        if isinstance(node, unittest.TestSuite):
            for child in node:
                yield from flatten(child)
        else:
            yield node
    cases = list(flatten(suite))
    modules = Counter(t.__class__.__module__ for t in cases)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    failed_ids = [t.id() for t, _ in result.failures]
    error_ids = [t.id() for t, _ in result.errors]
    skipped = [{"id": t.id(), "reason": reason} for t,reason in result.skipped]
    protected=verify_inputs(ROOT,witness)
    if source_hashes != {p.relative_to(ROOT).as_posix():file_hash(p) for p in paths}:
        raise ValueError("Research source changed during tests")
    evidence = {"protected_inputs_status":protected["status"],"protected_files_checked":protected["files_checked"],
                "research_code_sha256":source_hashes,"stage": "OFFLINE_ENGINEERING_TESTS", "discovered": len(cases),
                "run": result.testsRun, "passed": result.testsRun-len(failed_ids)-len(error_ids)-len(skipped),
                "failures": len(failed_ids), "errors": len(error_ids), "skipped": skipped,
                "failed_ids": failed_ids, "error_ids": error_ids,
                "modules_discovered": dict(sorted(modules.items())),
                "network_blocked": True, "project_credentials_blocked": True,
                "dummy_temp_credentials_for_existing_mock_tests_only": True,
                "models_fitted": 0, "selection_validation_evaluated": False, "final_evaluated": False}
    out = ROOT / "reports/ml-research/engineering-tests.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(evidence,indent=2)+"\n", encoding="utf-8")
    print(json.dumps({k:evidence[k] for k in ("discovered","passed","failures","errors","skipped")}))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
