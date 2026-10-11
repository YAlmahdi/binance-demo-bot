import hashlib
import hmac
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit, parse_qs

from demo_futures.client import DemoClient, APIError, NoRedirect, Transport
from demo_futures.config import Settings, SafetyError, DEMO_REST


def exchange_info():
    return {"symbols": [{"symbol": s, "status": "TRADING", "contractType": "PERPETUAL",
        "quoteAsset": "USDT", "marginAsset": "USDT", "filters": [
            {"filterType": "LOT_SIZE", "minQty": "0.001", "maxQty": "100", "stepSize": "0.001"},
            {"filterType": "PRICE_FILTER", "minPrice": "0.10", "maxPrice": "1000000", "tickSize": "0.10"},
            {"filterType": "MIN_NOTIONAL", "notional": "100"}]} for s in ("BTCUSDT", "ETHUSDT")]}


class FakeTransport:
    def __init__(self):
        self.calls = []
        self.fail_path = None
        self.clock_skew = 0

    def send(self, method, url, headers, body):
        self.calls.append((method, url, headers, body))
        path = urlsplit(url).path
        if path == self.fail_path:
            raise APIError(503)
        if path == "/fapi/v1/ping":
            return {}
        if path == "/fapi/v1/time":
            return {"serverTime": int(time.time() * 1000) + self.clock_skew}
        if path == "/fapi/v1/exchangeInfo":
            return exchange_info()
        if path == "/fapi/v3/balance":
            return [{"asset": "USDT", "balance": "10000"}]
        if path == "/fapi/v1/openOrders":
            return []
        if path == "/fapi/v1/order/test":
            return {}
        raise AssertionError(path)


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.transport = FakeTransport()
        self.client = DemoClient(Settings("dummy-key", "dummy-secret"), self.transport)

    def test_production_and_deceptive_origins_blocked(self):
        for url in ("https://fapi.binance.com", DEMO_REST + "/", DEMO_REST + ".evil.test",
                    "http://demo-fapi.binance.com", DEMO_REST + ":443", DEMO_REST + "@evil.test"):
            with self.subTest(url=url), self.assertRaises(SafetyError):
                DemoClient(Settings(base_url=url), self.transport)
        self.assertEqual(self.transport.calls, [])

    def test_endpoint_allowlist(self):
        for method, path in (("POST", "/fapi/v1/order"), ("DELETE", "/fapi/v1/order"),
                             ("GET", "https://fapi.binance.com/fapi/v1/time"),
                             ("POST", "/fapi/v1/leverage"), ("GET", "/fapi/v1/order/test")):
            with self.assertRaises(SafetyError):
                self.client.request(method, path)
        self.assertFalse(self.transport.calls)

    def test_signed_access_requires_verification(self):
        with self.assertRaises(SafetyError):
            self.client.request("GET", "/fapi/v3/balance")
        self.assertFalse(self.transport.calls)

    def test_expired_verification(self):
        self.client.verify()
        self.client._verified_at = time.monotonic() - 61
        with self.assertRaises(SafetyError):
            self.client.request("GET", "/fapi/v3/balance")

    def test_credentials_required(self):
        client = DemoClient(Settings(), self.transport)
        client.verify()
        with self.assertRaises(SafetyError):
            client.request("GET", "/fapi/v3/balance")

    def test_account_signing_and_origin(self):
        result = self.client.account_check()
        self.assertEqual(result["balances"][0]["asset"], "USDT")
        call = next(c for c in self.transport.calls if "/fapi/v3/balance?" in c[1])
        query, signature = urlsplit(call[1]).query.rsplit("&signature=", 1)
        expected = hmac.new(b"dummy-secret", query.encode(), hashlib.sha256).hexdigest()
        self.assertEqual(signature, expected)
        self.assertEqual(call[2]["X-MBX-APIKEY"], "dummy-key")
        for _, url, _, _ in self.transport.calls:
            self.assertEqual(urlsplit(url).netloc, "demo-fapi.binance.com")
        self.assertNotIn("X-MBX-APIKEY", self.transport.calls[0][2])

    def test_skew_fails_closed(self):
        self.transport.clock_skew = 120_000
        with self.assertRaises(SafetyError):
            self.client.verify()
        self.assertEqual(self.client._verified_at, 0)

    def test_network_error_revokes_verification_no_retry(self):
        self.client.verify()
        self.transport.fail_path = "/fapi/v3/balance"
        with self.assertRaises(APIError):
            self.client.request("GET", "/fapi/v3/balance")
        self.assertEqual(self.client._verified_at, 0)
        self.assertEqual(sum("/balance?" in c[1] for c in self.transport.calls), 1)

    def test_test_order_does_not_use_execution_endpoint(self):
        self.client.test_order("BTCUSDT", "BUY", "0.002", "60000.10")
        post = self.transport.calls[-1]
        self.assertEqual((post[0], post[1]), ("POST", DEMO_REST + "/fapi/v1/order/test"))
        self.assertIn(b"signature=", post[3])

    def test_post_failure_single_attempt(self):
        self.transport.fail_path = "/fapi/v1/order/test"
        with self.assertRaises(APIError):
            self.client.test_order("BTCUSDT", "BUY", "0.002", "60000")
        self.assertEqual(sum(c[0] == "POST" for c in self.transport.calls), 1)

    def test_order_filters(self):
        for qty, price in (("0.0021", "60000"), ("0.002", "60000.01"), ("0.001", "60000"),
                           ("NaN", "60000"), ("1", "Infinity"), ("-1", "60000")):
            with self.subTest(qty=qty, price=price), self.assertRaises(SafetyError):
                self.client.test_order("BTCUSDT", "BUY", qty, price)
        self.assertFalse(any(c[0] == "POST" for c in self.transport.calls))

    def test_redirect_blocked(self):
        with self.assertRaises(SafetyError):
            NoRedirect().redirect_request(None, None, 302, "", {}, "https://fapi.binance.com")

    def test_transport_rejects_foreign_origin_before_network(self):
        with self.assertRaises(SafetyError):
            Transport().send("GET", "https://fapi.binance.com/fapi/v1/time", {}, None)

    def test_env_and_repr_do_not_reveal_secrets(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {}, clear=True):
            path = Path(temp) / ".env"
            path.write_text('BINANCE_ENV=demo\nBINANCE_DEMO_API_KEY="dummy-key"\nBINANCE_DEMO_API_SECRET=dummy-secret\n', encoding="utf-8")
            settings = Settings.load(path)
            self.assertEqual(settings.api_secret, "dummy-secret")
            self.assertNotIn("dummy", repr(settings))
            with patch.dict(os.environ, {"BINANCE_ENV": "live"}), self.assertRaises(SafetyError):
                Settings.load(path)


if __name__ == "__main__":
    unittest.main()
