from dataclasses import replace
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from demo_futures.ml_research.development_data import load_engineering,training_partition,evaluation_rows
from demo_futures.ml_research.development_runtime import write_version
from demo_futures.ml_research.config import FOLDS,BUFFER,DEV_END
from test_ml_development_fixtures import synthetic_partition

ROOT=Path(__file__).resolve().parents[1]


class MLDevelopmentDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.rows=load_engineering(ROOT)

    def test_actual_saved_rows_and_fixed_gates(self):
        self.assertEqual(len(self.rows.features),2397)
        self.assertEqual(sum(r.status=="VALID" for r in self.rows.labels.values()),2390)
        for n,counts in ((1,(1033,371)),(2,(1409,388)),(3,(1796,566))):
            p=training_partition(self.rows,n);e=evaluation_rows(self.rows,n)
            self.assertEqual((len(p.labels),len(e)),counts)
            self.assertTrue(all(r.interval_end<=FOLDS[n-1][0]-BUFFER for r in p.labels))
            self.assertFalse(set(r.row_id for r in p.labels)&set(r.row_id for r in e))

    def test_future_evaluation_label_changes_cannot_enter_training(self):
        p=training_partition(self.rows,1)
        labels=dict(self.rows.labels)
        for r in evaluation_rows(self.rows,1):
            labels[r.row_id]=replace(r,y=1-r.y,trade=replace(r.trade,net_pnl=-r.trade.net_pnl))
        altered=replace(self.rows,labels=labels)
        self.assertEqual(p,training_partition(altered,1))

    def test_unknown_or_locked_stage_refused(self):
        for n in (0,4,"selection_validation",True):
            with self.assertRaises(PermissionError):training_partition(self.rows,n)
            with self.assertRaises(PermissionError):evaluation_rows(self.rows,n)

    def test_new_artifacts_are_exclusive(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"version";m=write_version(path,{"model.json":"{}\n"})
            self.assertFalse(m["execution_enabled"]);self.assertEqual(m["risk_evidence"],"NOT CLEARED")
            with self.assertRaises(FileExistsError):write_version(path,{"model.json":"{}\n"})

    def test_artifact_paths_cannot_escape(self):
        with tempfile.TemporaryDirectory() as d:
            for n in ("../outside.json","model.pkl",".env"):
                with self.assertRaises(ValueError):write_version(Path(d)/"version",{n:"dummy"})

    def test_runtime_blocks_network_and_credentials_in_child(self):
        source=f"""import sys
sys.path.insert(0,{str(ROOT/'src')!r})
from demo_futures.ml_research.development_runtime import guard
guard({str(ROOT)!r})
import socket
for action in (lambda: socket.getaddrinfo('example.invalid',443),lambda: open({str(ROOT/'.env')!r})): 
 try: action()
 except PermissionError: pass
 else: raise AssertionError('Guard failed')
print('blocked')
"""
        result=subprocess.run([sys.executable,"-B","-c",source],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr);self.assertIn("blocked",result.stdout)

    def test_training_labels_keep_financial_outcomes_out_of_feature_values(self):
        p=synthetic_partition();self.assertEqual(len(p.features[0].values),16)
        self.assertNotIn("net_pnl",p.features[0].__dataclass_fields__)
