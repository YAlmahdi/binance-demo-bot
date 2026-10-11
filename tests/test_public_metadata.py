"""Offline metadata-body transport checks; no Binance requests."""
import io
import http.client
import ssl
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

from demo_futures import public_history as h

URL = h.DEMO_ORIGIN + "/fapi/v1/exchangeInfo"
PAYLOAD = {"symbols": [], "rateLimits": []}


class Clock:
    def __init__(self): self.now = 0.0
    def __call__(self): return self.now


class Socket:
    def __init__(self): self.timeouts = []
    def settimeout(self, value): self.timeouts.append(value)


class Body:
    status = 200
    def __init__(self, data=None, *, clock=None, delays=(), error=None, length=True, url=URL):
        self.data = json.dumps(PAYLOAD).encode() if data is None else data
        self.clock, self.delays, self.error = clock, iter(delays), error
        self.socket = Socket()
        self.fp = SimpleNamespace(raw=SimpleNamespace(_sock=self.socket))
        self.headers = {"Content-Type": "application/json", "X-MBX-USED-WEIGHT-1M": "2"}
        if length: self.headers["Content-Length"] = str(len(self.data))
        self.offset, self.reads, self.url, self.closed = 0, [], url, False
    def geturl(self): return self.url
    def __enter__(self): return self
    def __exit__(self, *args): self.closed = True
    def read1(self, size):
        self.reads.append(size)
        delay = next(self.delays, 0)
        if self.clock:
            self.clock.now += min(delay, self.socket.timeouts[-1])
        if delay > self.socket.timeouts[-1]: raise TimeoutError("untrusted remote details")
        if self.error: raise self.error
        chunk = self.data[self.offset:self.offset + size]
        self.offset += len(chunk)
        return chunk
    def read(self, *args): raise AssertionError("Network metadata must use bounded read1")


class Opener:
    def __init__(self, body=None, error=None): self.body, self.error, self.calls = body, error, []
    def open(self, request, timeout):
        self.calls.append((request, timeout))
        if self.error: raise self.error
        return self.body


def client(body=None, error=None):
    opener = Opener(body, error)
    return h.PublicDemoHistory(opener, pause=0, sleeper=lambda _: None, future_expansion=True), opener


class MetadataTests(unittest.TestCase):
    def test_http_200_then_body_timeout_retains_status_and_stage(self):
        body = Body(error=TimeoutError("untrusted remote details"))
        c, opener = client(body)
        with self.assertRaises(h.PublicHistoryError) as caught: c.get("/fapi/v1/exchangeInfo")
        self.assertEqual((caught.exception.status, caught.exception.kind, caught.exception.stage), (200, "body_timeout", "body_read"))
        self.assertEqual(c.requests[0]["status"], 200)
        self.assertEqual(c.requests[0]["failure_stage"], "body_read")
        self.assertEqual(c.requests[0]["body_bytes_returned"], 0)
        self.assertNotIn("untrusted", str(caught.exception))
        self.assertEqual(len(opener.calls), 1)
        self.assertTrue(body.closed)

    def test_failure_before_headers_has_unknown_status(self):
        c, opener = client(error=urllib.error.URLError("remote details"))
        with self.assertRaises(h.PublicHistoryError) as caught: c.get("/fapi/v1/exchangeInfo")
        self.assertEqual((caught.exception.status, caught.exception.kind, caught.exception.stage), (0, "network", "response_open"))
        self.assertEqual(c.requests[0]["failure_stage"], "response_open")
        self.assertEqual(len(opener.calls), 1)

    def test_http_rejection_is_not_a_body_failure(self):
        error = urllib.error.HTTPError(URL, 429, "private remote text", {}, io.BytesIO())
        c, opener = client(error=error)
        with self.assertRaises(h.PublicHistoryError) as caught: c.get("/fapi/v1/exchangeInfo")
        self.assertEqual((caught.exception.status, caught.exception.kind, caught.exception.stage), (429, "http", "response_open"))
        self.assertEqual(len(opener.calls), 1)

    def test_complete_large_json_in_bounded_chunks(self):
        payload = dict(PAYLOAD, padding="x" * 902495)
        body = Body(json.dumps(payload).encode())
        c, opener = client(body)
        self.assertEqual(c.get("/fapi/v1/exchangeInfo"), payload)
        self.assertGreater(len(body.reads), 10)
        self.assertLessEqual(max(body.reads), h.METADATA_CHUNK_BYTES)
        self.assertEqual(c.requests[0]["body_bytes_returned"], len(body.data))
        self.assertEqual(c.requests[0]["status"], 200)
        self.assertEqual(c.requests[0]["used_weight_headers"], {"x-mbx-used-weight-1m": 2})
        self.assertEqual(opener.calls[0][1], 30)
        self.assertTrue(body.closed)

    def test_delayed_body_can_succeed_within_fixed_budget(self):
        clock = Clock()
        body = Body(clock=clock, delays=[40])
        c, _ = client(body)
        with patch.object(h.time, "monotonic", clock): self.assertEqual(c.get("/fapi/v1/exchangeInfo"), PAYLOAD)
        self.assertEqual(c.requests[0]["body_elapsed_seconds"], 40)
        self.assertEqual(body.socket.timeouts, [60])

    def test_remaining_deadline_limits_each_blocking_read(self):
        clock = Clock()
        body = Body(b" " * (4 * h.METADATA_CHUNK_BYTES), clock=clock, delays=[50, 50, 50])
        c, _ = client(body)
        with patch.object(h.time, "monotonic", clock), self.assertRaises(h.PublicHistoryError) as caught:
            c.get("/fapi/v1/exchangeInfo")
        self.assertEqual(caught.exception.kind, "body_timeout")
        self.assertEqual(body.socket.timeouts, [60, 60, 20])
        self.assertEqual(clock.now, 120)
        self.assertEqual(c.requests[0]["body_bytes_returned"], 2 * h.METADATA_CHUNK_BYTES)

    def test_data_arriving_at_deadline_is_rejected_before_decoding(self):
        clock = Clock()
        body = Body(b" " * (2 * h.METADATA_CHUNK_BYTES), clock=clock, delays=[60, 60])
        c, _ = client(body)
        with patch.object(h.time, "monotonic", clock), self.assertRaises(h.PublicHistoryError) as caught:
            c.get("/fapi/v1/exchangeInfo")
        self.assertEqual(caught.exception.kind, "body_deadline")
        self.assertEqual(clock.now, 120)
        self.assertEqual(len(body.reads), 2)

    def test_body_size_cap_with_and_without_length(self):
        for length in (False, True):
            body = Body(b"x" * (h.METADATA_MAX_BYTES + 1), length=length)
            c, _ = client(body)
            with self.assertRaises(h.PublicHistoryError) as caught: c.get("/fapi/v1/exchangeInfo")
            self.assertEqual(caught.exception.kind, "body_size")
            self.assertLessEqual(body.offset, h.METADATA_MAX_BYTES + 1)
            if length: self.assertEqual(body.reads, [])

    def test_incomplete_body_is_not_json_decode_failure(self):
        body = Body()
        body.headers["Content-Length"] = str(len(body.data) + 10)
        c, _ = client(body)
        with self.assertRaises(h.PublicHistoryError) as caught: c.get("/fapi/v1/exchangeInfo")
        self.assertEqual((caught.exception.status, caught.exception.kind, caught.exception.stage), (200, "body_incomplete", "body_read"))

    def test_invalid_json_retains_http_status(self):
        c, _ = client(Body(b"not json"))
        with self.assertRaises(h.PublicHistoryError) as caught: c.get("/fapi/v1/exchangeInfo")
        self.assertEqual((caught.exception.status, caught.exception.kind, caught.exception.stage), (200, "invalid_json", "json_decode"))

    def test_unknown_socket_layout_fails_closed(self):
        body = Body()
        body.fp = None
        c, _ = client(body)
        with self.assertRaises(h.PublicHistoryError) as caught: c.get("/fapi/v1/exchangeInfo")
        self.assertEqual(caught.exception.kind, "body_timeout_unsupported")
        self.assertEqual(body.reads, [])

    def test_unsigned_get_no_redirect_and_budget_unchanged(self):
        c, opener = client(Body())
        c.get("/fapi/v1/exchangeInfo")
        request, timeout = opener.calls[0]
        self.assertEqual(request.full_url, URL)
        self.assertEqual(request.get_method(), "GET")
        self.assertIsNone(request.data)
        self.assertEqual(set(k.lower() for k in request.headers), {"user-agent"})
        bad, _ = client(Body(url="https://untrusted.invalid/"))
        with self.assertRaises(h.PublicHistoryError): bad.get("/fapi/v1/exchangeInfo")
        budget, calls = client(Body())
        budget.requests = [{}] * 1200
        with self.assertRaises(h.PublicHistoryError): budget.get("/fapi/v1/exchangeInfo")
        self.assertEqual(calls.calls, [])

    def test_original_scopes_still_refuse_metadata_and_private_paths(self):
        for flag in (False, True):
            for path in ("/fapi/v1/order", "/fapi/v1/order/test", "/fapi/v3/balance", "https://fapi.binance.com/fapi/v1/exchangeInfo"):
                with self.assertRaises(ValueError): h.public_url(path, future_expansion=flag)
        with self.assertRaises(ValueError): h.public_url("/fapi/v1/exchangeInfo")
        with self.assertRaises(ValueError): h.public_url("/fapi/v1/exchangeInfo", {"signature": "dummy"}, future_expansion=True)
        self.assertEqual(h.SYMBOLS, ("BTCUSDT", "ETHUSDT"))

    def test_default_transport_keeps_proxy_and_tls_controls(self):
        c = h.PublicDemoHistory(future_expansion=True)
        proxy_handlers = [x for x in c.opener.handlers if isinstance(x, urllib.request.ProxyHandler)]
        self.assertTrue(all(x.proxies == {} for x in proxy_handlers))
        self.assertTrue(any(isinstance(x, h.NoRedirect) for x in c.opener.handlers))
        self.assertTrue(any(isinstance(x, urllib.request.HTTPSHandler) for x in c.opener.handlers))

    def test_cpython_http_response_chunking_and_final_close(self):
        # Real HTTPResponse parsing over a synthetic BufferedReader, no sockets.
        payload = dict(PAYLOAD, padding="x" * 902495)
        data = json.dumps(payload).encode()
        raw = io.BytesIO(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: " +
                         str(len(data)).encode() + b"\r\nConnection: close\r\n\r\n" + data)
        sock = Socket()
        raw._sock = sock
        sock.makefile = lambda mode: io.BufferedReader(raw)
        response = http.client.HTTPResponse(sock)
        response.begin()
        response.geturl = lambda: URL
        c, _ = client(response)
        self.assertEqual(c.get("/fapi/v1/exchangeInfo"), payload)
        self.assertEqual(c.requests[0]["status"], 200)
        self.assertEqual(c.requests[0]["body_bytes_returned"], len(data))
        self.assertIsNone(response.fp)
        self.assertGreater(len(sock.timeouts), 10)

    def test_default_https_connection_verifies_certificate_and_hostname(self):
        # HTTPSConnection construction does not resolve DNS or connect.
        connection = http.client.HTTPSConnection("demo-fapi.binance.com")
        self.assertEqual(connection._context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(connection._context.check_hostname)
        connection.close()

    def test_body_failure_is_not_automatically_retried(self):
        c, opener = client(Body(error=TimeoutError("remote")))
        retries = h.RetryingPublicHistory(c, sleeper=lambda _: self.fail("Unexpected retry"))
        with self.assertRaises(h.PublicHistoryError): retries.get("/fapi/v1/exchangeInfo")
        self.assertEqual(len(opener.calls), 1)


if __name__ == "__main__": unittest.main()
