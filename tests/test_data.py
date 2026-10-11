import math
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from demo_futures.data import Candle, DataQualityError, SQLiteStore, closed_candles, validate_candles


def candle(start=0):
    return Candle(start, 100.0, 110.0, 90.0, 105.0, 12.0, start + 299_999, 1200.0, 6)


class CandleTests(unittest.TestCase):
    def test_parse_binance_and_validate(self):
        value = Candle.from_binance([0, "100", "110", "90", "105", "12", 299999, "1200", 6, "0", "0", "0"])
        self.assertEqual(validate_candles([value], "5m", now_ms=300000), [candle()])

    def test_reject_nonfinite_negative_and_inconsistent_prices(self):
        for values in ({"close": math.nan}, {"volume": math.inf}, {"volume": -1},
                       {"low": 106}, {"high": 99}, {"open": 0}, {"trades": -1},
                       {"quote_volume": -1}):
            with self.subTest(values=values), self.assertRaises(DataQualityError):
                validate_candles([replace(candle(), **values)], "5m", now_ms=300000)

    def test_reject_gaps_duplicates_and_reverse_order(self):
        for rows in ([candle(), candle(600000)], [candle(), candle()], [candle(300000), candle()]):
            with self.subTest(rows=rows), self.assertRaises(DataQualityError):
                validate_candles(rows, "5m", now_ms=1_000_000)

    def test_invalid_interval_and_timestamp(self):
        for interval, value in (("1m", candle()), ("5m", replace(candle(), open_time=1)),
                                ("5m", replace(candle(), close_time=300000)),
                                ("5m", replace(candle(), open_time=0.5))):
            with self.subTest(interval=interval, value=value), self.assertRaises(DataQualityError):
                validate_candles([value], interval, now_ms=1_000_000)

    def test_closed_boundary_and_filter(self):
        with self.assertRaises(DataQualityError):
            validate_candles([candle()], "5m", now_ms=299999)
        self.assertEqual(closed_candles([candle(), candle(300000)], now_ms=300000), [candle()])

    def test_malformed_wire_data(self):
        for row in ([], [0, "bad", 1, 1, 1, 1, 299999, 0, 0], [0.1, 1, 1, 1, 1, 1, 299999, 0, 0]):
            with self.subTest(row=row), self.assertRaises(DataQualityError):
                Candle.from_binance(row)


class SQLiteTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "nested" / "market.sqlite3"
        self.store = SQLiteStore(self.path)

    def tearDown(self):
        self.directory.cleanup()

    def test_idempotent_persistence_and_range(self):
        self.store.upsert_candles("BTCUSDT", "5m", [candle(), candle(300000)])
        self.store.upsert_candles("BTCUSDT", "5m", [replace(candle(), close=106)])
        reopened = SQLiteStore(self.path)
        self.assertEqual(len(reopened.load_candles("BTCUSDT", "5m")), 2)
        self.assertEqual(reopened.load_candles("BTCUSDT", "5m")[0].close, 106)
        self.assertEqual(reopened.load_candles("BTCUSDT", "5m", start_ms=300000), [candle(300000)])
        self.assertEqual(reopened.load_candles("ETHUSDT", "5m"), [])

    def test_batch_validation_prevents_partial_write(self):
        with self.assertRaises(DataQualityError):
            self.store.upsert_candles("BTCUSDT", "5m", [candle(), replace(candle(300000), close=math.nan)])
        self.assertEqual(self.store.load_candles("BTCUSDT", "5m"), [])

    def test_storage_gap_detected_on_read(self):
        self.store.upsert_candles("BTCUSDT", "5m", [candle()])
        self.store.upsert_candles("BTCUSDT", "5m", [candle(600000)])
        with self.assertRaises(DataQualityError):
            self.store.load_candles("BTCUSDT", "5m")

    def test_snapshot_idempotence_and_availability_time(self):
        funding = {"symbol": "BTCUSDT", "fundingTime": 8000, "fundingRate": "-0.0001", "markPrice": "100"}
        oi = {"symbol": "BTCUSDT", "time": 9000, "openInterest": "12"}
        self.store.upsert_funding("BTCUSDT", [funding], observed_at_ms=10000)
        self.store.upsert_funding("BTCUSDT", [funding], observed_at_ms=20000)
        self.store.upsert_open_interest("BTCUSDT", [oi], observed_at_ms=10000)
        self.store.upsert_open_interest("BTCUSDT", [oi], observed_at_ms=20000)
        self.assertEqual(len(self.store.load_funding("BTCUSDT")), 1)
        self.assertEqual(self.store.load_funding("BTCUSDT")[0]["observed_at_ms"], 10000)
        self.assertEqual(self.store.load_open_interest("BTCUSDT")[0]["observed_at_ms"], 10000)
        self.assertEqual(self.store.load_open_interest("BTCUSDT")[0]["openInterest"], 12)

    def test_snapshot_invalid_data_and_symbol(self):
        with self.assertRaises(DataQualityError):
            self.store.upsert_funding("BTCUSDT", [{"fundingTime": 0, "fundingRate": "NaN"}])
        with self.assertRaises(DataQualityError):
            self.store.upsert_open_interest("BTCUSDT", [{"time": 0, "openInterest": -1}])
        with self.assertRaises(DataQualityError):
            self.store.upsert_candles("BNBUSDT", "5m", [])


if __name__ == "__main__":
    unittest.main()
