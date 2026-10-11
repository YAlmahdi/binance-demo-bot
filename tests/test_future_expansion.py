import json
import tempfile
import unittest
from pathlib import Path
from demo_futures.future_expansion import validate_range, contract_metadata, candle_page, candle_defects, funding_page, probe, collect, audit
from demo_futures.public_history import public_url, PublicDemoHistory, PublicHistoryError, FUTURE_EXPANSION_SYMBOLS, SYMBOLS, STEP, DAY
from demo_futures.data import DataQualityError, SUPPORTED_SYMBOLS
from test_public_history import row, Fake, Opener

class ExpansionTests(unittest.TestCase):
    def test_expansion_is_explicit_and_does_not_change_active_symbols(self):
        self.assertEqual(SYMBOLS, ("BTCUSDT", "ETHUSDT"))
        self.assertEqual(SUPPORTED_SYMBOLS, frozenset(SYMBOLS))
        for symbol in FUTURE_EXPANSION_SYMBOLS:
            p=dict(symbol=symbol, interval="5m", startTime=0, endTime=STEP-1, limit=1)
            with self.assertRaises(ValueError): public_url("/fapi/v1/klines",p)
            self.assertTrue(public_url("/fapi/v1/klines",p,future_expansion=True).startswith("https://demo-fapi.binance.com/"))
        with self.assertRaises(ValueError): public_url("/fapi/v1/exchangeInfo")
        self.assertEqual(public_url("/fapi/v1/exchangeInfo",future_expansion=True), "https://demo-fapi.binance.com/fapi/v1/exchangeInfo")

    def test_both_scopes_reject_private_orders_origins_and_authentication(self):
        p=dict(symbol="SOLUSDT", interval="5m", startTime=0, endTime=STEP-1, limit=1)
        for flag in (False,True):
            for path in ("/fapi/v1/order", "/fapi/v1/order/test", "/fapi/v3/balance", "/fapi/v1/openInterest", "https://fapi.binance.com/fapi/v1/klines"):
                with self.assertRaises(ValueError): public_url(path,p,future_expansion=flag)
        for change in ({"signature":"forbidden"},{"symbol":"BTCUSDT"},{"symbol":"DOGEUSDT"},{"interval":"1h"},{"startTime":True},{"limit":1001}):
            with self.assertRaises(ValueError): public_url("/fapi/v1/klines",dict(p,**change),future_expansion=True)
        with self.assertRaises(ValueError): PublicDemoHistory(future_expansion="yes")

    def test_metadata_transport_is_unsigned_and_validated(self):
        opener=Opener({"symbols":[],"rateLimits":[]})
        client=PublicDemoHistory(opener,pause=0,sleeper=lambda _:None,future_expansion=True)
        client.get("/fapi/v1/exchangeInfo")
        request=opener.calls[0]
        self.assertEqual(request.get_method(),"GET")
        self.assertIsNone(request.data)
        self.assertFalse(any(k.lower() in ("authorization","x-mbx-apikey") for k in request.headers))
        with self.assertRaises(DataQualityError): PublicDemoHistory(Opener([]),pause=0,sleeper=lambda _:None,future_expansion=True).get("/fapi/v1/exchangeInfo")

    def test_expansion_transport_retains_redirect_block(self):
        with self.assertRaises(PublicHistoryError): PublicDemoHistory(Opener({"serverTime":1},redirect=True),pause=0,sleeper=lambda _:None,future_expansion=True).get("/fapi/v1/time")

    def test_1200_request_budget_stops_before_transport(self):
        opener=Opener({"serverTime":1})
        client=PublicDemoHistory(opener,pause=0,sleeper=lambda _:None,future_expansion=True)
        client.requests=[{}]*1200
        with self.assertRaises(PublicHistoryError): client.get("/fapi/v1/time")
        self.assertEqual(opener.calls,[])

    def test_range_completed_and_180_day_hard_bound(self):
        validate_range("SOLUSDT",0,180*DAY,180*DAY+1)
        for symbol,start,end,server in (("BTCUSDT",0,STEP,STEP+1),("SOLUSDT",1,STEP,STEP+1),("SOLUSDT",0,181*DAY,182*DAY),("SOLUSDT",0,STEP,STEP-1),("SOLUSDT",False,STEP,STEP+1)):
            with self.assertRaises(DataQualityError): validate_range(symbol,start,end,server)

    def test_contract_requires_exact_perpetual_usdt_metadata(self):
        item=dict(symbol="SOLUSDT",contractType="PERPETUAL",status="TRADING",quoteAsset="USDT",marginAsset="USDT")
        self.assertEqual(contract_metadata({"symbols":[item]},"SOLUSDT"),item)
        for items in ([],[item,item],[dict(item,contractType="CURRENT_QUARTER")],[dict(item,marginAsset="USDC")]):
            with self.assertRaises(DataQualityError): contract_metadata({"symbols":items},"SOLUSDT")

    def test_candle_gaps_are_preserved_but_bad_pages_rejected(self):
        bars=candle_page([row(0),row(2*STEP)],0,3*STEP,3*STEP+1)
        self.assertEqual([b.open_time for b in bars],[0,2*STEP])
        for rows in ([row(0),row(0)],[row(STEP),row(0)],[row(3*STEP)],[row(0)[:3]]):
            with self.assertRaises((DataQualityError,TypeError)): candle_page(rows,0,3*STEP,3*STEP+1)

    def test_raw_defects_and_extreme_flags_not_repaired(self):
        bad=row(0);bad[2]="90"
        d=candle_defects([row(STEP),row(0),row(0),bad],0,3*STEP,3*STEP+1)
        self.assertEqual(d,dict(duplicate_rows=2,non_monotonic_rows=1,invalid_rows=1))
        extreme=row(0);extreme[2]="120"
        bars=candle_page([extreme],0,STEP,STEP+1)
        self.assertEqual(audit(bars,[],0,STEP,STEP+1)["candles"]["bars_with_range_over_5pct"],1)

    def test_funding_sign_timestamp_and_mark_validity(self):
        r=dict(symbol="SOLUSDT",fundingTime=1,fundingRate="-.001",markPrice="100")
        self.assertEqual(funding_page([r],"SOLUSDT",0,STEP),[r])
        for rows in ([r,r],[dict(r,symbol="ETHUSDT")],[dict(r,fundingRate="NaN")],[dict(r,markPrice="-1")],[dict(r,fundingTime=STEP)]):
            with self.assertRaises(DataQualityError): funding_page(rows,"SOLUSDT",0,STEP)

    def test_collection_fixed_pagination_retains_empty_windows(self):
        end=500*STEP
        fake=Fake([[],[row(499*STEP)],[]])
        bars,funding,failures,defects,scanned,fscan=collect(fake,"SOLUSDT",0,end,end+1)
        self.assertEqual(len(bars),1)
        self.assertEqual(fake.calls[1][1]["startTime"],499*STEP)
        self.assertEqual(fake.calls[1][1]["limit"],1)
        quality=audit(bars,funding,0,end,end+1)
        self.assertEqual(quality["candles"]["missing_target_intervals"],499)
        self.assertFalse(quality["candles"]["covers_target"])
        self.assertEqual(quality["funding"]["completeness"],"UNKNOWN")
        self.assertEqual(scanned,end)

    def test_funding_short_page_verified_to_exhaustion(self):
        r=dict(symbol="SOLUSDT",fundingTime=1,fundingRate="-.001",markPrice="100")
        fake=Fake([[row(0)],[r],[]])
        result=collect(fake,"SOLUSDT",0,STEP,STEP+1)
        self.assertEqual(result[1],[r])
        self.assertEqual(fake.calls[2][1]["startTime"],2)

    def test_invalid_page_quarantines_without_accepting_rows(self):
        fake=Fake([[row(0),row(0)],[]])
        bars,funding,failures,defects,scanned,fscan=collect(fake,"SOLUSDT",0,2*STEP,2*STEP+1)
        self.assertEqual(bars,[])
        self.assertEqual(defects["duplicate_rows"],1)
        self.assertEqual(failures[0]["raw_rows_excluded"],2)
        self.assertEqual(scanned,0)

    def test_probe_checks_multiple_boundaries_not_one_request(self):
        end=4*STEP
        fake=Fake([[row(0)],[row(2*STEP)],[row(3*STEP)],[],[]])
        result=probe(fake,"SOLUSDT",0,end,end+1)
        self.assertEqual(len(result),5)
        self.assertEqual(len(fake.calls),5)

    def test_funding_modal_schedule_never_claims_complete_or_zero(self):
        r=[dict(symbol="SOLUSDT",fundingTime=t,fundingRate="-.001",markPrice="100") for t in (0,STEP,3*STEP)]
        q=audit(candle_page([row(0)],0,4*STEP,4*STEP+1),r,0,4*STEP,4*STEP+1)
        self.assertEqual(q["funding"]["negative_rates"],3)
        self.assertEqual(q["funding"]["completeness"],"UNKNOWN")
        self.assertEqual(q["candles"]["missing_target_intervals"],3)

    def test_transport_failure_preserves_valid_prefix_and_stops(self):
        class Broken:
            def __init__(self): self.calls=0
            def get(self,path,params):
                self.calls+=1
                if self.calls==1: return [row(0)]
                raise PublicHistoryError(429)
        fake=Broken()
        bars,funding,failures,defects,scanned,fscan=collect(fake,"SOLUSDT",0,500*STEP,500*STEP+1)
        self.assertEqual(len(bars),1)
        self.assertEqual(fake.calls,2)
        self.assertEqual(failures[0]["http_status"],429)
        self.assertEqual(funding,[])


class SnapshotSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import importlib.util
        file=Path(__file__).resolve().parents[1]/"scripts/collect_future_expansion.py"
        spec=importlib.util.spec_from_file_location("expansion_runner_test",file)
        cls.runner=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.runner)

    def test_snapshot_json_and_csv_refuse_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"snapshot.json"
            self.runner.save_json(path,{"public":True})
            before=path.read_bytes()
            with self.assertRaises(FileExistsError): self.runner.save_json(path,{"public":False})
            self.assertEqual(path.read_bytes(),before)
            csv=Path(tmp)/"candles.csv"
            self.runner.save_csv(csv,["symbol"],[{"symbol":"SOLUSDT"}])
            with self.assertRaises(FileExistsError): self.runner.save_csv(csv,["symbol"],[])

    def make_guard(self):
        from unittest.mock import patch
        with patch.object(self.runner.sys,"addaudithook") as register:
            self.runner.install_guard(Path("new-snapshot"),Path("new-report"))
        return register.call_args.args[0]

    def test_runner_guard_blocks_private_files_old_databases_and_ml(self):
        guard=self.make_guard()
        for path in (self.runner.ROOT/".env",self.runner.ROOT/"data/market.sqlite3",self.runner.ROOT/"artifacts/ml-research/locked/labels.csv"):
            with self.assertRaises(RuntimeError): guard("open",(str(path),"r",0))
        with self.assertRaises(RuntimeError): guard("open",(str(self.runner.ROOT/"src/demo_futures/risk.py"),"w",1))
        for name in ("demo_futures.client","demo_futures.config","demo_futures.ml_research.model"):
            with self.assertRaises(RuntimeError): guard("import",(name,))

    def test_runner_guard_revalidates_exact_unsigned_demo_get(self):
        guard=self.make_guard()
        good=public_url("/fapi/v1/klines",dict(symbol="SOLUSDT",interval="5m",startTime=0,endTime=STEP-1,limit=1),future_expansion=True)
        guard("urllib.Request",(good,None,{},"GET"))
        for url,body,headers,method in ((good,None,{},"POST"),(good,b"x",{},"GET"),(good,None,{"X-MBX-APIKEY":"dummy"},"GET"),(good+"&signature=forbidden",None,{},"GET"),(good.replace("demo-fapi.binance.com","fapi.binance.com"),None,{},"GET"),(good.replace("SOLUSDT","BTCUSDT"),None,{},"GET")):
            with self.assertRaises((RuntimeError,ValueError)): guard("urllib.Request",(url,body,headers,method))
        with self.assertRaises(RuntimeError): guard("socket.getaddrinfo",("fapi.binance.com",443))

    def test_recorder_request_and_weight_budgets_stop_before_get(self):
        class Mock:
            requests=[{"used_weight_headers":{"x-mbx-used-weight-1m":1920}}]
            def get(self,*args): raise AssertionError("Network must not run")
        recorder=self.runner.Recorder(Mock(),Path("unused"))
        with self.assertRaises(PublicHistoryError): recorder.get("/fapi/v1/time")
        recorder.calls=700
        with self.assertRaises(PublicHistoryError): recorder.get("/fapi/v1/time")

    def test_raw_response_receipt_keeps_hash_and_requested_bounds(self):
        import hashlib
        payload=[row(0)]
        digest=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
        class Mock:
            requests=[]
            def get(self,path,params):
                self.requests.append(dict(received_at_ms=10,response_sha256=digest))
                return payload
        with tempfile.TemporaryDirectory() as tmp:
            recorder=self.runner.Recorder(Mock(),Path(tmp))
            params=dict(symbol="SOLUSDT",interval="5m",startTime=0,endTime=STEP-1,limit=1)
            self.assertEqual(recorder.get("/fapi/v1/klines",params),payload)
            receipt=json.loads(next(Path(tmp).glob("*.json")).read_text())
            self.assertEqual(receipt["params"],params)
            self.assertEqual(receipt["response_sha256"],digest)
            self.assertEqual(receipt["origin"],"https://demo-fapi.binance.com")
