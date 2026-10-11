"""Offline component integration + explicitly opted-in public Demo smoke test."""
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from contextlib import closing
from urllib.parse import urlsplit, parse_qs
from unittest.mock import patch

from demo_futures.client import DemoClient, APIError
from demo_futures.config import Settings
from demo_futures.collector import collect
from demo_futures.data import SQLiteStore, DataQualityError
from test_client import FakeTransport


class MarketTransport(FakeTransport):
    def send(self, method, url, headers, body):
        path = urlsplit(url).path
        args = parse_qs(urlsplit(url).query)
        if path == "/fapi/v1/klines":
            self.calls.append((method, url, headers, body))
            start = int(args["startTime"][0])
            # One candle/page to force actual pagination through client and storage.
            return [[start, "100", "110", "90", "105", "20", start + 299999, "2000", 3, "0", "0", "0"]]
        if path == "/fapi/v1/fundingRate":
            return [{"symbol": "BTCUSDT", "fundingTime": 300000, "fundingRate": "0.0001", "markPrice": "100"}]
        if path == "/fapi/v1/openInterest":
            return {"symbol": "BTCUSDT", "time": 900000, "openInterest": "123"}
        return super().send(method, url, headers, body)


class IntegrationTests(unittest.TestCase):
    @patch("demo_futures.collector.time.sleep")
    def test_paginated_ingest_idempotent_and_report_persisted(self, _sleep):
        with tempfile.TemporaryDirectory() as temp:
            store = SQLiteStore(Path(temp) / "market.sqlite3")
            client = DemoClient(Settings(), MarketTransport())
            for _ in range(2):
                report = collect(client, store, 0, 900000, ["BTCUSDT"], ["5m"])
                self.assertEqual(report["candles"]["BTCUSDT:5m"], 3)
            self.assertEqual(len(store.load_candles("BTCUSDT", "5m")), 3)
            self.assertEqual(len(store.load_funding("BTCUSDT")), 1)
            self.assertEqual(len(store.load_open_interest("BTCUSDT")), 1)
            with closing(sqlite3.connect(store.path)) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM collection_runs").fetchone()[0], 2)

    def test_missing_first_candle_stops_ingestion(self):
        transport = MarketTransport()
        original = transport.send
        def gap(method, url, headers, body):
            rows = original(method, url, headers, body)
            if urlsplit(url).path.endswith("klines"):
                rows[0][0] += 300000
                rows[0][6] += 300000
            return rows
        transport.send = gap
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(DataQualityError):
            collect(DemoClient(Settings(), transport), SQLiteStore(Path(temp) / "db"), 0, 900000, ["BTCUSDT"], ["5m"])

    @unittest.skipUnless(os.environ.get("RUN_DEMO_INTEGRATION") == "1", "Public Demo network test is opt-in")
    def test_public_demo_network(self):
        self.assertGreater(DemoClient(Settings()).verify(), 0)
