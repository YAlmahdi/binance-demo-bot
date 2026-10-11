"""Synthetic-only tests for fixed-window, resumable collection controls."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
from demo_futures import bounded_expansion as b
from demo_futures.public_history import STEP, PublicHistoryError, SYMBOLS
from test_public_history import row
from test_public_metadata import Body, Clock


def params():
    return dict(symbol="SOLUSDT", interval="5m", startTime=b.START, endTime=b.START+STEP-1, limit=1)


class Fake:
    def __init__(self, values): self.values, self.requests = iter(values), []
    def get(self, path, values):
        self.requests.append({"status": 200})
        value = next(self.values)
        if isinstance(value, Exception): raise value
        return value


class ControlsTests(unittest.TestCase):
    def test_dates_exactly_match_approved_180_days(self):
        from datetime import datetime, timezone
        self.assertEqual(datetime.fromtimestamp(b.START/1000, timezone.utc).isoformat(), "2026-04-13T22:20:00+00:00")
        self.assertEqual(datetime.fromtimestamp(b.END/1000, timezone.utc).isoformat(), "2026-10-10T22:20:00+00:00")
        self.assertEqual((b.END-b.START)//STEP, 51840)

    def test_unapproved_paths_symbols_and_ranges_blocked(self):
        for path in ("/fapi/v1/time", "/fapi/v1/exchangeInfo", "/fapi/v1/order", "/fapi/v1/order/test", "/fapi/v3/balance", "https://fapi.binance.com/fapi/v1/klines"):
            with self.assertRaises(ValueError): b.check_request(path, params())
        for change in ({"symbol":"BTCUSDT"},{"symbol":"DOGEUSDT"},{"interval":"1h"},{"limit":500},{"startTime":b.START-STEP},{"endTime":b.END},{"signature":"dummy"},{"startTime":b.START+1}):
            with self.assertRaises(ValueError): b.check_request("/fapi/v1/klines", dict(params(), **change))
        self.assertEqual(SYMBOLS, ("BTCUSDT", "ETHUSDT"))

    def test_checkpoint_replays_without_new_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake=Fake([[row(b.START)]])
            first=b.CheckpointClient(tmp, fake, sleeper=lambda _:None)
            expected=first.get("/fapi/v1/klines", params())
            resumed=b.CheckpointClient(tmp, Fake([]), sleeper=lambda _:None)
            self.assertEqual(resumed.get("/fapi/v1/klines", params()), expected)
            self.assertEqual(resumed.calls, 1)
            self.assertEqual(resumed.cache_hits, 1)
            self.assertEqual(len(list(Path(tmp).glob("page-*.json"))), 1)

    def test_corrupted_checkpoint_fails_before_transport(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=b.CheckpointClient(tmp, Fake([[row(b.START)]]), sleeper=lambda _:None)
            c.get("/fapi/v1/klines", params())
            file=next(Path(tmp).glob("page-*.json")); data=json.loads(file.read_text())
            data["origin"]="https://fapi.binance.com"; file.write_text(json.dumps(data))
            with self.assertRaises(PublicHistoryError): c.get("/fapi/v1/klines", params())
            self.assertEqual(c.calls, 1)

    def test_recoverable_failures_have_at_most_three_attempts(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=b.CheckpointClient(tmp, Fake([PublicHistoryError(200,"body_timeout","body_read")]*3), sleeper=lambda _:None)
            with self.assertRaises(PublicHistoryError): c.get("/fapi/v1/klines", params())
            self.assertEqual(c.calls, 3)
            results=[json.loads(p.read_text()) for p in Path(tmp).glob("*-result.json")]
            self.assertTrue(all(r["status"]==200 and r["stage"]=="body_read" for r in results))

    def test_http_bans_redirects_and_invalid_json_not_retried(self):
        for error in (PublicHistoryError(429),PublicHistoryError(418),PublicHistoryError(302),PublicHistoryError(500),PublicHistoryError(200,"invalid_json")):
            with tempfile.TemporaryDirectory() as tmp:
                c=b.CheckpointClient(tmp,Fake([error]),sleeper=lambda _:None)
                with self.assertRaises(PublicHistoryError): c.get("/fapi/v1/klines",params())
                self.assertEqual(c.calls,1)

    def test_attempt_budget_counts_failures_across_continuation(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=b.CheckpointClient(tmp,Fake([PublicHistoryError(0,"network")]),max_requests=1,sleeper=lambda _:None)
            with self.assertRaises(PublicHistoryError): c.get("/fapi/v1/klines",params())
            resumed=b.CheckpointClient(tmp,Fake([]),max_requests=1,sleeper=lambda _:None)
            with self.assertRaises(PublicHistoryError) as got: resumed.get("/fapi/v1/klines",params())
            self.assertEqual(got.exception.kind,"local_request_budget")

    def test_expired_wall_budget_stops_before_transport(self):
        with tempfile.TemporaryDirectory() as tmp:
            clock=Clock(); c=b.CheckpointClient(tmp,Fake([]),clock=clock,seconds=1,sleeper=lambda _:None)
            clock.now=2
            with self.assertRaises(PublicHistoryError) as got: c.get("/fapi/v1/klines",params())
            self.assertEqual(got.exception.kind,"local_wall_budget")
            self.assertEqual(c.calls,0)

    def test_weight_stop_precedes_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=b.CheckpointClient(tmp,Fake([])); c.weight=1920
            with self.assertRaises(PublicHistoryError): c.get("/fapi/v1/klines",params())
            self.assertEqual(c.calls,0)

    def test_invalid_and_duplicate_rows_quarantined_not_checkpointed(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=dict(params(),endTime=b.START+2*STEP-1,limit=2)
            c=b.CheckpointClient(tmp,Fake([[row(b.START),row(b.START)]]),sleeper=lambda _:None)
            with self.assertRaises(PublicHistoryError): c.get("/fapi/v1/klines",p)
            self.assertFalse(list(Path(tmp).glob("page-*.json")))
            self.assertEqual(len(list(Path(tmp).glob("*-rejected.json"))),1)

    def test_missing_rows_and_negative_funding_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=b.CheckpointClient(tmp,Fake([[],[dict(symbol="SOLUSDT",fundingTime=b.START+1,fundingRate="-.001",markPrice="100")]]),sleeper=lambda _:None)
            self.assertEqual(c.get("/fapi/v1/klines",params()),[])
            p=params(); del p["interval"]
            self.assertEqual(c.get("/fapi/v1/fundingRate",p)[0]["fundingRate"],"-.001")

    def test_atomic_checkpoint_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/"x.json"; b.save(file,{"first":True}); old=file.read_bytes()
            with self.assertRaises(FileExistsError): b.save(file,{"second":True})
            self.assertEqual(file.read_bytes(),old)

    def test_http200_body_timeout_preserves_status(self):
        response=Body(error=TimeoutError("private detail")); receipt={"status":200}
        with self.assertRaises(PublicHistoryError) as got: b.BodyAdapter(response,receipt).read()
        self.assertEqual((got.exception.status,got.exception.kind,got.exception.stage),(200,"body_timeout","body_read"))
        self.assertNotIn("private detail",str(got.exception))

    def test_large_complete_body_and_delayed_read_use_existing_bounds(self):
        clock=Clock(); data=b'['+b' '*900000+b']'; response=Body(data,clock=clock,delays=(40,))
        receipt={"status":200}
        with patch("demo_futures.public_history.time.monotonic",clock):
            self.assertEqual(b.BodyAdapter(response,receipt).read(),data)
        self.assertLessEqual(max(response.reads),65536)
        self.assertLessEqual(max(response.socket.timeouts),60)
        self.assertEqual(receipt["stage"],"json_decode")

    def test_guard_blocks_old_data_credentials_and_non_demo_requests(self):
        import importlib.util
        file=Path(__file__).resolve().parents[1]/"scripts/collect_bounded_expansion.py"
        spec=importlib.util.spec_from_file_location("bounded_runner",file); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        guard=mod.guard_for(mod.ROOT/"artifacts/future-expansion/new",mod.ROOT/"reports/future-expansion/new")
        for path in (mod.ROOT/".env",mod.ROOT/"data/market.sqlite3",mod.ROOT/"artifacts/ml-research/locked/labels.csv"):
            with self.assertRaises(RuntimeError): guard("open",(str(path),"r",0))
        for name in ("demo_futures.client","demo_futures.config","demo_futures.ml_research.model"):
            with self.assertRaises(RuntimeError): guard("import",(name,))
        good=b.check_request("/fapi/v1/klines",params())
        guard("urllib.Request",(good,None,{"User-agent":"test"},"GET"))
        for url,data,headers,method in ((good,None,{},"POST"),(good,b'x',{},"GET"),(good,None,{"X-MBX-APIKEY":"dummy"},"GET"),(good.replace("demo-fapi","fapi"),None,{},"GET")):
            with self.assertRaises(RuntimeError): guard("urllib.Request",(url,data,headers,method))

    def test_external_watchdog_kills_stalled_worker_and_records_partial_stop(self):
        import importlib.util, subprocess
        file=Path(__file__).resolve().parents[1]/"scripts/collect_bounded_expansion.py"
        spec=importlib.util.spec_from_file_location("bounded_watchdog",file); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); art=root/"artifacts/future-expansion/FUTURE-EXPANSION-DATA-ONLY-test"; art.mkdir(parents=True)
            report=root/"reports/future-expansion"/art.name; report.mkdir(parents=True)
            child=Mock(); child.wait.side_effect=[subprocess.TimeoutExpired("mock-worker",b.WALL_SECONDS),0]; child.poll.return_value=0
            with patch.object(mod,"ROOT",root), patch.object(mod.sys,"argv",[str(file),"--collect","--snapshot",str(art)]), patch.object(mod.subprocess,"Popen",return_value=child):
                self.assertEqual(mod.main(),2)
            child.kill.assert_called_once()
            self.assertEqual(child.wait.call_args_list[0].kwargs["timeout"],1200)
            evidence=json.loads(next(report.glob("run-*.json")).read_text())
            self.assertTrue(evidence["watchdog_timeout"])
            self.assertFalse((art/"worker.lock").exists())

    def test_pagination_resumes_verified_batches_and_keeps_empty_funding(self):
        from demo_futures.future_expansion import collect
        end=b.START+500*STEP
        with tempfile.TemporaryDirectory() as tmp:
            first=b.CheckpointClient(tmp,Fake([[row(b.START)],PublicHistoryError(429)]),sleeper=lambda _:None)
            partial=collect(first,"SOLUSDT",b.START,end,b.END)
            self.assertEqual(partial[4],b.START+499*STEP)
            resumed=b.CheckpointClient(tmp,Fake([[row(end-STEP)],[]]),sleeper=lambda _:None)
            full=collect(resumed,"SOLUSDT",b.START,end,b.END)
            self.assertEqual(len(full[0]),2)  # Gaps preserved, never filled.
            self.assertEqual(full[1],[])
            self.assertEqual(full[4:6],(end,end))
            self.assertEqual(resumed.cache_hits,1)
