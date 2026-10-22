"""Pure synthetic-only preprocessing estimation; no data access or model fitting.

The supplied receipt declares the eligible post-purge/post-buffer training set.
Its consistency is checked, not its historical authenticity, as-of availability
or paired-label validity. A result grants no research or execution authority.
"""
from dataclasses import dataclass, field

from .config import FEATURES
from . import validation


@dataclass(frozen=True)
class PreprocessingEstimate:
    diagnostic: validation.TrainingStatisticsCheck
    contract: validation.TransformContract | None = None
    evidence: str = field(default="SYNTHETIC_ONLY", init=False)
    authority: str = field(default="SYNTHETIC_PREPROCESSING_ONLY", init=False)

    def __post_init__(self):
        if (type(self.diagnostic) is not validation.TrainingStatisticsCheck
                or (self.diagnostic.status == "CONSISTENT") != (self.contract is not None)
                or (self.contract is not None and type(self.contract) is not validation.TransformContract)):
            raise ValueError("Only consistent estimation may retain a transform contract")

    @property
    def status(self):
        return self.diagnostic.status

    @property
    def reasons(self):
        return self.diagnostic.reasons

    def __bool__(self):
        raise TypeError("Inspect status explicitly; estimation grants no authority")


def estimate_preprocessing(rows, receipt, expected_training_receipt, *, feature_names=FEATURES):
    """Estimate only the exact ordered, explicitly declared synthetic training set.

    Shared validation preflight must pass before arithmetic. Both estimator and
    validator use one two-pass numerical implementation; the completed contract
    must also pass the public validator before it can be returned. No clipping,
    imputation, evaluation inputs, partial contracts or fallback statistics.
    Values are finite builtin binary floats or exactly representable integers;
    Decimal, foreign numeric types and inexact integer conversions are refused.
    """
    def rejected(reason):
        return PreprocessingEstimate(validation.TrainingStatisticsCheck("INVALID", (reason,)))

    if (type(feature_names) is not tuple
            or any(type(name) is not str for name in feature_names)
            or feature_names != FEATURES):
        return rejected("FEATURE_SCHEMA_MISMATCH")
    captured, owned_receipt, check = validation._capture_training_population(
        rows, receipt, expected_training_receipt)
    if check.status != "CONSISTENT":
        return PreprocessingEstimate(check)
    try:
        lower, upper, mean, scale = validation._population_statistics(captured)
        contract = validation.TransformContract(owned_receipt, lower, upper, mean, scale)
        check = validation.check_training_statistics(captured, contract, owned_receipt)
        return PreprocessingEstimate(check, contract if check.status == "CONSISTENT" else None)
    except validation._StatisticsError as error:
        return rejected(str(error))
    except (ValueError, TypeError, OverflowError, AttributeError):
        return rejected("INVALID_CONTRACT_OR_NUMERIC_INPUT")
