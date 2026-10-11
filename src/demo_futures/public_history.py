"""Credential-free public Demo history client. No Settings or authenticated client imports."""
import hashlib
import io
import json
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request

from .data import Candle, DataQualityError, validate_candles

DEMO_ORIGIN = "https://demo-fapi.binance.com"
SYMBOLS = ("BTCUSDT", "ETHUSDT")
FUTURE_EXPANSION_SYMBOLS = ("SOLUSDT", "BNBUSDT", "XRPUSDT")
STEP = 300_000
DAY = 86_400_000

# Only the large, public exchangeInfo body gets this policy. Opening still uses 30s.
METADATA_IDLE_SECONDS = 60
METADATA_BODY_SECONDS = 120
METADATA_MAX_BYTES = 4 * 1024 * 1024
METADATA_CHUNK_BYTES = 64 * 1024


class PublicHistoryError(RuntimeError):
    def __init__(self, status=0, kind="http", stage=None):
        self.status, self.kind, self.stage = status, kind, stage
        super().__init__(f"Public Demo history request failed (HTTP {status}); stopped without fallback")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *arguments, **kwargs):
        raise PublicHistoryError(302)


def public_url(path, params=None, *, future_expansion=False):
    """Fixed public GET scope; expansion opt-in does not change active symbols."""
    if type(future_expansion) is not bool:
        raise ValueError("Expansion scope must be explicit boolean")
    permitted_symbols = FUTURE_EXPANSION_SYMBOLS if future_expansion else SYMBOLS
    values = dict(params or {})
    if path == "/fapi/v1/time" or (future_expansion and path == "/fapi/v1/exchangeInfo"):
        if values:
            raise ValueError("Time endpoint takes no research parameters")
    elif path in ("/fapi/v1/klines", "/fapi/v1/fundingRate"):
        allowed = {"symbol", "startTime", "endTime", "limit"}
        if path.endswith("klines"):
            allowed.add("interval")
        if set(values) != allowed or values["symbol"] not in permitted_symbols:
            raise ValueError("Unsupported public history parameters")
        if "interval" in allowed and values["interval"] != "5m":
            raise ValueError("Research collection accepts 5m only")
        if any(type(values[key]) is not int for key in ("startTime", "endTime", "limit")):
            raise ValueError("Timestamp/limit parameters must be integers")
        if not 0 <= values["startTime"] <= values["endTime"] or not 1 <= values["limit"] <= 1000:
            raise ValueError("Invalid public history range or page size")
    else:
        raise ValueError("Endpoint is not permitted for public historical research")
    return DEMO_ORIGIN + path + ("?" + urllib.parse.urlencode(values) if values else "")


def _read_metadata_body(response, receipt):
    """Bound memory and blocking reads; never use read-all on a network response.

    CPython urllib exposes its TLS socket through HTTPResponse.fp.raw._sock.
    Fail closed if that layout changes rather than silently losing the deadline.
    In-memory StringIO/BytesIO are allowed for existing offline transport fixtures.
    """
    started = time.monotonic()
    deadline = started + METADATA_BODY_SECONDS
    receipt["body_bytes_returned"] = 0
    receipt["body_read_calls"] = 0
    try:
        value = getattr(response, "headers", {}).get("Content-Length")
        length = None
        if value is not None:
            if not str(value).isdigit():
                raise PublicHistoryError(receipt["status"], "invalid_content_length", "body_read")
            length = int(value)
            if length > METADATA_MAX_BYTES:
                raise PublicHistoryError(receipt["status"], "body_size", "body_read")
        memory = isinstance(response, (io.BytesIO, io.StringIO))
        sock = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
        if not memory and (sock is None or not callable(getattr(sock, "settimeout", None)) or
                           not callable(getattr(response, "read1", None))):
            raise PublicHistoryError(receipt["status"], "body_timeout_unsupported", "body_read")
        chunks = []
        while length is None or receipt["body_bytes_returned"] < length:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise PublicHistoryError(receipt["status"], "body_deadline", "body_read")
            if not memory:
                sock.settimeout(min(METADATA_IDLE_SECONDS, remaining))
            size = min(METADATA_CHUNK_BYTES, METADATA_MAX_BYTES - receipt["body_bytes_returned"] + 1)
            receipt["body_read_calls"] += 1
            chunk = response.read(size) if memory else response.read1(size)
            receipt["body_bytes_returned"] += len(chunk.encode("utf-8")) if isinstance(chunk, str) else len(chunk)
            if receipt["body_bytes_returned"] > METADATA_MAX_BYTES:
                raise PublicHistoryError(receipt["status"], "body_size", "body_read")
            if time.monotonic() >= deadline:
                raise PublicHistoryError(receipt["status"], "body_deadline", "body_read")
            if not chunk:
                break
            chunks.append(chunk)
        if length is not None and receipt["body_bytes_returned"] != length:
            raise PublicHistoryError(receipt["status"], "body_incomplete", "body_read")
        if not chunks:
            return b""
        return ("" if isinstance(chunks[0], str) else b"").join(chunks)
    finally:
        receipt["body_elapsed_seconds"] = round(time.monotonic() - started, 6)


class PublicDemoHistory:
    def __init__(self, opener=None, pause=0.2, sleeper=time.sleep, *, future_expansion=False):
        if type(future_expansion) is not bool:
            raise ValueError("Expansion scope must be explicit boolean")
        self.future_expansion = future_expansion
        self.opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        self.pause, self.sleeper = pause, sleeper
        self.requests = []

    def get(self, path, params=None):
        if self.future_expansion and len(self.requests) >= 1200:
            raise PublicHistoryError(0, "request_budget")
        url = public_url(path, params, future_expansion=self.future_expansion)
        request = urllib.request.Request(url, method="GET", headers={"User-Agent": "Futures-AI-Lab-public-history/0.2"})
        metadata = self.future_expansion and path == "/fapi/v1/exchangeInfo"
        receipt = {"method": "GET", "origin": DEMO_ORIGIN, "path": path,
                   "params": dict(params or {}), "status": 0}
        started, stage = time.monotonic(), "response_open"

        def record_failure(status, kind, failure_stage):
            if metadata:
                receipt.update(status=status, failure_kind=kind, failure_stage=failure_stage,
                               elapsed_seconds=round(time.monotonic() - started, 6))
                self.requests.append(receipt)
            else:
                self.requests.append({"method": "GET", "origin": DEMO_ORIGIN, "path": path,
                                      "params": dict(params or {}), "status": status, "failure_kind": kind})

        try:
            with self.opener.open(request, timeout=30) as response:
                if metadata:
                    status = getattr(response, "status", None)
                    if status is None and callable(getattr(response, "getcode", None)):
                        status = response.getcode()
                    receipt["status"] = status if type(status) is int else 0
                    receipt["response_open_seconds"] = round(time.monotonic() - started, 6)
                    headers = getattr(response, "headers", {})
                    receipt["response_headers"] = {key.lower(): headers[key] for key in
                        ("Content-Type", "Content-Length", "Content-Encoding", "Connection") if key in headers}
                if response.geturl() != url:
                    raise PublicHistoryError(302, stage="response_origin")
                if metadata:
                    stage = "body_read"
                    body = _read_metadata_body(response, receipt)
                    stage = "json_decode"
                    payload = json.loads(body)
                else:
                    payload = json.load(response)
                rate_headers = {k.lower(): int(v) for k, v in getattr(response, "headers", {}).items()
                                if k.lower().startswith("x-mbx-used-weight-") and str(v).isdigit()}
        except PublicHistoryError as error:
            record_failure(error.status, error.kind, error.stage or stage)
            raise
        except urllib.error.HTTPError as error:
            record_failure(error.code, "http", stage)
            raise PublicHistoryError(error.code, stage=stage if metadata else None) from None
        except (urllib.error.URLError, OSError) as error:
            status = receipt["status"] if metadata else 0
            kind = ("body_timeout" if isinstance(error, TimeoutError) else "body_read") if metadata and stage == "body_read" else "network"
            record_failure(status, kind, stage)
            raise PublicHistoryError(status, kind, stage if metadata else None) from None
        except ValueError:
            if metadata:
                record_failure(receipt["status"], "invalid_json", stage)
            raise PublicHistoryError(receipt["status"] if metadata else 0, "invalid_json",
                                     stage if metadata else None) from None
        if path == "/fapi/v1/time":
            if not isinstance(payload, dict) or type(payload.get("serverTime")) is not int or payload["serverTime"] <= 0:
                raise DataQualityError("Invalid public Demo server time")
        elif self.future_expansion and path == "/fapi/v1/exchangeInfo":
            if not isinstance(payload, dict) or not isinstance(payload.get("symbols"), list) or not isinstance(payload.get("rateLimits"), list):
                raise DataQualityError("Invalid public Demo exchange metadata")
        elif not isinstance(payload, list) or len(payload) > params["limit"]:
            raise DataQualityError("Invalid public Demo historical response")
        self.requests.append({
            "method": "GET", "origin": DEMO_ORIGIN, "path": path, "params": dict(params or {}),
            "received_at_ms": int(time.time() * 1000),
            "response_sha256": hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
            "rows": len(payload) if isinstance(payload, list) else None,
        })
        if self.future_expansion:
            self.requests[-1]["used_weight_headers"] = rate_headers
        if metadata:
            receipt.update(elapsed_seconds=round(time.monotonic() - started, 6))
            self.requests[-1].update(receipt)
        self.sleeper(self.pause)
        return payload


class RetryingPublicHistory:
    """At most three public GET attempts; bans/rate limits/redirects are never retried."""
    def __init__(self, client, sleeper=time.sleep):
        self.client, self.sleeper = client, sleeper
        self.requests = client.requests

    def get(self, path, params=None):
        for attempt in range(3):
            try:
                return self.client.get(path, params)
            except PublicHistoryError as error:
                retryable = error.kind == "network" or error.status in (500,502,503,504)
                if not retryable or attempt == 2:
                    raise
                self.sleeper(1 << attempt)


def collect_candles(client, symbol, start, end, server_time, progress=None, cache_dir=None):
    """All-or-fail exact contiguous range, [start,end); never fabricates missing bars."""
    if symbol not in SYMBOLS or start < 0 or start % STEP or end % STEP or start >= end:
        raise DataQualityError("Invalid historical collection range")
    if end > server_time // STEP * STEP or end - start > 90 * DAY:
        raise DataQualityError("Only completed candles and at most 90 days are permitted")
    cursor, candles = start, []
    while cursor < end:
        count = min(1000, (end - cursor) // STEP)
        # Bound every page exactly: protects against latest-data truncation semantics.
        page_end = cursor + count * STEP
        params = {"symbol": symbol, "interval": "5m", "startTime": cursor, "endTime": page_end - 1, "limit": count}
        cache = Path(cache_dir)/f"{symbol}-{cursor}-{page_end}.json" if cache_dir else None
        cached = cache is not None and cache.is_file()
        if cached:
            stored = json.loads(cache.read_text(encoding="utf-8"))
            if stored.get("origin") != DEMO_ORIGIN or stored.get("params") != params:
                raise DataQualityError("Historical checkpoint does not match the requested Demo page")
            rows = stored["rows"]
        else:
            rows = client.get("/fapi/v1/klines", params)
        page = validate_candles([Candle.from_binance(row) for row in rows], "5m", server_time)
        if len(page) != count or not page or page[0].open_time != cursor or page[-1].open_time != page_end - STEP:
            raise DataQualityError("Demo cannot supply the complete requested historical page; stopped")
        if cache is not None:
            if cached:
                client.requests.append({"method":"GET","origin":DEMO_ORIGIN,"path":"/fapi/v1/klines",
                                        "params":params,"rows":len(rows),"validated_local_cache":str(cache),
                                        "response_sha256":hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()})
            else:
                cache.parent.mkdir(parents=True,exist_ok=True)
                temporary = cache.with_suffix(".tmp")
                temporary.write_text(json.dumps({"origin":DEMO_ORIGIN,"params":params,"rows":rows}),encoding="utf-8")
                temporary.replace(cache)
        candles.extend(page)
        cursor = page_end
        if progress:
            progress(symbol, len(candles), (end - start) // STEP)
    return validate_candles(candles, "5m", server_time)


def collect_funding(client, symbol, start, end):
    if symbol not in SYMBOLS or not 0 <= start < end or end - start > 90 * DAY:
        raise DataQualityError("Invalid historical funding range")
    records, cursor = [], start
    while cursor < end:
        rows = client.get("/fapi/v1/fundingRate", {"symbol": symbol, "startTime": cursor,
                                                "endTime": end - 1, "limit": 1000})
        if not rows:
            break
        try:
            times = [row["fundingTime"] for row in rows]
            if any(type(t) is not int for t in times) or times != sorted(set(times)):
                raise ValueError()
            if times[0] < cursor or times[-1] >= end or any(row.get("symbol") != symbol for row in rows):
                raise ValueError()
            from .backtest import FundingEvent
            for row in rows:
                mark = row.get("markPrice")
                FundingEvent(row["fundingTime"], row["fundingRate"], None if mark in (None, "") else mark)
        except (KeyError, TypeError, ValueError, ArithmeticError):
            raise DataQualityError("Invalid historical funding response") from None
        records.extend(rows)
        cursor = times[-1] + 1
        # Continue even after a short page to verify exhaustion rather than silently truncate.
    return records
