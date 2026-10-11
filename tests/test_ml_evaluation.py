import unittest
import numpy as np
from demo_futures.ml_research.evaluation import scores,calibration,block_uncertainty,compare
from test_ml_development_fixtures import synthetic_partition


class MLEvaluationTests(unittest.TestCase):
    def setUp(self):self.labels=synthetic_partition().labels

    def test_hand_calculated_log_loss_brier(self):
        report=scores(self.labels,np.full(len(self.labels),.5))
        self.assertAlmostEqual(report["log_loss"],np.log(2));self.assertEqual(report["brier_score"],.25)

    def test_hard_majority_infinite_loss_is_explicit(self):
        report=scores(self.labels,np.zeros(len(self.labels)))
        self.assertIsNone(report["log_loss"]);self.assertIn("INFINITE",report["log_loss_status"])
        self.assertEqual(report["brier_score"],.5)

    def test_exact_fixed_bucket_boundaries(self):
        p=np.tile(np.arange(12)/11,20);report=calibration(self.labels,p)
        self.assertEqual(sum(b["rows"] for b in report["equal_width_buckets"]),len(p))
        self.assertEqual(len(report["equal_width_buckets"]),10)
        self.assertTrue(report["equal_width_buckets"][-1]["upper_inclusive"])

    def test_probability_validation(self):
        for p in ([-.1]*240,[1.1]*240,[float("nan")]*240,[.5]):
            with self.assertRaises(ValueError):scores(self.labels,p)

    def test_sparse_buckets_and_empty_outcomes_explicit(self):
        b=calibration(self.labels,[.5]*240)["equal_width_buckets"][0]
        self.assertIn("INSUFFICIENT",b["status"]);self.assertEqual(b["rows"],0);self.assertIsNone(b["observed_win_fraction"])

    def test_paired_bootstrap_deterministic_and_positive_improvement(self):
        labels=synthetic_partition(day_blocks=True).labels
        p=np.array([.8 if r.y else .2 for r in labels]);prior=np.full(len(labels),.5)
        a=block_uncertainty(labels,p,prior);self.assertEqual(a,block_uncertainty(labels,p,prior))
        self.assertEqual(a["blocks"],20);self.assertGreater(a["ci_95"]["prior_minus_model_log_loss"][0],0)

    def test_insufficient_blocks_not_fake_confidence(self):
        a=block_uncertainty(self.labels,[.5]*240,[.5]*240)
        self.assertIn("INSUFFICIENT",a["status"])

    def test_equal_prior_fails_improvement_gate(self):
        result=compare(self.labels,[.5]*240,[.5]*240)
        self.assertEqual(result["predictive_gates"]["log_loss_improves_at_least_1pct"],"FAIL")

    def test_admission_threshold_is_not_accuracy_threshold(self):
        a=scores(self.labels,[.64]*240);b=scores(self.labels,[.65]*240)
        self.assertEqual(a["admitted_at_frozen_0_65"],0);self.assertEqual(b["admitted_at_frozen_0_65"],240)
        self.assertEqual(a["accuracy_at_0_5"],b["accuracy_at_0_5"])

    def test_duplicate_labels_refused(self):
        with self.assertRaises(ValueError):scores([self.labels[0]]*2,[.5,.5])
