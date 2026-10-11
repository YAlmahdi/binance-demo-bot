"""Validated, closed market candles and durable local market-data storage.

Timestamps are UTC Unix milliseconds. No credentials or account information are
stored here. Market metadata is deliberately separate from execution state.
"""

from __future__ import annotations

import math
import sqlite3
import time
from dataclasses import dataclass
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator, Mapping, Sequence


INTERVAL_MS = {"5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}
SUPPORTED_SYMBOLS = frozenset({"BTCUSDT", "ETHUSDT"})


class DataQualityError(ValueError):
    """Market data cannot safely be used for research or a trading decision."""


def _integer(value: object) -> int:
    if isinstance(value, bool):
        raise DataQualityError("Boolean values are not timestamps or counts")
    try:
        result = int(value)  # type: ignore[arg-type]
        if float(value) != result:  # type: ignore[arg-type]
            raise ValueError("fractional integer")
        return result
    except (ValueError, TypeError, OverflowError) as exc:
        raise DataQualityError("Invalid timestamp or trade count") from exc


@dataclass(frozen=True)
class Candle:
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: int
    quote_volume: float = 0.0
    trades: int = 0

    @classmethod
    def from_binance(cls, row: Sequence[object]) -> "Candle":
        if len(row) < 9:
            raise DataQualityError("Binance kline requires at least nine fields")
        try:
            return cls(
                open_time=_integer(row[0]), open=float(row[1]), high=float(row[2]),
                low=float(row[3]), close=float(row[4]), volume=float(row[5]),
                close_time=_integer(row[6]), quote_volume=float(row[7]),
                trades=_integer(row[8]),
            )
        except (ValueError, TypeError, OverflowError) as exc:
            raise DataQualityError("Malformed Binance candle") from exc


def closed_candles(candles: Iterable[Candle], now_ms: int | None = None) -> list[Candle]:
    """Discard unfinished candles before strict validation (REST includes one)."""
    cutoff = int(time.time() * 1000) if now_ms is None else now_ms
    return [candle for candle in candles if candle.close_time < cutoff]


def validate_candles(
    candles: Iterable[Candle], interval: str, now_ms: int | None = None,
    require_contiguous: bool = True,
) -> list[Candle]:
    """Validate without sorting, deduplicating, filling gaps, or hiding bad rows."""
    if interval not in INTERVAL_MS:
        raise DataQualityError(f"Unsupported interval: {interval}")
    duration = INTERVAL_MS[interval]
    cutoff = int(time.time() * 1000) if now_ms is None else now_ms
    result = list(candles)
    previous: int | None = None
    for candle in result:
        start, end, trades = (_integer(candle.open_time), _integer(candle.close_time),
                              _integer(candle.trades))
        values = (candle.open, candle.high, candle.low, candle.close,
                  candle.volume, candle.quote_volume)
        try:
            if not all(math.isfinite(value) for value in values):
                raise DataQualityError("Non-finite OHLCV value")
            if min(candle.open, candle.high, candle.low, candle.close) <= 0:
                raise DataQualityError("Prices must be positive")
            if candle.low > min(candle.open, candle.close) or candle.high < max(candle.open, candle.close):
                raise DataQualityError("OHLC prices are inconsistent")
            if candle.volume < 0 or candle.quote_volume < 0 or trades < 0:
                raise DataQualityError("Volume and trade counts must be non-negative")
        except TypeError as exc:
            raise DataQualityError("OHLCV values must be numbers") from exc
        if start < 0 or start % duration != 0 or end != start + duration - 1:
            raise DataQualityError("Candle timestamps do not match the interval")
        if end >= cutoff:
            raise DataQualityError("Unfinished candle cannot be stored or analyzed")
        if previous is not None:
            if start <= previous:
                raise DataQualityError("Candles must be unique and strictly chronological")
            if require_contiguous and start - previous != duration:
                raise DataQualityError("Missing candle interval detected")
        previous = start
    return result


def _check_market(symbol: str, interval: str | None = None) -> None:
    if symbol not in SUPPORTED_SYMBOLS:
        raise DataQualityError(f"Unsupported symbol: {symbol}")
    if interval is not None and interval not in INTERVAL_MS:
        raise DataQualityError(f"Unsupported interval: {interval}")


class SQLiteStore:
    """Atomic idempotent ingestion; primary keys prevent duplicated observations."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS candles (
                    symbol TEXT NOT NULL, interval TEXT NOT NULL,
                    open_time INTEGER NOT NULL, open REAL NOT NULL,
                    high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL,
                    volume REAL NOT NULL, close_time INTEGER NOT NULL,
                    quote_volume REAL NOT NULL, trades INTEGER NOT NULL,
                    PRIMARY KEY (symbol, interval, open_time));
                CREATE TABLE IF NOT EXISTS funding (
                    symbol TEXT NOT NULL, timestamp INTEGER NOT NULL,
                    rate REAL NOT NULL, mark_price REAL, observed_at_ms INTEGER NOT NULL,
                    PRIMARY KEY (symbol, timestamp));
                CREATE TABLE IF NOT EXISTS open_interest (
                    symbol TEXT NOT NULL, timestamp INTEGER NOT NULL,
                    quantity REAL NOT NULL, observed_at_ms INTEGER NOT NULL,
                    PRIMARY KEY (symbol, timestamp));
            """)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=15)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def upsert_candles(self, symbol: str, interval: str, candles: Iterable[Candle]) -> int:
        _check_market(symbol, interval)
        rows = validate_candles(candles, interval)
        with self._connect() as connection:
            connection.executemany("""
                INSERT INTO candles VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, interval, open_time) DO UPDATE SET
                  open=excluded.open, high=excluded.high, low=excluded.low,
                  close=excluded.close, volume=excluded.volume,
                  close_time=excluded.close_time, quote_volume=excluded.quote_volume,
                  trades=excluded.trades
            """, [(symbol, interval, c.open_time, c.open, c.high, c.low, c.close,
                   c.volume, c.close_time, c.quote_volume, c.trades) for c in rows])
        return len(rows)

    def load_candles(self, symbol: str, interval: str, start_ms: int | None = None,
                     end_ms: int | None = None) -> list[Candle]:
        """Read ascending candles; bounds refer to open times and are inclusive."""
        _check_market(symbol, interval)
        query = "SELECT open_time, open, high, low, close, volume, close_time, quote_volume, trades FROM candles WHERE symbol=? AND interval=?"
        parameters: list[object] = [symbol, interval]
        if start_ms is not None:
            query += " AND open_time>=?"
            parameters.append(_integer(start_ms))
        if end_ms is not None:
            query += " AND open_time<=?"
            parameters.append(_integer(end_ms))
        query += " ORDER BY open_time"
        with self._connect() as connection:
            result = [Candle(*row) for row in connection.execute(query, parameters)]
        return validate_candles(result, interval)

    def upsert_funding(self, symbol: str, records: Iterable[Mapping[str, object]],
                       observed_at_ms: int | None = None) -> int:
        _check_market(symbol)
        observed = _integer(int(time.time() * 1000) if observed_at_ms is None else observed_at_ms)
        if observed < 0:
            raise DataQualityError("Invalid observation time")
        rows = []
        for record in records:
            try:
                timestamp, rate = _integer(record["fundingTime"]), float(record["fundingRate"])
                mark = float(record["markPrice"]) if record.get("markPrice") not in (None, "") else None
                if timestamp < 0 or timestamp > observed or not math.isfinite(rate) or (mark is not None and (not math.isfinite(mark) or mark <= 0)):
                    raise ValueError("invalid funding snapshot")
                if record.get("symbol", symbol) != symbol:
                    raise ValueError("symbol mismatch")
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                raise DataQualityError("Invalid funding snapshot") from exc
            rows.append((symbol, timestamp, rate, mark, observed))
        with self._connect() as connection:
            connection.executemany("INSERT INTO funding VALUES (?, ?, ?, ?, ?) ON CONFLICT(symbol, timestamp) DO NOTHING", rows)
        return len(rows)

    def upsert_open_interest(self, symbol: str, records: Iterable[Mapping[str, object]],
                             observed_at_ms: int | None = None) -> int:
        _check_market(symbol)
        observed = _integer(int(time.time() * 1000) if observed_at_ms is None else observed_at_ms)
        if observed < 0:
            raise DataQualityError("Invalid observation time")
        rows = []
        for record in records:
            try:
                timestamp = _integer(record["time"])
                quantity = float(record["openInterest"])
                if timestamp < 0 or timestamp > observed or not math.isfinite(quantity) or quantity < 0 or record.get("symbol", symbol) != symbol:
                    raise ValueError("invalid open interest snapshot")
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                raise DataQualityError("Invalid open interest snapshot") from exc
            rows.append((symbol, timestamp, quantity, observed))
        with self._connect() as connection:
            connection.executemany("INSERT INTO open_interest VALUES (?, ?, ?, ?) ON CONFLICT(symbol, timestamp) DO NOTHING", rows)
        return len(rows)

    def load_funding(self, symbol: str) -> list[dict[str, object]]:
        _check_market(symbol)
        with self._connect() as connection:
            return [dict(zip(("symbol", "fundingTime", "fundingRate", "markPrice", "observed_at_ms"), row))
                    for row in connection.execute("SELECT * FROM funding WHERE symbol=? ORDER BY timestamp", (symbol,))]

    def load_open_interest(self, symbol: str) -> list[dict[str, object]]:
        _check_market(symbol)
        with self._connect() as connection:
            return [dict(zip(("symbol", "time", "openInterest", "observed_at_ms"), row))
                    for row in connection.execute("SELECT * FROM open_interest WHERE symbol=? ORDER BY timestamp", (symbol,))]
