import csv
from dataclasses import asdict
from decimal import Decimal
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from demo_futures.backtest import FundingEvent
from demo_futures.ml_research.artifacts import feature_csv,label_csv,isolated_journal_csv,verify_inputs,write_bundle
from demo_futures.ml_research.audit import payoff_summary,development_audit,risk_diagnostics
from demo_futures.ml_research.config import ExperimentConfig,canonical,digest,START
from demo_futures.ml_research.dataset import file_hash
from demo_futures.ml_research.features import causal_indicators,feature_at
from demo_futures.ml_research.labels import label_opportunity
from test_ml_fixtures import candle,history,opportunity


class MLArtifactTests(unittest.TestCase):
    def test_recipe_and_threshold_frozen(self):
        config=ExperimentConfig()
        self.assertEqual(config.admission_threshold,"0.65")
        for change in ({"admission_threshold":"0.64"},{"horizon_bars":24},{"buffer_ms":0},{"seed":1}):
            with self.assertRaises(ValueError): ExperimentConfig(**change)
        self.assertFalse(config.manifest()["execution_enabled"])
        self.assertFalse(config.manifest()["model_fitting_approved"])

    def test_deterministic_fingerprints_and_no_nonfinite_json(self):
        self.assertEqual(digest({"b":2,"a":1}),digest({"a":1,"b":2}))
        self.assertNotEqual(digest({"a":1}),digest({"a":2}))
        self.assertEqual(canonical({"cost":Decimal(".1")}),'{"cost":"0.1"}')
        with self.assertRaises(ValueError): canonical({"x":float("nan")})

    def test_immutable_bundle_exact_replay_and_refusal_to_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"experiment"
            first=write_bundle(path,{"config.json":canonical(ExperimentConfig().manifest())+"\n"})
            before={p.name:p.read_bytes() for p in path.iterdir()}
            self.assertEqual(first,write_bundle(path,{"config.json":canonical(ExperimentConfig().manifest())+"\n"}))
            self.assertEqual(before,{p.name:p.read_bytes() for p in path.iterdir()})
            manifest=json.loads((path/"manifest.json").read_text())
            self.assertFalse(manifest["fitted_model"])
            with self.assertRaises(FileExistsError): write_bundle(path,{"config.json":"changed"})
            with self.assertRaises(ValueError): write_bundle(Path(folder)/"bad",{"../escape":"x"})

    def test_protected_hashes_detect_mutation_not_just_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"fixture.txt";path.write_text("old")
            witness={path.name:file_hash(path)}
            self.assertEqual(verify_inputs(folder,witness)["status"],"UNCHANGED")
            path.write_text("new")
            with self.assertRaises(ValueError): verify_inputs(folder,witness)

    def test_feature_and_label_exports_are_separate_and_deterministic(self):
        bars=history();indicators=causal_indicators(bars)
        feature=feature_at("BTCUSDT",bars,indicators,300,"LONG")[0]
        label=label_opportunity(opportunity(bars,index=300),bars,(FundingEvent(START,".001",100),))
        features=feature_csv([feature]);labels=label_csv([label])
        self.assertEqual(features,feature_csv([feature]))
        self.assertEqual(labels,label_csv([label]))
        feature_row=next(csv.DictReader(io.StringIO(features)))
        self.assertNotIn("y",feature_row);self.assertNotIn("net_pnl",feature_row)
        self.assertEqual(len(feature_row),20)
        label_row=next(csv.DictReader(io.StringIO(labels)))
        self.assertIn("y",label_row);self.assertIn("net_pnl",label_row)
        trade=next(csv.DictReader(io.StringIO(isolated_journal_csv([label]))))
        self.assertEqual(trade["row_id"],label.row_id)
        self.assertEqual(Decimal(trade["net_pnl"]),label.trade.net_pnl)

    def test_empty_payoffs_undefined_not_fabricated(self):
        summary=payoff_summary([])
        self.assertIsNone(summary["mean_winning_net_pnl"])
        self.assertIsNone(summary["payoff_ratio"])
        self.assertEqual(summary["isolated_outcomes"],0)

    def test_offline_guard_refuses_network_credentials_and_training_imports(self):
        source = """import sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()/"src"))
from demo_futures.ml_research.safety import offline_guard
offline_guard(Path.cwd())
for event,args in [('socket.connect',()),('socket.getaddrinfo',()),('urllib.Request',()),
                   ('open',('.env','r',0)),('open',('credentials.json','r',0)),
                   ('import',('demo_futures.client',)),('import',('sklearn',))]:
    try: sys.audit(event,*args)
    except RuntimeError: pass
    else: raise AssertionError(event+' was allowed')
print('guard fixtures passed')
"""
        result=subprocess.run([sys.executable,"-B","-c",source],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn("guard fixtures passed",result.stdout)

    def test_entrypoint_has_no_training_or_unlock_command(self):
        script=Path(__file__).resolve().parents[1]/"scripts/ml_research.py"
        result=subprocess.run([sys.executable,"-B",str(script),"train"],capture_output=True,text=True)
        self.assertEqual(result.returncode,2)
        self.assertIn("invalid choice",result.stderr)

    def test_end_to_end_engineering_audit_determinism_and_no_model_scores(self):
        from demo_futures.ml_research.opportunities import enumerate_opportunities
        from demo_futures.ml_research.splits import split_manifest
        markets={"BTCUSDT":history(),"ETHUSDT":history(direction=-1)}
        opportunities,features,counts=enumerate_opportunities(markets)
        funds=(FundingEvent(START,".001",100),)
        labels=tuple(label_opportunity(o,markets[o.symbol],funds) for o in opportunities)
        split=split_manifest(labels)
        inputs=(SimpleNamespace(audit={"synthetic":True}),opportunities,features,labels,split,counts,{"synthetic":True})
        first=development_audit(*inputs)
        self.assertEqual(canonical(first),canonical(development_audit(*inputs)))
        self.assertEqual(first["engineering_checks"],"PASS")
        self.assertGreater(first["label_counts"]["VALID"],0)
        self.assertIn("INCOMPLETE_HORIZON",first["label_counts"])
        self.assertEqual(first["final"],"LOCKED / NOT EVALUATED")
        self.assertIn("NOT AVAILABLE",first["probability_buckets"])
        self.assertNotIn("accuracy",first)
        self.assertEqual(first["isolated_development_payoffs"]["isolated_outcomes"],first["label_counts"]["VALID"])

    def test_artifact_writer_allows_only_declared_research_filenames(self):
        with tempfile.TemporaryDirectory() as folder:
            for name in ("credentials.json","secret.key","unexpected.json",".env"):
                with self.assertRaises(ValueError): write_bundle(Path(folder)/"forbidden",{name:"dummy"})

    def test_recorded_funding_overrun_explained_without_changing_label(self):
        bars=[candle(i) for i in range(49)]
        bars[2]=candle(2,high=101,low=97)
        funds=(FundingEvent(START+450000,".003",100),)
        label=label_opportunity(opportunity(bars),bars,funds)
        original=asdict(label)
        diagnostics=risk_diagnostics([label])
        self.assertEqual(diagnostics["planned_entry_budget_violations"],0)
        self.assertEqual(diagnostics["entry_leverage_violations"],0)
        overrun=diagnostics["realized_loss_budget_overruns"][0]
        self.assertTrue(overrun["stop_ledger_reconciles"])
        self.assertEqual(overrun["cause"],"Recorded funding debit exceeded sizing reserve")
        self.assertIn("NOT CLEARED",diagnostics["risk_clearance"])
        self.assertEqual(original,asdict(label))
        self.assertEqual(label.y,0)
