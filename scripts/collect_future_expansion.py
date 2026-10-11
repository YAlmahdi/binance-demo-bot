"""Explicit public Demo collection; future-expansion data only, never models/orders."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time
import urllib.parse
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def install_guard(artifact, report):
    allowed = (artifact.resolve(), report.resolve())
    private_roots = tuple((ROOT / p).resolve() for p in ("data", "artifacts/ml-research", "reports/ml-research"))
    def guard(event, args):
        if event == "open" and isinstance(args[0], (str, bytes)):
            p = Path(args[0]).resolve()
            if p.name.lower().startswith(".env") or p.suffix.lower() in (".db", ".sqlite", ".sqlite3", ".key", ".pem") or "credential" in p.name.lower() or any(p.is_relative_to(v) for v in private_roots):
                raise RuntimeError("Private or protected data access prohibited")
            mode, flags = args[1], args[2]
            writing = (isinstance(mode, str) and any(v in mode for v in "wax+")) or (isinstance(flags, int) and flags & 3 != 0)
            if writing and not any(p.is_relative_to(v) for v in allowed):
                raise RuntimeError("Writes outside new snapshot/report prohibited")
        if event == "socket.getaddrinfo" and args[0] != "demo-fapi.binance.com":
            raise RuntimeError("Only Demo DNS permitted")
        if event == "urllib.Request":
            url, body, headers, method = args
            parts = urllib.parse.urlsplit(url)
            if method != "GET" or body is not None or parts.scheme != "https" or parts.netloc != "demo-fapi.binance.com" or parts.fragment:
                raise RuntimeError("Only fixed-origin public Demo GET permitted")
            if any(k.lower() in ("authorization", "x-mbx-apikey") for k in headers):
                raise RuntimeError("Authentication prohibited")
            pairs = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
            if len(pairs) != len(dict(pairs)):
                raise RuntimeError("Duplicate query parameters prohibited")
            values = dict(pairs)
            for k in ("startTime", "endTime", "limit"):
                if k in values:
                    values[k] = int(values[k])
            from demo_futures.public_history import public_url
            if public_url(parts.path, values, future_expansion=True) != url:
                raise RuntimeError("Noncanonical public request prohibited")
        if event == "import" and (args[0] in ("demo_futures.config", "demo_futures.client", "demo_futures.cli", "demo_futures.collector") or args[0].startswith("demo_futures.ml_research")):
            raise RuntimeError("Authenticated or ML modules prohibited")
    sys.addaudithook(guard)


def save_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, indent=2, allow_nan=False)
        f.write("\n")


def save_csv(path, fields, rows):
    with path.open("x", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class Recorder:
    def __init__(self, client, folder):
        self.client, self.folder, self.calls = client, folder, 0
        self.weight_limit = 2400
    def get(self, path, params=None):
        from demo_futures.public_history import PublicHistoryError, DEMO_ORIGIN
        if self.calls >= 700:
            raise PublicHistoryError(0, "local_request_budget")
        headers = self.client.requests[-1].get("used_weight_headers", {}) if self.client.requests else {}
        if headers.get("x-mbx-used-weight-1m", 0) >= self.weight_limit * .8:
            raise PublicHistoryError(0, "local_weight_stop")
        self.calls += 1
        payload = self.client.get(path, params)
        entry = self.client.requests[-1]
        save_json(self.folder / f"{self.calls:04d}-{path.rsplit('/',1)[-1]}.json", {"origin":DEMO_ORIGIN,"path":path,"params":dict(params or {}),"received_at_ms":entry["received_at_ms"],"response_sha256":entry["response_sha256"],"payload":payload})
        return payload


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collect", action="store_true", help="Explicit authorized public GET data collection")
    parser.add_argument("--days", type=int, default=180)
    args=parser.parse_args(argv)
    if not args.collect or not 1 <= args.days <= 180:
        parser.error("Explicit --collect and 1..180 days required")
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    version="future-data-"+stamp+"-"+uuid.uuid4().hex[:8]
    artifact=ROOT/"artifacts/future-expansion"/version
    report=ROOT/"reports/future-expansion"/version
    artifact.mkdir(parents=True,exist_ok=False)
    report.mkdir(parents=True,exist_ok=False)
    install_guard(artifact,report)
    from demo_futures.public_history import PublicDemoHistory, RetryingPublicHistory, PublicHistoryError, FUTURE_EXPANSION_SYMBOLS, DEMO_ORIGIN, DAY, STEP
    from demo_futures.future_expansion import contract_metadata, probe, collect, audit, candle_records
    from demo_futures.data import DataQualityError
    from demo_futures.history_audit import utc
    client=RetryingPublicHistory(PublicDemoHistory(pause=.3,future_expansion=True))
    recorder=Recorder(client,artifact/"raw")
    result={"version":version,"scope":"FUTURE_EXPANSION_DATA_ONLY","active_v2_symbols":["BTCUSDT","ETHUSDT"],"future_only_symbols":list(FUTURE_EXPANSION_SYMBOLS),"origin":DEMO_ORIGIN,"retrieval_started_utc":datetime.now(timezone.utc).isoformat(),"target_days":args.days,"symbols":{},"risk":"NOT CLEARED","prospective":False,"no_training_or_trading":True}
    try:
        server=recorder.get("/fapi/v1/time")["serverTime"]
        if abs(server-int(time.time()*1000))>60000:
            raise DataQualityError("Server/local clock mismatch")
        end=server//STEP*STEP
        start=end-args.days*DAY
        result.update(start_utc=utc(start),end_exclusive_utc=utc(end),start_ms=start,end_ms=end,server_time_ms=server,server_time_utc=utc(server))
        info=recorder.get("/fapi/v1/exchangeInfo")
        if info.get("timezone") != "UTC":
            raise DataQualityError("Exchange timezone not UTC")
        result["rate_limits"]=info["rateLimits"]
        for item in info["rateLimits"]:
            if item.get("rateLimitType")=="REQUEST_WEIGHT" and item.get("interval")=="MINUTE" and item.get("intervalNum")==1:
                recorder.weight_limit=int(item["limit"])
        halt=False
        for symbol in FUTURE_EXPANSION_SYMBOLS:
            item={"scope":"DATA_ONLY_NOT_ACTIVE","status":"NOT_COLLECTED"}
            result["symbols"][symbol]=item
            if halt:
                item["failure"]="Previous transport/limit failure; no further requests"
                continue
            try:
                item["contract"]=contract_metadata(info,symbol)
                item["availability_probes"]=probe(recorder,symbol,start,end,server)
                recent=[p for p in item["availability_probes"] if p["kind"]=="candle"][-1]
                funds=[p for p in item["availability_probes"] if p["kind"]=="funding"]
                if not recent["rows"] or not any(p["rows"] for p in funds):
                    item["failure"]="Recent completed candle or public funding history unavailable; no full collection"
                    continue
                checkpoint=[0]
                def progress(sym,kind,rows,scanned):
                    if kind=="candles" and rows-checkpoint[0]>=10000:
                        print(sym,kind,rows,"validated rows",flush=True)
                        checkpoint[0]=rows
                bars,funding,failures,defects,scanned,fscan=collect(recorder,symbol,start,end,server,progress)
                quality=audit(bars,funding,start,end,server)
                item.update(quality=quality,collection_failures=failures,raw_candle_defects=defects,candles_scanned_end_utc=utc(scanned),funding_scanned_end_utc=utc(fscan),status="COLLECTED" if not failures else "PARTIAL_OR_REJECTED")
                dest=artifact/symbol
                dest.mkdir(exist_ok=False)
                rows=candle_records(bars,symbol)
                fields=["symbol","interval","open_time","open","high","low","close","volume","close_time","quote_volume","trades"]
                save_csv(dest/"candles.csv",fields,rows)
                save_csv(dest/"funding.csv",["symbol","fundingTime","fundingRate","markPrice","rateType"],[{k:r.get(k,"") for k in ("symbol","fundingTime","fundingRate","markPrice","rateType")} for r in funding])
                item["dataset_paths"]={"candles":str(dest/"candles.csv"),"funding":str(dest/"funding.csv")}
                halt=any(v["kind"]=="transport_stop" for v in failures)
                print(symbol,item["status"],len(bars),"candles",len(funding),"funding records",flush=True)
            except PublicHistoryError as error:
                item.update(status="UNAVAILABLE",failure={"http_status":error.status,"kind":error.kind})
                halt=True
            except DataQualityError:
                item.update(status="QUALITY_CHECK_FAILED",failure="Public response validation failed; no repaired or substituted data")
    except (PublicHistoryError,DataQualityError) as error:
        result["global_failure"]={"type":type(error).__name__,"http_status":getattr(error,"status",None),"kind":getattr(error,"kind","quality")}
        for symbol in FUTURE_EXPANSION_SYMBOLS:
            result["symbols"].setdefault(symbol,{"status":"NOT_COLLECTED","scope":"DATA_ONLY_NOT_ACTIVE"})
    result["retrieval_finished_utc"]=datetime.now(timezone.utc).isoformat()
    result["actual_get_attempts"]=len(client.requests)
    save_json(report/"requests.json",client.requests)
    save_json(report/"audit.json",result)
    files={str(p.relative_to(artifact)):hashlib.sha256(p.read_bytes()).hexdigest() for p in artifact.rglob("*") if p.is_file()}
    save_json(artifact/"manifest.json",{"version":version,"scope":"FUTURE_EXPANSION_DATA_ONLY","files_sha256":files,"source_sha256":{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__),ROOT/"src/demo_futures/public_history.py",ROOT/"src/demo_futures/future_expansion.py")},"audit_sha256":hashlib.sha256((report/"audit.json").read_bytes()).hexdigest()})
    print("ARTIFACT",artifact,flush=True)
    print("REPORT",report/"audit.json",flush=True)
    return 0 if not result.get("global_failure") and all(v["status"]=="COLLECTED" for v in result["symbols"].values()) else 2

if __name__=="__main__":
    raise SystemExit(main())
