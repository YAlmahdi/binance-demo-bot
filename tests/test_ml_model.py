from dataclasses import replace
from unittest.mock import patch
import unittest
import numpy as np
from sklearn.exceptions import ConvergenceWarning
from demo_futures.ml_research.model import fit,RECIPE
from demo_futures.ml_research.config import FOLDS,BUFFER,DEV_END
from demo_futures.ml_research.development_data import TrainingPartition
from test_ml_development_fixtures import synthetic_partition


class MLModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.partition=synthetic_partition(); cls.model=fit(cls.partition)

    def test_scaler_statistics_use_only_training_rows(self):
        x=np.array([f.values for f in self.partition.features])
        np.testing.assert_allclose(self.model.mean,x[:,:14].mean(axis=0),rtol=0,atol=1e-14)
        np.testing.assert_allclose(self.model.scale,x[:,:14].std(axis=0),rtol=0,atol=1e-14)

    def test_deterministic_fixed_recipe_synthetic_refit(self):
        self.assertEqual(self.model,fit(self.partition))
        self.assertEqual(RECIPE["C"],1);self.assertEqual(RECIPE["admission_threshold"],.65)
        self.assertEqual(RECIPE["class_weight"],None)

    def test_binary_flags_are_not_scaled(self):
        self.assertEqual(len(self.model.mean),14);self.assertEqual(len(self.model.coefficients),16)
        f=self.partition.features[0]; x=np.array(f.values)
        x[:14]=(x[:14]-np.array(self.model.mean))/np.array(self.model.scale)
        z=x@np.array(self.model.coefficients)+self.model.intercept
        self.assertAlmostEqual(self.model.predict([f])[0],1/(1+np.exp(-z)),places=14)

    def test_inference_never_calls_fit(self):
        with patch("demo_futures.ml_research.model.LogisticRegression.fit",side_effect=AssertionError("No fit")):
            p=self.model.predict(self.partition.features)
        self.assertTrue(((p>=0)&(p<=1)).all())

    def test_evaluation_rows_rejected_by_training_boundary(self):
        part=self.partition;r=part.labels[-1];f=part.features[-1];t=FOLDS[0][0]+299999
        r=replace(r,row_id=f"{r.symbol}:{t}",decision_time=t,interval_start=t+1,interval_end=t+1+BUFFER)
        f=replace(f,row_id=r.row_id,decision_time=t,available_at=t)
        invalid=replace(part,features=part.features[:-1]+(f,),labels=part.labels[:-1]+(r,))
        with self.assertRaises(PermissionError):fit(invalid)

    def test_embargo_edge_rejected(self):
        part=self.partition;r=part.labels[-1];f=part.features[-1];t=FOLDS[0][0]-2*BUFFER
        r=replace(r,row_id=f"{r.symbol}:{t}",decision_time=t,interval_start=t+1,interval_end=t+1+BUFFER)
        f=replace(f,row_id=r.row_id,decision_time=t,available_at=t)
        with self.assertRaises(PermissionError):replace(part,features=part.features[:-1]+(f,),labels=part.labels[:-1]+(r,)).validate()

    def test_low_samples_refuse_fit(self):
        with self.assertRaisesRegex(ValueError,"INSUFFICIENT"):fit(synthetic_partition(100))

    def test_low_class_count_refuse_fit(self):
        p=self.partition;labels=tuple(replace(r,y=0,trade=replace(r.trade,net_pnl=-abs(r.trade.net_pnl))) for r in p.labels)
        with self.assertRaisesRegex(ValueError,"INSUFFICIENT"):fit(replace(p,labels=labels))

    def test_arrays_cannot_bypass_training_contract(self):
        with self.assertRaises(TypeError):fit(np.zeros((240,16)))

    def test_nonchronological_rows_rejected(self):
        with self.assertRaises(ValueError):replace(self.partition,features=self.partition.features[::-1],labels=self.partition.labels[::-1]).validate()

    def test_schema_and_active_model_refused(self):
        for model in (replace(self.model,execution_enabled=True),replace(self.model,scale=(0,)*14),
                      replace(self.model,intercept=float("nan")),replace(self.model,feature_order=("wrong",)*16)):
            with self.assertRaises(ValueError):model.predict(self.partition.features[:1])

    def test_locked_features_rejected_before_prediction(self):
        f=self.partition.features[0];f=replace(f,row_id=f"{f.symbol}:{DEV_END}",decision_time=DEV_END,available_at=DEV_END)
        with self.assertRaises(ValueError):self.model.predict([f])

    def test_convergence_failure_stops_without_parameter_change(self):
        import warnings
        def no_convergence(*args,**kwargs):warnings.warn("Synthetic failure",ConvergenceWarning)
        with patch("demo_futures.ml_research.model.LogisticRegression.fit",side_effect=no_convergence):
            with self.assertRaises(ConvergenceWarning):fit(self.partition)

    def test_predictions_do_not_mutate_model_or_features(self):
        before=self.model.manifest();features=self.partition.features
        self.model.predict(features);self.assertEqual(before,self.model.manifest());self.assertEqual(features,self.partition.features)
