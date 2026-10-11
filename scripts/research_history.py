"""Explicit public-Demo collection; default operation evaluates saved history offline."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import urllib.parse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
os.chdir(ROOT)
SOURCE_FILES = ("strategy.py","indicators.py","risk.py","backtest.py","reporting.py")


def source_hashes():
    return {name:hashlib.sha256((ROOT/"src"/"demo_futures"/name).read_bytes()).hexdigest() for name in SOURCE_FILES}


def guard(online):
    secret=(ROOT/".env").resolve()
    def audit(event,args):
        if event=="open" and isinstance(args[0],(str,bytes)) and Path(os.fsdecode(args[0])).resolve()==secret:
            raise RuntimeError("Credential-file access prohibited")
        if event=="socket.getaddrinfo":
            if not online or args[0]!="demo-fapi.binance.com":
                raise RuntimeError("Network outside authorized public Demo collection prohibited")
        if event=="socket.connect" and not online:
            raise RuntimeError("Offline evaluation prohibits network access")
        if event=="urllib.Request":
            url,body,headers,method=args
            parts=urllib.parse.urlsplit(url)
            allowed={"/fapi/v1/time","/fapi/v1/klines","/fapi/v1/fundingRate"}
            if not online or method!="GET" or body is not None or parts.scheme!="https" or parts.netloc!="demo-fapi.binance.com" or parts.path not in allowed:
                raise RuntimeError("Non-public-Demo request prohibited")
            query_keys = [k for k,v in urllib.parse.parse_qsl(parts.query,keep_blank_values=True)]
            permitted = set() if parts.path=="/fapi/v1/time" else {"symbol","startTime","endTime","limit"}
            if parts.path=="/fapi/v1/klines": permitted.add("interval")
            if len(query_keys)!=len(set(query_keys)) or set(query_keys)!=permitted or parts.fragment:
                raise RuntimeError("Signed or unsupported query parameters prohibited")
            if any(k.lower() in ("x-mbx-apikey","authorization") for k in headers):
                raise RuntimeError("Authentication headers prohibited")
        if event=="import" and args[0] in ("demo_futures.config","demo_futures.client","demo_futures.cli","demo_futures.collector"):
            raise RuntimeError("Authenticated configuration/client imports prohibited in research")
    sys.addaudithook(audit)


def save(path,payload):
    path.write_text(json.dumps(payload,indent=2,default=str,allow_nan=False)+"\n",encoding="utf-8")


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collect",action="store_true",help="Explicitly fetch public Demo data; never credentials")
    parser.add_argument("--days",type=int,default=90)
    parser.add_argument("--end-utc",help="Optional frozen exclusive UTC end aligned to 5m")
    parser.add_argument("--db",type=Path,default=Path("data/research-90d.sqlite3"))
    parser.add_argument("--output",type=Path,default=Path("reports/historical-90d"))
    args=parser.parse_args(argv)
    if not 1<=args.days<=90: parser.error("days must be between 1 and 90")
    if args.db.resolve()==(ROOT/"data"/"market.sqlite3").resolve():
        parser.error("Use a separate research snapshot; preserve the original database")
    if args.db.suffix.lower() not in (".sqlite3",".sqlite",".db"):
        parser.error("Research path must be a SQLite database")
    guard(args.collect)
    from demo_futures.history_audit import audit_database,utc
    from demo_futures.public_history import PublicDemoHistory,RetryingPublicHistory,collect_candles,collect_funding,DAY,STEP,SYMBOLS
    from demo_futures.data import SQLiteStore,DataQualityError
    from demo_futures.backtest_cli import load_history
    from demo_futures.backtest import BacktestEngine
    from demo_futures.risk import BacktestConfig
    from demo_futures.reporting import write_report
    from demo_futures.research_evaluation import analyze,write_research_report
    args.output.mkdir(parents=True,exist_ok=True)
    original=ROOT/"data"/"market.sqlite3"
    original_hash=hashlib.sha256(original.read_bytes()).hexdigest()
    originals=audit_database(original)
    save(args.output/"original-audit.json",originals)
    hashes=source_hashes()
    manifest_path=args.output/"collection.json"
    if args.collect:
        if args.db.exists():
            raise ValueError("Research snapshot already exists; rerun offline without --collect")
        client=RetryingPublicHistory(PublicDemoHistory())
        server=client.get("/fapi/v1/time")["serverTime"]
        if abs(server-int(time.time()*1000))>60000:
            raise DataQualityError("Demo server/local clock mismatch")
        end=server//STEP*STEP
        if args.end_utc:
            parsed=datetime.fromisoformat(args.end_utc.replace("Z","+00:00"))
            if parsed.tzinfo is None: raise ValueError("End requires a UTC offset")
            chosen=int(parsed.timestamp()*1000)
            if chosen%STEP or chosen>end: raise ValueError("End must be aligned and no later than the last completed candle")
            end=chosen
        start=end-args.days*DAY
        probes=[]
        for symbol in SYMBOLS:
            for days in (90,60,30,7,1):
                if days>args.days: continue
                left=end-days*DAY
                rows=client.get("/fapi/v1/klines",{"symbol":symbol,"interval":"5m","startTime":left,"endTime":left+STEP-1,"limit":1})
                probes.append({"symbol":symbol,"days_before_end":days,"requested_open_utc":utc(left),
                               "returned_open_utc":utc(rows[0][0]) if rows else None,"rows":len(rows)})
        manifest={"origin":"https://demo-fapi.binance.com","public_only":True,
                  "start_utc":utc(start),"end_exclusive_utc":utc(end),"server_time_utc":utc(server),
                  "availability_probes":probes,"frozen_source_hashes":hashes,
                  "original_database_sha256":original_hash,"status":"collecting"}
        save(manifest_path,manifest)
        candles,funding={},{}
        def progress(symbol,count,total):
            if count%5000==0 or count==total:
                print(f"{symbol}: {count}/{total} completed candles validated",flush=True)
        try:
            for symbol in SYMBOLS:
                candles[symbol]=collect_candles(client,symbol,start,end,server,progress,ROOT/"data"/"history-checkpoints")
                funding[symbol]=collect_funding(client,symbol,start,end)
                if not funding[symbol]:
                    raise DataQualityError("No historical funding records: full-cost evaluation cannot be verified")
            # Persist only after the complete two-symbol range and funding payloads validate.
            store=SQLiteStore(args.db)
            for symbol in SYMBOLS:
                store.upsert_candles(symbol,"5m",candles[symbol])
                store.upsert_funding(symbol,funding[symbol])
            manifest.update({"status":"complete","requests":client.requests,
                             "database_sha256":hashlib.sha256(args.db.read_bytes()).hexdigest(),
                             "candles_per_symbol":{s:len(v) for s,v in candles.items()},
                             "funding_per_symbol":{s:len(v) for s,v in funding.items()}})
            save(manifest_path,manifest)
            save(args.output/"funding-raw.json",funding)
        except Exception as error:
            manifest.update({"status":"failed","requests":client.requests,"error_type":type(error).__name__,
                             "public_http_status":getattr(error,"status",None),"failure_kind":getattr(error,"kind",None),
                             "limitation":"Collection failed or complete Demo history was unavailable. No production fallback."})
            save(manifest_path,manifest)
            raise
    else:
        manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["status"]!="complete" or manifest["frozen_source_hashes"]!=hashes:
            raise ValueError("Frozen source changed or collection was incomplete")
        if hashlib.sha256(args.db.read_bytes()).hexdigest()!=manifest["database_sha256"]:
            raise ValueError("Research data snapshot changed")
    audit=audit_database(args.db)
    save(args.output/"research-audit.json",audit)
    for symbol in SYMBOLS:
        if not audit["candles"][symbol+":5m"]["quality_passed"]:
            raise DataQualityError("Research candle quality failed; evaluation stopped")
    markets,funding=load_history(args.db,SYMBOLS,"5m")
    analyses={}
    for scenario,config,destination in (
        ("default",BacktestConfig(),args.output/"default"),
        ("doubled_costs",BacktestConfig(fee_rate=".001",slippage_rate=".0004"),args.output/"doubled-costs"),
    ):
        print(f"Running continuous chronological {scenario} backtest...",flush=True)
        result=BacktestEngine(config).run(markets,"5m",funding)
        write_report(result,destination)
        analyses[scenario]=analyze(result,audit)
        print(f"{scenario}: {len(result.trades)} trades; net after costs {result.metrics['net_pnl']:.4f} USDT",flush=True)
    if source_hashes()!=hashes or hashlib.sha256(original.read_bytes()).hexdigest()!=original_hash:
        raise RuntimeError("Frozen source or original history changed")
    write_research_report(args.output,audit,analyses,originals,manifest)
    print("Research complete. Frozen sources and original database unchanged.",flush=True)
    print("Report:",(args.output/"report.md").resolve())
    return 0


if __name__=="__main__":
    try:
        raise SystemExit(main())
    except (ValueError,ArithmeticError,OSError,RuntimeError):
        print("Research stopped: inspect data quality, collection status and configuration. No credentials or production fallback.",file=sys.stderr)
        raise SystemExit(1)
