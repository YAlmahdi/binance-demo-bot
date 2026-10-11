import json
import logging
import sqlite3
import time
from contextlib import closing

from .client import APIError
from .config import SYMBOLS, INTERVALS
from .data import Candle, closed_candles, validate_candles, DataQualityError

log = logging.getLogger(__name__)


def collect(client, store, start_ms, end_ms=None, symbols=SYMBOLS, intervals=tuple(INTERVALS)):
    """Paginate a bounded UTC range. Fail on missing candles; never fill data gaps."""
    if not symbols or not intervals or not set(symbols) <= set(SYMBOLS) or not set(intervals) <= set(INTERVALS):
        raise DataQualityError("Unsupported or empty market selection")
    server_ms = client.verify()
    end_ms = min(server_ms, end_ms if end_ms is not None else server_ms)
    if start_ms < 0 or start_ms >= end_ms:
        raise DataQualityError("Invalid collection time range")
    report = {"started_at_ms": int(time.time() * 1000), "start_ms": start_ms,
              "end_ms": end_ms, "candles": {}, "optional": {}}
    for symbol in symbols:
        for interval in intervals:
            step = INTERVALS[interval]
            cursor = ((start_ms + step - 1) // step) * step
            # Require full candles only; end_ms is an exclusive bound.
            last = (end_ms // step - 1) * step
            total = 0
            while cursor <= last:
                rows = client.request("GET", "/fapi/v1/klines", {
                    "symbol": symbol, "interval": interval, "startTime": cursor,
                    "endTime": last + step - 1, "limit": 1000})
                candles = validate_candles(closed_candles([Candle.from_binance(r) for r in rows], server_ms), interval, server_ms)
                if not candles or candles[0].open_time != cursor or candles[-1].open_time > last:
                    raise DataQualityError("Missing or out-of-range historical candles")
                total += store.upsert_candles(symbol, interval, candles)
                cursor = candles[-1].open_time + step
                time.sleep(0.15)
            report["candles"][f"{symbol}:{interval}"] = total
            log.info("Validated %s %s: %d closed candles", symbol, interval, total)
        for dataset, path in (("funding", "/fapi/v1/fundingRate"), ("open_interest", "/fapi/v1/openInterest")):
            key = f"{symbol}:{dataset}"
            try:
                if dataset == "funding":
                    cursor, count = start_ms, 0
                    while cursor < end_ms:
                        rows = client.request("GET", path, {"symbol": symbol, "startTime": cursor,
                                                            "endTime": end_ms - 1, "limit": 1000})
                        if not rows:
                            break
                        times = [int(r["fundingTime"]) for r in rows]
                        if times != sorted(set(times)) or times[0] < cursor or times[-1] >= end_ms:
                            raise DataQualityError("Invalid funding chronology")
                        count += store.upsert_funding(symbol, rows)
                        cursor = times[-1] + 1
                        if len(rows) < 1000:
                            break
                        time.sleep(0.15)
                else:
                    # A current observation, never a reconstruction of historical OI.
                    row = client.request("GET", path, {"symbol": symbol})
                    count = store.upsert_open_interest(symbol, [row])
                report["optional"][key] = {"status": "available" if count else "empty", "rows": count}
            except APIError as exc:
                # Only explicit unsupported responses are optional; auth, bans and outages stop ingestion.
                if exc.status != 404 and exc.code != -1121:
                    raise
                report["optional"][key] = {"status": "unavailable", "http": exc.status, "code": exc.code}
                log.warning("Demo dataset unavailable: %s", key)
    with closing(sqlite3.connect(store.path)) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS collection_runs (id INTEGER PRIMARY KEY, created_ms INTEGER, report_json TEXT)")
        db.execute("INSERT INTO collection_runs(created_ms, report_json) VALUES (?, ?)",
                   (int(time.time() * 1000), json.dumps(report)))
    return report
