from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from demo_futures.ml_research.config import START,DEV_END,VALIDATION_END,STEP,SYMBOLS
from demo_futures.ml_research.dataset import file_hash,load_development,open_snapshot


class MLDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.path=Path(cls.temp.name)/"history.sqlite3"
        with sqlite3.connect(cls.path) as db:
            db.execute("CREATE TABLE candles(symbol,interval,open_time,open,high,low,close,volume,close_time,quote_volume,trades)")
            db.execute("CREATE TABLE funding(symbol,timestamp,rate,mark_price)")
            for s in SYMBOLS:
                db.executemany("INSERT INTO candles VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    ((s,"5m",t,100,101,99,100,100,t+STEP-1,10000,10) for t in range(START,DEV_END,STEP)))
                # Protected rows are deliberately invalid. A broad read would fail validation.
                db.execute("INSERT INTO candles VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (s,"5m",VALIDATION_END,-100,-100,-100,-100,-1,VALIDATION_END+STEP-1,0,0))
                db.executemany("INSERT INTO funding VALUES(?,?,?,?)",
                    ((s,t,"0.0001",100) for t in range(START,DEV_END,28_800_000)))
                db.execute("INSERT INTO funding VALUES(?,?,?,?)",(s,VALIDATION_END,"INVALID",-100))
        cls.hash=file_hash(cls.path)

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def test_reads_only_fixed_development_observations(self):
        data=load_development(self.path,self.hash)
        for s in SYMBOLS:
            self.assertEqual(len(data.candles[s]),(DEV_END-START)//STEP)
            self.assertLess(data.candles[s][-1].close_time,DEV_END)
            self.assertTrue(all(f.timestamp<DEV_END for f in data.funding[s]))
        self.assertEqual(file_hash(self.path),self.hash)

    def test_sqlite_query_only_and_read_only(self):
        with closing(open_snapshot(self.path)) as db:
            self.assertEqual(db.execute("PRAGMA query_only").fetchone()[0],1)
            with self.assertRaises(sqlite3.OperationalError): db.execute("DELETE FROM candles")
        self.assertEqual(file_hash(self.path),self.hash)

    def test_protected_period_and_changed_boundaries_rejected_before_file_open(self):
        for start,end in ((START,VALIDATION_END),(DEV_END,VALIDATION_END),(START+STEP,DEV_END)):
            with self.assertRaises(PermissionError):
                load_development("missing.sqlite3","x",start=start,end=end)

    def test_provenance_mismatch_refused(self):
        with self.assertRaises(ValueError): load_development(self.path,"0"*64)

    def test_dataset_mapping_and_rows_immutable(self):
        data=load_development(self.path,self.hash)
        with self.assertRaises(TypeError): data.candles["BTCUSDT"]=()
        with self.assertRaises((AttributeError,TypeError)): data.candles["BTCUSDT"][0].close=1

    def test_active_wal_refused_without_modifying_source(self):
        path=Path(self.temp.name)/"history.sqlite3-wal"
        path.touch()
        try:
            with self.assertRaises(ValueError): open_snapshot(self.path)
        finally: path.unlink()
        self.assertEqual(file_hash(self.path),self.hash)

    def test_invalid_file_kind_refused(self):
        with self.assertRaises(ValueError): open_snapshot(Path(self.temp.name)/"input.csv")

    def test_missing_candle_grid_refused(self):
        path=Path(self.temp.name)/"gap.sqlite3"
        # Fixture-only clone, never the project source.
        with closing(sqlite3.connect(self.path)) as source,closing(sqlite3.connect(path)) as target:
            source.backup(target)
            target.execute("DELETE FROM candles WHERE symbol=? AND open_time=?",("BTCUSDT",START+STEP))
            target.commit()
        with self.assertRaises(ValueError): load_development(path,file_hash(path))

    def test_credential_shaped_path_rejected_before_hashing_or_opening(self):
        with patch("demo_futures.ml_research.dataset.file_hash",side_effect=AssertionError("File content touched")):
            with self.assertRaises(ValueError): load_development(".env","irrelevant")
