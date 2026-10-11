import io
import json
import sqlite3
import tempfile
import unittest
import urllib.error
from pathlib import Path

from demo_futures.data import Candle, DataQualityError, SQLiteStore
from demo_futures.history_audit import audit_candles, audit_database, funding_audit
from demo_futures.public_history import PublicDemoHistory, PublicHistoryError, NoRedirect, RetryingPublicHistory, public_url, collect_candles, collect_funding


def row(timestamp):
    return [timestamp,"100","101","99","100","10",timestamp+299999,"1000",10,"0","0","0"]


class Fake:
    def __init__(self, payloads):
        self.payloads = iter(payloads)
        self.calls = []
        self.requests = []
    def get(self, path, params):
        self.calls.append((path,params))
        return next(self.payloads)


class Response(io.StringIO):
    def __init__(self, payload, url):
        super().__init__(json.dumps(payload))
        self.url = url
    def geturl(self):
        return self.url


class Opener:
    def __init__(self, payload=None, error=None, redirect=False):
        self.payload, self.error, self.redirect = payload, error, redirect
        self.calls = []
    def open(self, request, timeout):
        self.calls.append(request)
        if self.error:
            raise self.error
        url = "https://untrusted.invalid/" if self.redirect else request.full_url
        return Response(self.payload, url)


class PublicHistoryTests(unittest.TestCase):
    def test_origin_paths_and_unsigned_parameter_allowlist(self):
        params = {"symbol":"BTCUSDT","interval":"5m","startTime":0,"endTime":299999,"limit":1}
        self.assertTrue(public_url("/fapi/v1/klines",params).startswith("https://demo-fapi.binance.com/"))
        for path in ("/fapi/v1/order","/fapi/v1/order/test","/fapi/v3/balance","https://fapi.binance.com/fapi/v1/klines"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                public_url(path,params)
        for changes in ({"signature":"forbidden"},{"timestamp":123},{"symbol":"BNBUSDT"},{"interval":"1h"},{"limit":1001},{"startTime":True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                public_url("/fapi/v1/klines",dict(params,**changes))
        with self.assertRaises(ValueError):
            public_url("/fapi/v1/time",{"symbol":"BTCUSDT"})

    def test_transport_get_only_has_no_auth_headers_or_body(self):
        opener = Opener({"serverTime":300001})
        client = PublicDemoHistory(opener,pause=0,sleeper=lambda _:None)
        self.assertEqual(client.get("/fapi/v1/time"),{"serverTime":300001})
        request = opener.calls[0]
        self.assertEqual(request.get_method(),"GET")
        self.assertIsNone(request.data)
        self.assertFalse(any(k.lower() in ("x-mbx-apikey","authorization") for k in request.headers))
        self.assertEqual(len(client.requests),1)
        self.assertEqual(len(client.requests[0]["response_sha256"]),64)

    def test_redirects_fail_closed(self):
        with self.assertRaises(PublicHistoryError):
            NoRedirect().redirect_request(None,None,302,"",{},"https://fapi.binance.com")
        client = PublicDemoHistory(Opener({"serverTime":1},redirect=True),pause=0,sleeper=lambda _:None)
        with self.assertRaises(PublicHistoryError):
            client.get("/fapi/v1/time")

    def test_rate_limit_or_ban_stops_without_retry_or_response_body(self):
        for code in (429,418,503):
            opener = Opener(error=urllib.error.HTTPError("public-url",code,"Remote body must not be exposed",{},None))
            client = PublicDemoHistory(opener,pause=0,sleeper=lambda _:None)
            with self.assertRaises(PublicHistoryError) as caught:
                client.get("/fapi/v1/time")
            self.assertEqual(len(opener.calls),1)
            self.assertEqual(caught.exception.status,code)
            self.assertNotIn("Remote body",str(caught.exception))

    def test_invalid_server_or_historical_response_rejected(self):
        for payload in ({"serverTime":True},{"serverTime":0},[]):
            with self.assertRaises(DataQualityError):
                PublicDemoHistory(Opener(payload),pause=0,sleeper=lambda _:None).get("/fapi/v1/time")
        with self.assertRaises(DataQualityError):
            PublicDemoHistory(Opener({"code":-1}),pause=0,sleeper=lambda _:None).get("/fapi/v1/fundingRate",
                {"symbol":"BTCUSDT","startTime":0,"endTime":1,"limit":1})

    def test_exact_page_pagination_and_completed_exclusive_end(self):
        fake = Fake([[row(i*300000) for i in range(1000)],[row(300000000)]])
        result = collect_candles(fake,"BTCUSDT",0,300300000,300300001)
        self.assertEqual(len(result),1001)
        self.assertEqual(fake.calls[0][1]["endTime"],299999999)
        self.assertEqual(fake.calls[1][1]["startTime"],300000000)
        self.assertEqual(fake.calls[1][1]["limit"],1)
        self.assertEqual(result[-1].close_time,300299999)

    def test_empty_short_shifted_or_gapped_pages_fail_without_fabrication(self):
        for rows in ([],[row(0)],[row(300000),row(600000)],[row(0),row(600000)]):
            with self.subTest(rows=len(rows)), self.assertRaises(DataQualityError):
                collect_candles(Fake([rows]),"ETHUSDT",0,600000,600001)

    def test_open_candles_unaligned_and_over_90_day_ranges_rejected(self):
        for start,end,now in ((0,600000,599999),(1,600000,700000),(0,91*86400000,92*86400000)):
            with self.assertRaises(DataQualityError):
                collect_candles(Fake([]),"BTCUSDT",start,end,now)

    def test_funding_paginates_even_after_short_page_and_verifies_exhaustion(self):
        rows=[{"symbol":"BTCUSDT","fundingTime":10,"fundingRate":".001","markPrice":"100"}]
        fake=Fake([rows,[]])
        self.assertEqual(collect_funding(fake,"BTCUSDT",0,100),rows)
        self.assertEqual(fake.calls[1][1]["startTime"],11)

    def test_funding_wrong_symbol_duplicate_or_invalid_data_rejected(self):
        base={"symbol":"BTCUSDT","fundingTime":10,"fundingRate":".001","markPrice":"100"}
        for rows in ([base,base],[dict(base,symbol="ETHUSDT")],[dict(base,fundingTime=100)],
                     [dict(base,fundingRate="NaN")],[dict(base,markPrice="-1")]):
            with self.subTest(rows=rows), self.assertRaises(DataQualityError):
                collect_funding(Fake([rows]),"BTCUSDT",0,100)

    def test_empty_funding_is_not_silently_invented(self):
        self.assertEqual(collect_funding(Fake([[]]),"ETHUSDT",0,100),[])


class HistoricalAuditTests(unittest.TestCase):
    def test_reports_exact_coverage_missing_intervals_and_outliers(self):
        bars=[Candle(i*300000,100,106,99,100,0,i*300000+299999,0,0) for i in (0,2)]
        result=audit_candles(bars,"5m")
        self.assertEqual(result["missing_intervals"],1)
        self.assertEqual(result["expected_rows_in_span"],3)
        self.assertFalse(result["quality_passed"])
        self.assertTrue(result["values_and_timestamps_passed"])
        self.assertEqual(result["zero_volume_bars"],2)
        self.assertEqual(result["bars_with_range_over_5pct"],2)

    def test_invalid_ohlc_is_a_quality_failure_not_an_accepted_segment(self):
        result=audit_candles([Candle(0,100,99,98,100,1,299999,100,1)],"5m")
        self.assertFalse(result["values_and_timestamps_passed"])

    def test_modal_funding_schedule_missing_timestamp_is_explicitly_assumed(self):
        result=funding_audit([(0,.001,100),(10,.001,100),(20,.001,100),(40,.001,None)],0,50)
        self.assertEqual(result["modal_spacing_ms"],10)
        self.assertEqual(len(result["absent_under_modal_schedule_utc"]),1)
        self.assertEqual(result["missing_mark_prices"],1)
        self.assertIn("not independently verified",result["schedule_warning"])

    def test_database_audit_is_read_only_and_distinguishes_absent_intervals(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"history.sqlite3"
            store=SQLiteStore(path)
            store.upsert_candles("BTCUSDT","5m",[Candle(0,100,101,99,100,1,299999,100,1)])
            before=path.read_bytes()
            result=audit_database(path)
            self.assertEqual(before,path.read_bytes())
            self.assertEqual(result["integrity"],"ok")
            self.assertTrue(result["candles"]["BTCUSDT:5m"]["quality_passed"])
            self.assertEqual(result["candles"]["ETHUSDT:5m"]["status"],"absent")

class RecoveryTests(unittest.TestCase):
    def test_only_transient_public_failures_are_retried_at_most_three_times(self):
        class Unstable:
            requests=[]
            def __init__(self,status,kind="http"):
                self.calls=0;self.status=status;self.kind=kind
            def get(self,path,params=None):
                self.calls+=1
                raise PublicHistoryError(self.status,self.kind)
        for status,kind,expected in ((0,"network",3),(503,"http",3),(429,"http",1),
                                     (418,"http",1),(302,"http",1),(0,"invalid_json",1)):
            with self.subTest(status=status,kind=kind):
                base=Unstable(status,kind)
                wrapped=RetryingPublicHistory(base,sleeper=lambda _:None)
                with self.assertRaises(PublicHistoryError):
                    wrapped.get("/fapi/v1/time")
                self.assertEqual(base.calls,expected)

    def test_validated_cache_resumes_without_network_and_rejects_wrong_origin(self):
        with tempfile.TemporaryDirectory() as temp:
            first=Fake([[row(0),row(300000)]])
            bars=collect_candles(first,"BTCUSDT",0,600000,600001,cache_dir=temp)
            resumed=Fake([])
            self.assertEqual(collect_candles(resumed,"BTCUSDT",0,600000,600001,cache_dir=temp),bars)
            self.assertEqual(resumed.calls,[])
            cached=next(Path(temp).glob("*.json"))
            payload=json.loads(cached.read_text())
            payload["origin"]="https://fapi.binance.com"
            cached.write_text(json.dumps(payload))
            with self.assertRaises(DataQualityError):
                collect_candles(Fake([]),"BTCUSDT",0,600000,600001,cache_dir=temp)

    def test_invalid_pages_are_never_checkpointed(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(DataQualityError):
                collect_candles(Fake([[row(0)]]),"BTCUSDT",0,600000,600001,cache_dir=temp)
            self.assertEqual(list(Path(temp).iterdir()),[])

class FundingTimingDiagnosticsTests(unittest.TestCase):
    def test_one_millisecond_jitter_is_not_misreported_as_a_missing_settlement(self):
        rows=[(0,.001,100),(10,.001,100),(21,.001,100),(40,.001,100),(50,.001,100)]
        result=funding_audit(rows,0,60)
        self.assertEqual(result["modal_spacing_ms"],10)
        self.assertEqual(len(result["absent_under_modal_schedule_utc"]),1)
        self.assertEqual(result["near_schedule_shifted_events"][0]["offset_ms"],1)
        self.assertTrue(result["near_schedule_shifted_events"][0]["event_utc"].endswith(".021000+00:00"))
        self.assertEqual(rows[2][0],21)
