"""Restricted REST client. TLS verification on; redirects and ambient proxies off."""
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation

from .config import DEMO_REST, SYMBOLS, Settings, SafetyError


class APIError(RuntimeError):
    def __init__(self, status=0, code=None):
        self.status, self.code = status, code
        super().__init__(f"Demo API failed (HTTP {status}, code {code}); stopped")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SafetyError("HTTP redirect blocked")


class Transport:
    def __init__(self):
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def send(self, method, url, headers, body):
        parts = urllib.parse.urlsplit(url)
        if (parts.scheme != "https" or parts.netloc != "demo-fapi.binance.com" or parts.fragment
                or parts.username or parts.password):
            raise SafetyError("Untrusted request URL")
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with self.opener.open(req, timeout=10) as response:
                if response.geturl() != url:
                    raise SafetyError("Unexpected response URL")
                return json.load(response)
        except urllib.error.HTTPError as exc:
            code = None
            try:
                code = json.loads(exc.read(65536)).get("code")
            except (ValueError, AttributeError):
                pass
            raise APIError(exc.code, code) from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            # Never expose signed URLs, credentials, or remote error payloads.
            raise APIError() from None


PUBLIC = {"/fapi/v1/ping", "/fapi/v1/time", "/fapi/v1/exchangeInfo", "/fapi/v1/klines",
          "/fapi/v1/fundingRate", "/fapi/v1/openInterest"}
PRIVATE = {"/fapi/v3/balance", "/fapi/v1/openOrders"}


class DemoClient:
    def __init__(self, settings: Settings, transport=None):
        settings.validate()
        self.settings = settings
        self.transport = transport or Transport()
        self._verified_at = 0.0
        self._offset_ms = 0
        self.exchange_info = None

    def request(self, method, path, params=None):
        self.settings.validate()
        signed = path in PRIVATE or path == "/fapi/v1/order/test"
        if not ((method == "GET" and path in PUBLIC | PRIVATE) or
                (method == "POST" and path == "/fapi/v1/order/test")):
            raise SafetyError("Endpoint/method not permitted in phase 1")
        values = dict(params or {})
        headers = {"User-Agent": "demo-futures-phase1/0.1"}
        if signed:
            if not self._verified_at or time.monotonic() - self._verified_at > 60:
                raise SafetyError("Demo verification missing or expired; run verification")
            if not self.settings.api_key or not self.settings.api_secret:
                raise SafetyError("Demo credentials missing in local .env")
            values.update(timestamp=int(time.time() * 1000) + self._offset_ms, recvWindow=5000)
            headers["X-MBX-APIKEY"] = self.settings.api_key
        query = urllib.parse.urlencode(values)
        if signed:
            signature = hmac.new(self.settings.api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
            query += "&signature=" + signature
        url = DEMO_REST + path
        body = None
        if method == "POST":
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            body = query.encode()
        elif query:
            url += "?" + query
        try:
            return self.transport.send(method, url, headers, body)
        except Exception:
            self._verified_at = 0
            raise

    def verify(self):
        self._verified_at = 0
        if self.request("GET", "/fapi/v1/ping") != {}:
            raise SafetyError("Unexpected ping response")
        before = int(time.time() * 1000)
        server = self.request("GET", "/fapi/v1/time")["serverTime"]
        after = int(time.time() * 1000)
        if not isinstance(server, int) or abs(server - after) > 60_000 or after - before > 5000:
            raise SafetyError("Server clock mismatch or excessive latency")
        info = self.request("GET", "/fapi/v1/exchangeInfo")
        available = {item["symbol"] for item in info["symbols"]
                     if item.get("status") == "TRADING" and item.get("contractType") == "PERPETUAL"
                     and item.get("quoteAsset") == "USDT" and item.get("marginAsset") == "USDT"}
        if not set(SYMBOLS) <= available:
            raise SafetyError("Expected USD-M perpetual Demo symbols unavailable")
        self.exchange_info = info
        self._offset_ms = server - (before + after) // 2
        self._verified_at = time.monotonic()
        return server

    def account_check(self):
        self.verify()
        return {"balances": self.request("GET", "/fapi/v3/balance"),
                "open_orders": {s: self.request("GET", "/fapi/v1/openOrders", {"symbol": s}) for s in SYMBOLS}}

    def test_order(self, symbol, side, quantity, price):
        self.verify()
        if symbol not in SYMBOLS or side not in {"BUY", "SELL"}:
            raise SafetyError("Unsupported symbol or side")
        item = next(s for s in self.exchange_info["symbols"] if s["symbol"] == symbol)
        filters = {f["filterType"]: f for f in item["filters"]}
        try:
            q, p = Decimal(quantity), Decimal(price)
            if not q.is_finite() or not p.is_finite() or q <= 0 or p <= 0:
                raise SafetyError("Quantity and price must be positive finite numbers")
            for value, kind, low, high, step in ((q, "LOT_SIZE", "minQty", "maxQty", "stepSize"),
                                                (p, "PRICE_FILTER", "minPrice", "maxPrice", "tickSize")):
                f = filters[kind]
                if not Decimal(f[low]) <= value <= Decimal(f[high]) or value % Decimal(f[step]):
                    raise SafetyError(f"Order violates {kind}")
            if q * p < Decimal(filters["MIN_NOTIONAL"]["notional"]):
                raise SafetyError("Order violates MIN_NOTIONAL")
        except (InvalidOperation, KeyError, ZeroDivisionError):
            raise SafetyError("Invalid order or unsupported exchange filters") from None
        return self.request("POST", "/fapi/v1/order/test", {
            "symbol": symbol, "side": side, "type": "LIMIT", "timeInForce": "GTC",
            "quantity": str(q), "price": str(p)})
