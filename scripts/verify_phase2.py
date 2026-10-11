"""Run the full suite and saved-data samples with network and real .env reads blocked.

This developer check is an additional audit guard, not an OS security sandbox.
It never enables the opt-in public Binance network test.
"""
from pathlib import Path
import hashlib
import json
import os
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "src"))
SECRET = (ROOT / ".env").resolve()


def offline_audit(event, arguments):
    if event in ("socket.connect", "socket.getaddrinfo"):
        raise RuntimeError("Phase 2 verification prohibits network access")
    if event == "open" and isinstance(arguments[0], (str, bytes)):
        if Path(os.fsdecode(arguments[0])).resolve() == SECRET:
            raise RuntimeError("Phase 2 verification prohibits local credential-file access")


sys.addaudithook(offline_audit)
os.environ.pop("RUN_DEMO_INTEGRATION", None)


def main():
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    summary = {
        "discovered": result.testsRun,
        "passed": result.testsRun - len(result.skipped) - len(result.failures) - len(result.errors),
        "failed": len(result.failures), "errors": len(result.errors),
        "skipped": [{"test": test.id(), "reason": reason} for test, reason in result.skipped],
        "network_blocked": True, "real_dotenv_reads_blocked": True,
        "scope": "offline tests; no credentials or exchange calls",
    }
    destination = ROOT / "reports" / "phase2-tests.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"Tests: {summary['passed']} passed; "
          f"{len(result.failures)} failed; {len(result.errors)} errors; {len(result.skipped)} skipped.")
    if not result.wasSuccessful():
        return 1
    from demo_futures.backtest_cli import main as backtest_main
    database = ROOT / "data" / "market.sqlite3"
    if not database.is_file():
        print("Saved historical database is missing. No data will be fetched.")
        return 1
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    for arguments in (
        ["--output", "reports/phase2-sample"],
        ["--fee-rate", ".001", "--slippage-rate", ".0004", "--output", "reports/phase2-cost-stress"],
    ):
        if backtest_main(arguments):
            return 1
    if hashlib.sha256(database.read_bytes()).hexdigest() != before:
        raise RuntimeError("Historical input database changed during verification")
    print("Historical database unchanged; offline sample and doubled-cost sample completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
