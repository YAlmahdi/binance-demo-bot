"""Explicit fixed-window future-expansion DATA ONLY collector with process watchdog."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.parse
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def guard_for(artifact, report):
    allowed = (artifact.resolve(), report.resolve())
    def guard(event, args):
        if event == "open" and isinstance(args[0], (str, bytes)):
            p = Path(args[0]).resolve()
            if p.name.lower().startswith(".env") or p.suffix.lower() in (".db", ".sqlite", ".sqlite3", ".key", ".pem") or "credential" in p.name.lower():
                raise RuntimeError("Credential/protected database access prohibited")
            if p.is_relative_to(ROOT / "src") and p.suffix == ".pyc":
                raise FileNotFoundError("Source-only imports")
            mode, flags = args[1:3]
            writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (isinstance(flags, int) and flags & 3 != 0)
            if writing and not any(p.is_relative_to(v) for v in allowed):
                raise RuntimeError("Writes outside new DATA ONLY snapshot prohibited")
            if any(p.is_relative_to(ROOT / v) for v in ("data", "artifacts", "reports")) and not any(p.is_relative_to(v) for v in allowed):
                raise RuntimeError("Old databases and research artifacts prohibited")
            if p.is_relative_to(ROOT / "src/demo_futures/ml_research"):
                raise RuntimeError("ML source/outcomes prohibited")
        if event == "sqlite3.connect":
            raise RuntimeError("Database access prohibited")
        if event == "import" and (args[0] in ("demo_futures.client", "demo_futures.config", "demo_futures.cli", "demo_futures.collector") or args[0].startswith("demo_futures.ml_research")):
            raise RuntimeError("Authenticated or ML modules prohibited")
        if event == "socket.getaddrinfo" and (args[0] != "demo-fapi.binance.com" or args[1] != 443):
            raise RuntimeError("Only Demo HTTPS DNS permitted")
        if event == "socket.connect" and args[1][1] != 443:
            raise RuntimeError("Only HTTPS transport permitted")
        if event == "urllib.Request":
            url, data, headers, method = args
            parts = urllib.parse.urlsplit(url)
            if method != "GET" or data is not None or parts.scheme != "https" or parts.netloc != "demo-fapi.binance.com" or parts.fragment or set(k.lower() for k in headers) - {"user-agent"}:
                raise RuntimeError("Only unsigned fixed-origin Demo GET permitted")
            pairs = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
            if len(pairs) != len(dict(pairs)):
                raise RuntimeError("Duplicate query prohibited")
            values = dict(pairs)
            for k in ("startTime", "endTime", "limit"):
                if k in values: values[k] = int(values[k])
            from demo_futures.bounded_expansion import check_request
            if check_request(parts.path, values) != url:
                raise RuntimeError("Noncanonical request prohibited")
        if event == "http.client.send":
            connection, data = args
            if connection.host != "demo-fapi.binance.com" or connection.port != 443 or not data.startswith(b"GET /fapi/v1/"):
                raise RuntimeError("Only approved Demo GET transport permitted")
            from demo_futures.bounded_expansion import save
            save(artifact / "wire" / (uuid.uuid4().hex + ".json"), {"utc": datetime.now(timezone.utc).isoformat(), "method": "GET", "host": connection.host})
    return guard


def worker(artifact, report):
    sys.addaudithook(guard_for(artifact, report))
    from demo_futures.bounded_expansion import (CheckpointClient, START, END, METADATA_SHA, WALL_SECONDS, save)
    from demo_futures.future_expansion import contract_metadata, collect
    from demo_futures.public_history import FUTURE_EXPANSION_SYMBOLS
    metadata = ROOT / "manual-public-metadata/exchangeInfo-demo.json"
    raw = metadata.read_bytes()
    if hashlib.sha256(raw).hexdigest() != METADATA_SHA:
        raise RuntimeError("Historical public metadata hash mismatch; no requests")
    info = json.loads(raw)
    for symbol in FUTURE_EXPANSION_SYMBOLS: contract_metadata(info, symbol)
    limits = [int(v["limit"]) for v in info["rateLimits"] if v.get("rateLimitType") == "REQUEST_WEIGHT" and v.get("interval") == "MINUTE" and v.get("intervalNum") == 1]
    if len(limits) != 1 or limits[0] <= 0:
        raise RuntimeError("Public metadata rate limit unavailable")
    client = CheckpointClient(artifact / "raw", seconds=WALL_SECONDS-20, weight_limit=limits[0])
    for symbol in FUTURE_EXPANSION_SYMBOLS:
        def progress(sym, kind, count, scanned):
            save(artifact / "progress" / (uuid.uuid4().hex + ".json"), {"symbol": sym, "kind": kind, "rows": count, "scanned_end_ms": scanned})
            if kind == "funding" or count % 4990 == 0:
                print(sym, kind, count, "validated rows; attempts", client.calls, flush=True)
        bars, funds, failures, defects, scanned, fscan = collect(client, symbol, START, END, END, progress)
        save(artifact / "progress" / (uuid.uuid4().hex + ".json"), {"symbol": symbol, "kind": "finished", "candles_scanned_end_ms": scanned, "funding_scanned_end_ms": fscan, "failures": failures, "defects": defects})
        print(symbol, len(bars), "candles", len(funds), "funding", "failures", len(failures), flush=True)
        if failures:
            return 2
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collect", action="store_true")
    parser.add_argument("--snapshot", required=True, help="New versioned DATA ONLY folder, or explicitly approved continuation")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    artifact = Path(args.snapshot).resolve()
    if not args.collect or artifact.parent != (ROOT / "artifacts/future-expansion").resolve() or not artifact.name.startswith("FUTURE-EXPANSION-DATA-ONLY-"):
        parser.error("Explicit --collect and isolated DATA ONLY folder required")
    report = ROOT / "reports/future-expansion" / artifact.name
    if not artifact.is_dir() or not report.is_dir(): parser.error("Prepared versioned folders required")
    if args.worker: return worker(artifact, report)
    from demo_futures.bounded_expansion import save, START, END, MAX_REQUESTS, WALL_SECONDS, METADATA_SHA
    config = artifact / "config.json"
    frozen = {"scope": "FUTURE_EXPANSION_DATA_ONLY", "origin": "https://demo-fapi.binance.com", "start_ms": START, "end_exclusive_ms": END,
        "symbols": ["SOLUSDT", "BNBUSDT", "XRPUSDT"], "interval": "5m", "max_attempts_cumulative": MAX_REQUESTS,
        "wall_seconds_per_invocation": WALL_SECONDS, "metadata_sha256": METADATA_SHA, "prospective": False, "risk": "NOT CLEARED"}
    if config.exists():
        if json.loads(config.read_text(encoding="utf-8")) != frozen: raise RuntimeError("Frozen collection configuration mismatch")
    else: save(config, frozen)
    # The external process watchdog covers even DNS/header stalls beyond socket bounds.
    lock = artifact / "worker.lock"
    with lock.open("x"):
        started = time.monotonic()
        child = subprocess.Popen([sys.executable, "-B", str(Path(__file__).resolve()), "--collect", "--snapshot", str(artifact), "--worker"])
        timed_out = False
        try:
            code = child.wait(timeout=WALL_SECONDS)
        except subprocess.TimeoutExpired:
            timed_out = True
            child.kill()
            child.wait(timeout=10)
            code = 2
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=10)
    lock.unlink()
    save(report / ("run-"+uuid.uuid4().hex+".json"), {"exit_code": code, "watchdog_timeout": timed_out,
        "elapsed_seconds": round(time.monotonic()-started, 6), "finished_utc": datetime.now(timezone.utc).isoformat()})
    return code


if __name__ == "__main__": raise SystemExit(main())
