from dataclasses import replace
from decimal import Decimal as D
import unittest
from types import SimpleNamespace
from demo_futures.backtest import FundingEvent
from demo_futures.ml_research.config import START,DEV_END,STEP,BUFFER,FOLDS
from demo_futures.ml_research.labels import label_opportunity
from demo_futures.ml_research.splits import split_manifest,sufficiency,nonoverlapping
from test_ml_fixtures import candle,opportunity


class MLSplitTests(unittest.TestCase):
    def setUp(self):
        bars=[candle(i) for i in range(49)]
        self.base=label_opportunity(opportunity(bars),bars,(FundingEvent(START,".001",100),))

    def row(self,decision,y=0,symbol="BTCUSDT",status="VALID"):
        trade=replace(self.base.trade,net_pnl=D(1) if y else D(-1)) if status=="VALID" else None
        return replace(self.base,row_id=f"{symbol}:{decision}",symbol=symbol,decision_time=decision,
            interval_start=decision+1,interval_end=decision+1+BUFFER,status=status,
            y=y if status=="VALID" else None,trade=trade)

    def test_purge_and_additional_buffer_exact_boundary(self):
        begin=FOLDS[0][0]
        allowed=self.row(begin-2*BUFFER-1)
        buffered=self.row(begin-2*BUFFER)
        overlap=self.row(begin-BUFFER)
        fold=split_manifest([allowed,buffered,overlap])["folds"][0]
        self.assertEqual(fold["train_ids"],[allowed.row_id])
        self.assertEqual(fold["excluded_ids"][buffered.row_id],"FOUR_HOUR_BUFFER")
        self.assertEqual(fold["excluded_ids"][overlap.row_id],"PURGED_OVERLAP")

    def test_evaluation_full_horizon_including_exclusive_endpoint(self):
        begin,end=FOLDS[0]
        at_begin=self.row(begin+STEP-1)
        allowed=self.row(end-BUFFER-1)
        excluded=self.row(end-BUFFER)
        fold=split_manifest([at_begin,allowed,excluded])["folds"][0]
        self.assertEqual(fold["evaluation_ids"],[at_begin.row_id,allowed.row_id])
        self.assertEqual(fold["excluded_ids"][excluded.row_id],"EVALUATION_HORIZON_CUTOFF")

    def test_same_timestamp_symbols_grouped_and_no_shuffle(self):
        begin=FOLDS[0][0]
        rows=[self.row(begin+STEP-1,1,"ETHUSDT"),self.row(begin+STEP-1,0,"BTCUSDT")]
        fold=split_manifest(rows)["folds"][0]
        self.assertEqual(fold["evaluation_ids"],[rows[1].row_id,rows[0].row_id])
        self.assertFalse(fold["train_ids"])

    def test_hard_train_sample_and_class_gates(self):
        rows=[self.row(START+i*STEP+STEP-1,int(i%5==0)) for i in range(200)]
        self.assertEqual(sufficiency(rows,"train")["status"],"SUFFICIENT")
        self.assertEqual(sufficiency(rows[:199],"train")["status"],"INSUFFICIENT")
        rows[-5]=replace(rows[-5],y=0,trade=replace(rows[-5].trade,net_pnl=D(-1)))
        self.assertEqual(sufficiency(rows,"train")["status"],"INSUFFICIENT")

    def test_hard_evaluation_nonoverlap_gate(self):
        dense=[self.row(START+i*STEP+STEP-1,i%2) for i in range(100)]
        gate=sufficiency(dense,"development_evaluation")
        self.assertEqual(gate["status"],"INSUFFICIENT")
        self.assertTrue(gate["checks"]["rows"]);self.assertTrue(gate["checks"]["class_1"])
        sparse=[self.row(START+i*BUFFER+STEP-1,i%2) for i in range(100)]
        self.assertEqual(sufficiency(sparse,"development_evaluation")["status"],"SUFFICIENT")

    def test_exclusions_never_count_as_class_zero(self):
        begin=FOLDS[0][0]
        r=self.row(begin+STEP-1,status="FUNDING_UNCERTAIN")
        f=split_manifest([r])["folds"][0]
        self.assertEqual(f["evaluation_gate"]["class_0"],0)
        self.assertEqual(f["exclusion_counts"],{"FUNDING_UNCERTAIN":1})

    def test_nonoverlap_deterministic_btc_priority_and_interval_end(self):
        first=self.row(START+STEP-1,0,"BTCUSDT")
        eth=self.row(first.decision_time,1,"ETHUSDT")
        next_row=self.row(first.interval_end-1)
        self.assertEqual(nonoverlapping([eth,next_row,first]),[first.row_id,next_row.row_id])

    def test_training_intervals_are_buffered_and_ids_disjoint_all_folds(self):
        rows=[self.row(START+i*STEP+STEP-1,i%2) for i in range((DEV_END-START-BUFFER)//STEP)]
        by_id={r.row_id:r for r in rows}
        manifest=split_manifest(rows)
        for f in manifest["folds"]:
            self.assertFalse(set(f["train_ids"])&set(f["evaluation_ids"]))
            self.assertTrue(all(by_id[r].interval_end<=f["evaluation_start"]-BUFFER for r in f["train_ids"]))
            self.assertTrue(all(f["evaluation_start"]<=by_id[r].decision_time<f["evaluation_end"] for r in f["evaluation_ids"]))

    def test_previous_evaluation_can_become_matured_training_only_later(self):
        r=self.row(FOLDS[0][0]+STEP-1)
        manifest=split_manifest([r])
        self.assertIn(r.row_id,manifest["folds"][0]["evaluation_ids"])
        self.assertIn(r.row_id,manifest["folds"][1]["train_ids"])

    def test_protected_rows_and_duplicate_ids_refused(self):
        with self.assertRaises(PermissionError): split_manifest([SimpleNamespace(row_id="locked",symbol="BTCUSDT",decision_time=DEV_END)])
        r=self.row(START+STEP-1)
        with self.assertRaises(PermissionError): split_manifest([r,r])

    def test_protected_gate_refused_not_inferred(self):
        with self.assertRaises(PermissionError): sufficiency([],"final")
        with self.assertRaises(PermissionError): sufficiency([],"selection_validation")

    def test_manifest_determinism_and_locked_boundaries_without_outcomes(self):
        rows=[self.row(START+i*STEP+STEP-1,i%2) for i in range(100)]
        manifest=split_manifest(rows)
        self.assertEqual(manifest,split_manifest(list(reversed(rows))))
        for name in ("selection_validation","final"):
            self.assertEqual(manifest[name]["status"],"LOCKED / NOT EVALUATED")
            self.assertNotIn("class_0",manifest[name])
            self.assertNotIn("ids",manifest[name])

    def test_sample_gate_refuses_duplicate_and_locked_rows_before_class_counts(self):
        r=self.row(START+STEP-1)
        with self.assertRaises(PermissionError): sufficiency([r,r],"train")
        locked=SimpleNamespace(row_id="locked",symbol="BTCUSDT",decision_time=DEV_END)
        with self.assertRaises(PermissionError): sufficiency([locked],"train")

    def test_shortened_interval_and_invalid_identity_refused(self):
        r=self.row(START+STEP-1)
        with self.assertRaises(ValueError): replace(r,interval_end=r.interval_end-STEP)
        with self.assertRaises(ValueError): replace(r,row_id="mismatched-id")
