"""Bounded public market-data ingestion for future expansion, never active research."""
from dataclasses import asdict
from decimal import Decimal
from .data import Candle, DataQualityError, validate_candles
from .history_audit import audit_candles, funding_audit, utc
from .public_history import FUTURE_EXPANSION_SYMBOLS, DAY, STEP, PublicHistoryError

PAGE_BARS = 499  # Official request-weight tier 2, rather than 5 at limit=500.


def validate_range(symbol, start, end, server_time):
    if symbol not in FUTURE_EXPANSION_SYMBOLS:
        raise DataQualityError("Only the three data-only expansion symbols are allowed")
    if any(type(v) is not int for v in (start, end, server_time)):
        raise DataQualityError("Integer UTC milliseconds required")
    if start < 0 or start % STEP or end % STEP or not start < end:
        raise DataQualityError("Aligned nonempty range required")
    if end > server_time // STEP * STEP or end - start > 180 * DAY:
        raise DataQualityError("Only completed history up to 180 days is allowed")


def contract_metadata(info, symbol):
    if symbol not in FUTURE_EXPANSION_SYMBOLS:
        raise DataQualityError("Unsupported expansion symbol")
    items = [v for v in info["symbols"] if v.get("symbol") == symbol]
    if len(items) != 1:
        raise DataQualityError("Exact unique Demo contract metadata unavailable")
    item = items[0]
    if (item.get("contractType"), item.get("quoteAsset"), item.get("marginAsset"), item.get("status")) != ("PERPETUAL", "USDT", "USDT", "TRADING"):
        raise DataQualityError("Demo USDT perpetual contract unavailable")
    return item


def candle_page(rows, start, end, server_time):
    bars = [Candle.from_binance(r) for r in rows]
    validate_candles(bars, "5m", server_time, require_contiguous=False)
    if any(not start <= b.open_time < end for b in bars):
        raise DataQualityError("Candle response shifted outside requested bounds")
    return bars


def candle_defects(rows, start, end, server_time):
    """Raw-page diagnostics; never correct, sort or deduplicate a response."""
    result = {"duplicate_rows": 0, "non_monotonic_rows": 0, "invalid_rows": 0}
    seen, previous = set(), None
    for row in rows:
        try:
            bar = Candle.from_binance(row)
            if bar.open_time in seen:
                result["duplicate_rows"] += 1
            if previous is not None and bar.open_time < previous:
                result["non_monotonic_rows"] += 1
            seen.add(bar.open_time)
            previous = bar.open_time
            validate_candles([bar], "5m", server_time)
            if not start <= bar.open_time < end:
                raise DataQualityError("Outside window")
        except (DataQualityError, TypeError, ValueError, ArithmeticError):
            result["invalid_rows"] += 1
    return result


def funding_page(rows, symbol, start, end):
    times = []
    for row in rows:
        try:
            t = row["fundingTime"]
            rate, mark = row["fundingRate"], row.get("markPrice")
            if row.get("symbol") != symbol or type(t) is not int or not start <= t < end or isinstance(rate, bool):
                raise ValueError()
            if not Decimal(str(rate)).is_finite():
                raise ValueError()
            if mark not in (None, "") and (isinstance(mark, bool) or not Decimal(str(mark)).is_finite() or Decimal(str(mark)) <= 0):
                raise ValueError()
            times.append(t)
        except (KeyError, TypeError, ValueError, ArithmeticError):
            raise DataQualityError("Invalid expansion funding row") from None
    if times != sorted(set(times)):
        raise DataQualityError("Duplicate or non-monotonic funding rows")
    return rows


def probe(client, symbol, start, end, server_time):
    validate_range(symbol, start, end, server_time)
    evidence = []
    for left in sorted({start, start + (end - start) // (2 * STEP) * STEP, end - STEP}):
        params = dict(symbol=symbol, interval="5m", startTime=left, endTime=left+STEP-1, limit=1)
        rows = client.get("/fapi/v1/klines", params)
        bars = candle_page(rows, left, left + STEP, server_time)
        evidence.append({"kind": "candle", "requested_open_utc": utc(left), "rows": len(bars), "returned_open_utc": utc(bars[0].open_time) if bars else None})
    for left, limit in ((start, 1), (max(start, end-DAY), 1000)):
        rows = client.get("/fapi/v1/fundingRate", dict(symbol=symbol, startTime=left, endTime=end-1, limit=limit))
        funding_page(rows, symbol, left, end)
        evidence.append({"kind": "funding", "requested_start_utc": utc(left), "rows": len(rows), "first_utc": utc(rows[0]["fundingTime"]) if rows else None, "last_utc": utc(rows[-1]["fundingTime"]) if rows else None})
    return evidence


def collect(client, symbol, start, end, server_time, progress=None):
    """Scan every fixed requested window; missing pages are evidence, not shifted dates."""
    validate_range(symbol, start, end, server_time)
    bars, funding, failures = [], [], []
    defects = {"duplicate_rows": 0, "non_monotonic_rows": 0, "invalid_rows": 0}
    scanned_end = start
    for left in range(start, end, PAGE_BARS * STEP):
        right = min(end, left + PAGE_BARS * STEP)
        try:
            rows = client.get("/fapi/v1/klines", dict(symbol=symbol, interval="5m", startTime=left, endTime=right-1, limit=(right-left)//STEP))
        except PublicHistoryError as error:
            failures.append({"kind": "transport_stop", "http_status": error.status, "failure_kind": error.kind})
            return bars, funding, failures, defects, scanned_end, start
        page_defects = candle_defects(rows, left, right, server_time)
        for key in defects:
            defects[key] += page_defects[key]
        try:
            page = candle_page(rows, left, right, server_time)
        except DataQualityError:
            failures.append({"kind": "rejected_candle_page", "start_utc": utc(left), "end_exclusive_utc": utc(right), "raw_rows_excluded": len(rows)})
            break  # Stop this symbol instead of hiding or repairing malformed data.
        bars.extend(page)
        scanned_end = right
        if progress:
            progress(symbol, "candles", len(bars), scanned_end)
    funding_scanned_end = start
    for left in range(start, end, 7 * DAY):
        right, cursor = min(end, left + 7 * DAY), left
        while cursor < right:
            try:
                rows = client.get("/fapi/v1/fundingRate", dict(symbol=symbol, startTime=cursor, endTime=right-1, limit=1000))
            except PublicHistoryError as error:
                failures.append({"kind": "transport_stop", "http_status": error.status, "failure_kind": error.kind})
                return bars, funding, failures, defects, scanned_end, funding_scanned_end
            try:
                funding_page(rows, symbol, cursor, right)
            except DataQualityError:
                failures.append({"kind": "rejected_funding_page", "start_utc": utc(cursor), "end_exclusive_utc": utc(right), "raw_rows_excluded": len(rows)})
                return bars, funding, failures, defects, scanned_end, funding_scanned_end
            if not rows:
                break
            funding.extend(rows)
            cursor = rows[-1]["fundingTime"] + 1
            # Query again after short pages to establish endpoint exhaustion.
        funding_scanned_end = right
        if progress:
            progress(symbol, "funding", len(funding), right)
    return bars, funding, failures, defects, scanned_end, funding_scanned_end


def audit(bars, funding, start, end, server_time):
    validate_candles(bars, "5m", server_time, require_contiguous=False)
    quality = audit_candles(bars, "5m")
    present = {bar.open_time for bar in bars}
    missing = []
    left = None
    for t in range(start, end, STEP):
        if t not in present and left is None:
            left = t
        elif t in present and left is not None:
            missing.append({"start_utc": utc(left), "end_exclusive_utc": utc(t), "bars": (t-left)//STEP})
            left = None
    if left is not None:
        missing.append({"start_utc": utc(left), "end_exclusive_utc": utc(end), "bars": (end-left)//STEP})
    quality.update(target_rows=(end-start)//STEP, missing_target_intervals=sum(g["bars"] for g in missing), missing_target_ranges=missing, covers_target=len(present)==(end-start)//STEP)
    events = [(v["fundingTime"], v["fundingRate"], v.get("markPrice") or None) for v in funding]
    fund = funding_audit(events, start, end)
    fund.update(completeness="UNKNOWN", reason="Endpoint pagination exhaustion and modal spacing do not independently establish the historical settlement schedule. Missing events are never zero.", uncertain_coverage={"start_utc": utc(start), "end_exclusive_utc": utc(end)}, signed_rate_min=str(min((Decimal(v["fundingRate"]) for v in funding), default=Decimal(0))) if funding else None, signed_rate_max=str(max((Decimal(v["fundingRate"]) for v in funding), default=Decimal(0))) if funding else None, negative_rates=sum(Decimal(v["fundingRate"])<0 for v in funding), positive_rates=sum(Decimal(v["fundingRate"])>0 for v in funding), zero_rates=sum(Decimal(v["fundingRate"])==0 for v in funding))
    return {"candles": quality, "funding": fund}


def candle_records(bars, symbol):
    return [dict(symbol=symbol, interval="5m", **asdict(b)) for b in bars]
