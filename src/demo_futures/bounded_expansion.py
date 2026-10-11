"""Resumable DATA ONLY controls; no account, model or execution configuration."""
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import ssl
import time
import urllib.error
import urllib.request
import uuid

from .public_history import (DEMO_ORIGIN, STEP, FUTURE_EXPANSION_SYMBOLS,
    PublicDemoHistory, PublicHistoryError, NoRedirect, public_url, _read_metadata_body)
from .future_expansion import candle_page, funding_page

START = 1776118800000  # 2026-04-13T22:20:00Z, inclusive
END = 1791670800000    # 2026-10-10T22:20:00Z, exclusive
METADATA_SHA = "2dbdb00f1f17eb627770200c928825e57be8388f3f0667767b2153bd634f2fd0"
MAX_REQUESTS = 700
WALL_SECONDS = 1200


def digest(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode()).hexdigest()


def save(path, value):
    """Publish a complete immutable checkpoint, never an incomplete final file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(path)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with temporary.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    # Windows rename refuses an existing destination; single-worker lock also required.
    temporary.rename(path)


def check_request(path, params):
    if path not in ("/fapi/v1/klines", "/fapi/v1/fundingRate"):
        raise ValueError("Only expansion candles and funding permitted")
    url = public_url(path, params, future_expansion=True)
    if not START <= params["startTime"] <= params["endTime"] < END:
        raise ValueError("Request outside frozen historical window")
    if path.endswith("klines") and (params["startTime"] % STEP or
            (params["endTime"] + 1) % STEP or params["limit"] > 499):
        raise ValueError("Aligned candle batches of at most 499 required")
    return url


class BodyAdapter:
    """Let the existing history client use its existing bounded body reader."""
    def __init__(self, response, receipt):
        self.response, self.receipt = response, receipt
        self.headers = response.headers
    def geturl(self): return self.response.geturl()
    def __enter__(self): return self
    def __exit__(self, *args): self.response.close()
    def read(self, size=-1):
        self.receipt["stage"] = "body_read"
        try:
            body = _read_metadata_body(self.response, self.receipt)
        except TimeoutError:
            raise PublicHistoryError(self.receipt["status"], "body_timeout", "body_read") from None
        except OSError:
            raise PublicHistoryError(self.receipt["status"], "body_read", "body_read") from None
        self.receipt.update(stage="json_decode", body_sha256=hashlib.sha256(body).hexdigest())
        return body


class ObservedOpener:
    def __init__(self, base=None):
        self.base = base or urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        self.receipt = {}
    def open(self, request, timeout):
        started = time.monotonic()
        self.receipt = {"status": 0, "stage": "response_open"}
        try:
            response = self.base.open(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            self.receipt["status"] = error.code
            error.close()
            raise PublicHistoryError(error.code, "http", "response_open") from None
        self.receipt.update(status=response.status, response_open_seconds=round(time.monotonic()-started, 6))
        if response.geturl() != request.full_url:
            response.close()
            raise PublicHistoryError(self.receipt["status"], "response_origin", "response_origin")
        sock = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
        if not isinstance(sock, ssl.SSLSocket) or sock.context.verify_mode != ssl.CERT_REQUIRED or not sock.context.check_hostname:
            response.close()
            raise PublicHistoryError(self.receipt["status"], "tls_verification", "response_open")
        self.receipt.update(tls_version=sock.version(), certificate_required=True, hostname_verified=True,
            response_headers={k.lower(): str(v) for k, v in response.headers.items()
                if k.lower() in ("content-length", "content-type", "retry-after") or k.lower().startswith("x-mbx-used-weight-")})
        return BodyAdapter(response, self.receipt)


class CheckpointClient:
    """Replay verified pages; bound every attempt including failures and retries."""
    def __init__(self, folder, client=None, clock=time.monotonic, sleeper=time.sleep,
                 max_requests=MAX_REQUESTS, seconds=WALL_SECONDS, weight_limit=2400):
        if not 1 <= max_requests <= MAX_REQUESTS or not 0 < seconds <= WALL_SECONDS:
            raise ValueError("Finite approved budgets required")
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.clock, self.sleeper = clock, sleeper
        self.deadline, self.max_requests = clock()+seconds, max_requests
        self.observed = ObservedOpener() if client is None else None
        self.client = client or PublicDemoHistory(self.observed, pause=0, future_expansion=True)
        self.weight_limit, self.weight = min(2400, weight_limit), 0
        self.calls = len(list(self.folder.glob("attempt-*-start.json")))
        self.cache_hits = 0

    def check_budget(self):
        if self.calls >= self.max_requests:
            raise PublicHistoryError(0, "local_request_budget", "before_request")
        if self.clock() >= self.deadline:
            raise PublicHistoryError(0, "local_wall_budget", "before_request")
        if self.weight >= self.weight_limit * .8:
            raise PublicHistoryError(0, "local_weight_stop", "before_request")

    def sleep(self, seconds):
        if self.clock()+seconds >= self.deadline:
            raise PublicHistoryError(0, "local_wall_budget", "before_request")
        self.sleeper(seconds)

    def get(self, path, params):
        check_request(path, params)
        key = digest({"path": path, "params": params})
        checkpoint = self.folder / ("page-"+key+".json")
        if checkpoint.exists():
            value = json.loads(checkpoint.read_text(encoding="utf-8"))
            if value["origin"] != DEMO_ORIGIN or value["path"] != path or value["params"] != params or digest(value["payload"]) != value["response_sha256"]:
                raise PublicHistoryError(0, "checkpoint_integrity", "local_cache")
            self.validate(path, params, value["payload"])
            self.cache_hits += 1
            return value["payload"]
        for retry in range(3):
            self.check_budget()
            self.sleep(.5 if retry == 0 else 2**retry)
            self.check_budget()
            self.calls += 1
            stem = self.folder / f"attempt-{self.calls:04d}"
            started = self.clock()
            save(Path(str(stem)+"-start.json"), {"origin": DEMO_ORIGIN, "path": path,
                "params": params, "retry_index": retry, "started_utc": datetime.now(timezone.utc).isoformat()})
            receipt = {}
            try:
                payload = self.client.get(path, params)
                receipt = dict(self.observed.receipt) if self.observed else dict(self.client.requests[-1])
                receipt.update(status=receipt.get("status", 200), stage="validation")
                self.validate(path, params, payload)
                receipt.update(stage="complete", elapsed_seconds=round(self.clock()-started, 6),
                    received_utc=datetime.now(timezone.utc).isoformat(), rows=len(payload))
                for k, v in receipt.get("response_headers", {}).items():
                    if k.lower().startswith("x-mbx-used-weight-") and str(v).isdigit():
                        self.weight = max(self.weight, int(v))
                save(checkpoint, {"origin": DEMO_ORIGIN, "path": path, "params": params,
                    "payload": payload, "response_sha256": digest(payload), "receipt": receipt})
                save(Path(str(stem)+"-result.json"), receipt)
                return payload
            except PublicHistoryError as error:
                receipt = dict(self.observed.receipt) if self.observed else receipt
                status = receipt.get("status", 0) or error.status
                receipt.update(status=status, failure_kind=error.kind, stage=error.stage or receipt.get("stage", "response_open"), elapsed_seconds=round(self.clock()-started, 6))
                save(Path(str(stem)+"-result.json"), receipt)
                # Only transport/timeouts are retried, never HTTP bans/redirects/schema failures.
                if error.kind not in ("network", "body_timeout", "body_read", "body_deadline") or retry == 2:
                    raise PublicHistoryError(status, error.kind, receipt["stage"]) from None
            except Exception as error:
                from .data import DataQualityError
                if not isinstance(error, (DataQualityError, ValueError, TypeError, KeyError, ArithmeticError)):
                    raise
                # Preserve rejected source payload separately; never accept or repair it.
                receipt = dict(self.observed.receipt) if self.observed else receipt
                receipt.update(failure_kind="quality", stage="validation", elapsed_seconds=round(self.clock()-started, 6))
                save(Path(str(stem)+"-result.json"), receipt)
                if "payload" in locals():
                    save(Path(str(stem)+"-rejected.json"), {"path": path, "params": params, "payload": payload, "response_sha256": digest(payload)})
                raise PublicHistoryError(receipt.get("status", 0), "quality", "validation") from None

    @staticmethod
    def validate(path, params, payload):
        if not isinstance(payload, list) or len(payload) > params["limit"]:
            raise ValueError("Invalid bounded page shape")
        if path.endswith("klines"):
            candle_page(payload, params["startTime"], params["endTime"]+1, END)
        else:
            funding_page(payload, params["symbol"], params["startTime"], params["endTime"]+1)
