"""Partition-limited, immutable SQLite snapshot reads. No ingestion or settings."""
from contextlib import closing
from dataclasses import dataclass
import hashlib
from pathlib import Path
import sqlite3
from types import MappingProxyType

from ..backtest import FundingEvent
from ..data import Candle, validate_candles
from ..history_audit import audit_candles, funding_audit
from .config import START, DEV_END, STEP, SYMBOLS, require_development, timestamp


def file_hash(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


@dataclass(frozen=True)
class DevelopmentData:
    candles: object
    funding: object
    funding_gaps: object
    audit: dict
    database_hash: str


def snapshot_path(path):
    path = Path(path)
    if path.is_symlink() or path.suffix.lower() not in (".sqlite3", ".sqlite", ".db"):
        raise ValueError("A regular historical SQLite snapshot is required")
    path = path.resolve(strict=True)
    if any(Path(str(path) + suffix).exists() for suffix in ("-wal", "-journal")):
        raise ValueError("Use a stable checkpointed snapshot, not an active writer database")
    return path


def open_snapshot(path):
    path = snapshot_path(path)
    db = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
    db.execute("PRAGMA query_only=ON")
    return db


def load_development(path, expected_hash, *, start=START, end=DEV_END):
    # Check policy before opening/querying/hash-reading the requested input.
    require_development(start, end)
    if start != START or end != DEV_END:
        raise PermissionError("Experiment 001 has fixed development boundaries")
    path = snapshot_path(path)
    before = file_hash(path)
    if before != expected_hash:
        raise ValueError("Historical snapshot hash differs from the approved provenance")
    markets, funds, gaps, audits = {}, {}, {}, {}
    with closing(open_snapshot(path)) as db:
        # Structural database check is not a final-period observation/label inspection.
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("SQLite integrity check failed")
        for symbol in SYMBOLS:
            rows = db.execute(
                "SELECT open_time,open,high,low,close,volume,close_time,quote_volume,trades "
                "FROM candles WHERE symbol=? AND interval='5m' AND open_time>=? AND close_time<? "
                "ORDER BY open_time", (symbol, start, end)).fetchall()
            candles = tuple(Candle(*row) for row in rows)
            validate_candles(candles, "5m")
            if (not candles or candles[0].open_time != start or candles[-1].close_time + 1 != end
                    or len(candles) != (end - start) // STEP):
                raise ValueError("Development coverage is incomplete")
            records = db.execute(
                "SELECT timestamp,rate,mark_price FROM funding "
                "WHERE symbol=? AND timestamp>=? AND timestamp<? ORDER BY timestamp",
                (symbol, start, end)).fetchall()
            if not records:
                raise ValueError("Recorded development funding is absent")
            fa = funding_audit(records, start, end)
            funds[symbol] = tuple(FundingEvent(*r) for r in records)
            gaps[symbol] = tuple(timestamp(t) for t in fa["absent_under_modal_schedule_utc"])
            markets[symbol] = candles
            audits[symbol] = {"candles": audit_candles(candles, "5m"), "funding": fa}
    if tuple(c.open_time for c in markets[SYMBOLS[0]]) != tuple(c.open_time for c in markets[SYMBOLS[1]]):
        raise ValueError("Cross-symbol candle grids differ")
    if file_hash(path) != before:
        raise ValueError("Input changed during read-only loading")
    return DevelopmentData(MappingProxyType(markets), MappingProxyType(funds),
                           MappingProxyType(gaps), audits, before)
