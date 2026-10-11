"""Fixed L2 logistic fit with training-only standardization; inert JSON model."""
from dataclasses import dataclass, asdict
import math
import warnings
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.exceptions import ConvergenceWarning
from threadpoolctl import threadpool_limits
from .development_data import TrainingPartition, validate_feature
from .config import FEATURE_NAMES, digest

RECIPE = {"penalty": "L2", "C": 1.0, "solver": "lbfgs", "fit_intercept": True,
          "class_weight": None, "max_iter": 2000, "random_state": 42,
          "continuous_columns": list(range(14)), "binary_passthrough": [14,15],
          "admission_threshold": 0.65, "thread_limit": 1}


@dataclass(frozen=True)
class FrozenModel:
    fold: int
    mean: tuple
    scale: tuple
    coefficients: tuple
    intercept: float
    iterations: int
    training_prevalence: float
    training_ids_sha256: str
    training_rows: int
    feature_order: tuple = FEATURE_NAMES
    execution_enabled: bool = False

    def validate(self):
        if (type(self.fold) is not int or not 1<=self.fold<=3 or self.execution_enabled
                or self.feature_order != FEATURE_NAMES or len(self.mean)!=14 or len(self.scale)!=14
                or len(self.coefficients)!=16 or any(s<=0 for s in self.scale)
                or not all(math.isfinite(v) for v in (*self.mean,*self.scale,*self.coefficients,self.intercept))
                or not 0<self.training_prevalence<1 or not 1<=self.iterations<2000):
            raise ValueError("Invalid inactive research model schema")

    def predict(self, features):
        self.validate()
        features = tuple(features)
        for f in features: validate_feature(f)
        if not features: return np.array([],dtype=np.float64)
        x = np.asarray([f.values for f in features], dtype=np.float64).copy()
        x[:,:14] = (x[:,:14]-np.asarray(self.mean))/np.asarray(self.scale)
        with threadpool_limits(limits=1):
            z = x@np.asarray(self.coefficients)+self.intercept
        # Stable sigmoid, without probability clipping or post-fit calibration.
        result = np.empty_like(z); positive = z>=0
        result[positive] = 1/(1+np.exp(-z[positive]))
        e = np.exp(z[~positive]); result[~positive] = e/(1+e)
        return result

    def manifest(self):
        return {**asdict(self), "recipe": RECIPE, "status": "INACTIVE_DEVELOPMENT_RESEARCH_MODEL"}


def fit(partition):
    if not isinstance(partition,TrainingPartition):
        raise TypeError("Fit accepts a checked training partition, never evaluation arrays")
    partition.validate()
    x = np.asarray([f.values for f in partition.features], dtype=np.float64)
    y = np.asarray([r.y for r in partition.labels], dtype=np.int64)
    with threadpool_limits(limits=1), warnings.catch_warnings():
        warnings.simplefilter("error", ConvergenceWarning)
        scaler = StandardScaler().fit(x[:,:14])
        transformed = x.copy(); transformed[:,:14] = scaler.transform(x[:,:14])
        # sklearn 1.9: l1_ratio=0 and no elastic-net mixing specifies L2.
        estimator = LogisticRegression(l1_ratio=0, C=1.0, solver="lbfgs", fit_intercept=True,
                                       class_weight=None, max_iter=2000, random_state=42)
        estimator.fit(transformed,y)
        model = FrozenModel(partition.fold, tuple(float(v) for v in scaler.mean_),
                            tuple(float(v) for v in scaler.scale_), tuple(float(v) for v in estimator.coef_[0]),
                            float(estimator.intercept_[0]), int(estimator.n_iter_[0]), float(y.mean()),
                            digest([r.row_id for r in partition.labels]), len(y))
        model.validate()
        if not np.allclose(model.predict(partition.features),estimator.predict_proba(transformed)[:,1],rtol=0,atol=1e-12):
            raise ArithmeticError("JSON model does not reproduce fitted probabilities")
    return model
