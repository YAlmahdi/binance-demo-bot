"""Read-only market database audit. No credentials, settings or network imports."""
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import sqlite3

from .backtest import FundingEvent
from .data import Candle, DataQualityError, INTERVAL_MS, validate_candles


def utc(timestamp):
    return datetime.fromtimestamp(timestamp / 1000, timezone.utc).isoformat() if timestamp is not None else None


def audit_candles(candles, interval):
    bars = list(candles)
    step = INTERVAL_MS[interval]
    if not bars:
        return {"rows": 0, "quality_passed": False, "status": "absent"}
    gaps = []
    for left, right in zip(bars, bars[1:]):
        if right.open_time - left.open_time != step:
            gaps.append({"after_utc": utc(left.open_time), "before_utc": utc(right.open_time),
                         "missing_intervals": max(0, (right.open_time - left.open_time)//step - 1)})
    valid = True
    try:
        validate_candles(bars, interval, require_contiguous=False)
    except (DataQualityError, ValueError):
        valid = False
    result = {"rows": len(bars), "start_utc": utc(bars[0].open_time), "end_utc": utc(bars[-1].close_time),
              "end_exclusive_ms": bars[-1].close_time + 1,
              "expected_rows_in_span": (bars[-1].open_time-bars[0].open_time)//step+1,
              "missing_intervals": sum(g["missing_intervals"] for g in gaps), "gap_ranges": gaps,
              "values_and_timestamps_passed": valid, "quality_passed": valid and not gaps}
    if valid:
        result.update({
            "zero_volume_bars": sum(c.volume == 0 for c in bars),
            "zero_range_bars": sum(c.high == c.low for c in bars),
            "largest_bar_range_pct": max((c.high-c.low)/c.open*100 for c in bars),
            "bars_with_range_over_5pct": sum((c.high-c.low)/c.open > .05 for c in bars),
            "largest_adjacent_open_gap_pct": max((abs(b.open-a.close)/a.close*100 for a,b in zip(bars,bars[1:])), default=0),
        })
    return result


def funding_audit(rows, start=None, end=None):
    events = [FundingEvent(timestamp, rate, mark) for timestamp, rate, mark in rows]
    times = [e.timestamp for e in events]
    if times != sorted(set(times)):
        raise DataQualityError("Duplicate or unordered funding observations")
    differences = Counter(b-a for a,b in zip(times,times[1:]))
    modal = differences.most_common(1)[0][0] if differences else None
    absent, shifted = [], []
    if modal and start is not None and end is not None:
        # Diagnostic schedule assumption only, not proof of the historical exchange schedule.
        phase = times[0] % modal
        first = start + (phase-start) % modal
        known = set()
        for event in times:
            slot = phase + ((event-phase+modal//2)//modal)*modal
            if abs(event-slot) <= 1:
                known.add(slot)
                if event != slot:
                    shifted.append({"event_utc":utc(event),"schedule_utc":utc(slot),"offset_ms":event-slot})
        absent = [utc(t) for t in range(first,end,modal) if t not in known]
    return {"rows": len(events), "first_utc": utc(times[0]) if times else None,
            "last_utc": utc(times[-1]) if times else None,
            "missing_mark_prices": sum(e.mark_price is None for e in events),
            "observed_spacing_ms": dict(sorted(differences.items())),
            "modal_spacing_ms": modal, "schedule_matching_tolerance_ms": 1,
            "near_schedule_shifted_events": shifted, "absent_under_modal_schedule_utc": absent,
            "schedule_warning": "Schedule diagnostics allow 1ms event jitter only; settlement keeps original timestamps. Historical schedule/completeness is not independently verified."}


def audit_database(path):
    path = Path(path).resolve()
    if path.suffix.lower() not in (".db", ".sqlite", ".sqlite3"):
        raise ValueError("A historical database path is required")
    result = {"path": str(path), "candles": {}, "funding": {}}
    with closing(sqlite3.connect(path.as_uri()+"?mode=ro", uri=True)) as db:
        result["integrity"] = db.execute("PRAGMA integrity_check").fetchone()[0]
        for symbol in ("BTCUSDT", "ETHUSDT"):
            for interval in INTERVAL_MS:
                rows = db.execute("SELECT open_time,open,high,low,close,volume,close_time,quote_volume,trades "
                                  "FROM candles WHERE symbol=? AND interval=? ORDER BY open_time", (symbol,interval)).fetchall()
                result["candles"][symbol+":"+interval] = audit_candles([Candle(*r) for r in rows],interval)
            coverage = result["candles"][symbol+":5m"]
            records = db.execute("SELECT timestamp,rate,mark_price FROM funding WHERE symbol=? ORDER BY timestamp",(symbol,)).fetchall()
            start = int(datetime.fromisoformat(coverage["start_utc"]).timestamp()*1000) if coverage["rows"] else None
            result["funding"][symbol] = funding_audit(records,start,coverage.get("end_exclusive_ms"))
    return result
