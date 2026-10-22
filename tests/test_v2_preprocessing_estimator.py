"""Synthetic preprocessing only; independent references, no outcomes or models."""
from dataclasses import FrozenInstanceError, dataclass, replace
from decimal import Decimal, localcontext
from fractions import Fraction
import math
import unittest
from unittest.mock import patch

from demo_futures.research_v2.config import FEATURES, HOUR, SYMBOLS
from demo_futures.research_v2 import validation
from demo_futures.research_v2.preprocessing import PreprocessingEstimate, estimate_preprocessing
from test_v2_preprocessing_validation import BASE, fixture


def receipt_for(rows, window):
    identities = tuple(row.row_id for row in rows)
    return validation.TrainingReceipt(identities, validation.ids_hash(identities), window)


def varied_rows():
    rows, contract = fixture()
    varied = tuple(replace(row, values=tuple(
        float((i // 2 % 4 * 2) * (j + 1) + j) for j in range(8))
        + (row.values[-1],)) for i, row in enumerate(rows))
    return varied, contract.receipt


class EstimatorTests(unittest.TestCase):
    def estimate(self, rows, receipt):
        return estimate_preprocessing(rows, receipt, receipt)

    def assert_rejected(self, result, status="INVALID"):
        self.assertEqual(result.status, status)
        self.assertIsNone(result.contract)
        self.assertTrue(result.reasons)

    def test_exact_hand_calculated_population_statistics(self):
        rows, contract = fixture()
        result = self.estimate(rows, contract.receipt)
        self.assertEqual(result.status, "CONSISTENT")
        self.assertEqual(result.contract, contract)
        self.assertEqual(result.contract.lower, (0.,) * 8)
        self.assertEqual(result.contract.upper, (2.,) * 8)
        self.assertEqual(result.contract.mean, (1.,) * 8)
        self.assertEqual(result.contract.scale, (1.,) * 8)

    def test_fraction_reference_for_distinct_columns_and_population_variance(self):
        rows, receipt = varied_rows()
        result = self.estimate(rows, receipt)
        self.assertEqual(result.status, "CONSISTENT")
        for j in range(8):
            values = [Fraction(row.values[j]) for row in rows]
            mean = sum(values) / len(values)
            variance = sum((x - mean) ** 2 for x in values) / len(values)
            self.assertEqual(mean, 4 * j + 3)
            self.assertEqual(variance, 5 * (j + 1) ** 2)
            self.assertEqual(result.contract.mean[j], float(mean))
            self.assertEqual(result.contract.scale[j], math.sqrt(float(variance)))
            self.assertEqual(result.contract.lower[j], min(values))
            self.assertEqual(result.contract.upper[j], max(values))

    def test_public_validator_is_invoked_once_and_accepts_result(self):
        rows, contract = fixture()
        with patch.object(validation, "check_training_statistics",
                          wraps=validation.check_training_statistics) as check:
            result = self.estimate(rows, contract.receipt)
        self.assertEqual(check.call_count, 1)
        self.assertEqual(validation.check_training_statistics(
            rows, result.contract, contract.receipt).status, "CONSISTENT")

    def test_validator_failure_cannot_leave_a_usable_contract(self):
        rows, contract = fixture()
        failed = validation.TrainingStatisticsCheck("INVALID", ("SYNTHETIC_REJECTION",))
        with patch.object(validation, "check_training_statistics", return_value=failed):
            self.assert_rejected(self.estimate(rows, contract.receipt))

    def test_nine_feature_order_is_frozen(self):
        rows, contract = fixture()
        self.assertEqual(self.estimate(rows, contract.receipt).contract.feature_names, FEATURES)
        for names in (FEATURES[::-1], FEATURES[:-1], FEATURES + ("extra",), list(FEATURES), (None,) * 9):
            with self.subTest(names=names):
                self.assert_rejected(estimate_preprocessing(
                    rows, contract.receipt, contract.receipt, feature_names=names))

    def test_symbol_flag_passes_through_transform_without_scaling(self):
        rows, contract = fixture()
        result = self.estimate(rows, contract.receipt)
        for row in rows[:2]:
            transformed = validation.apply_transform(row, result.contract, contract.receipt)
            self.assertEqual(transformed.values[-1], int(row.symbol == "ETHUSDT"))
            self.assertEqual(len(transformed.values), 9)

    def test_wrong_symbol_and_flag_fail_closed(self):
        rows, contract = fixture()
        for symbol, flag in (("SOLUSDT", 0.), ("BTCUSDT", 1.), ("ETHUSDT", 0.)):
            row = replace(rows[0])
            object.__setattr__(row, "symbol", symbol)
            object.__setattr__(row, "values", row.values[:-1] + (flag,))
            self.assert_rejected(self.estimate((row,) + rows[1:], contract.receipt))

    def test_duplicate_missing_reversed_and_repeated_action_rows_rejected(self):
        rows, contract = fixture()
        for changed in (rows + rows[:1], rows[1:], rows[::-1], rows + rows):
            self.assert_rejected(self.estimate(changed, contract.receipt))

    def test_nonchronological_receipt_does_not_authorize_reordering(self):
        rows, contract = fixture()
        receipt = receipt_for(rows[::-1], contract.receipt.window)
        self.assert_rejected(self.estimate(rows[::-1], receipt))

    def test_wrong_fold_binding_rejected_before_arithmetic(self):
        rows, contract = fixture()
        other = replace(contract.receipt, window=replace(
            contract.receipt.window, evaluation_end=BASE + 1001 * HOUR))
        with patch.object(validation, "_population_statistics", side_effect=AssertionError("No arithmetic")):
            self.assert_rejected(estimate_preprocessing(rows, contract.receipt, other))

    def test_empty_and_999_rows_are_insufficient_before_arithmetic(self):
        rows, contract = fixture()
        fewer = rows[:-1]
        receipt = receipt_for(fewer, contract.receipt.window)
        with patch.object(validation, "_population_statistics", side_effect=AssertionError("No arithmetic")):
            self.assert_rejected(self.estimate((), receipt), "INSUFFICIENT")
            self.assert_rejected(self.estimate(fewer, receipt), "INSUFFICIENT")

    def test_exact_1000_and_per_symbol_minimum_boundaries(self):
        rows, contract = fixture(count=701)
        for eth_count, count, expected in ((299, 1000, "INSUFFICIENT"), (300, 1000, "CONSISTENT")):
            selected = tuple(row for row in rows if row.symbol == "BTCUSDT"
                             or row.decision_time < BASE + eth_count * HOUR)[:count]
            # Select exactly 700/300 or 701/299, not a fitting operation.
            receipt = receipt_for(selected, contract.receipt.window)
            self.assertEqual(len(selected), 1000)
            self.assertEqual(self.estimate(selected, receipt).status, expected)

    def test_exact_purge_buffer_boundary_is_accepted_next_hour_rejected(self):
        rows, contract = fixture()
        cutoff = contract.receipt.window.evaluation_start
        shifted = rows[:-2] + tuple(replace(row, decision_time=cutoff - 8 * HOUR - 1) for row in rows[-2:])
        receipt = receipt_for(shifted, contract.receipt.window)
        self.assertEqual(self.estimate(shifted, receipt).status, "CONSISTENT")
        for boundary in (cutoff - 7 * HOUR, cutoff - 3 * HOUR, cutoff):
            changed = shifted[:-2] + tuple(replace(row, decision_time=boundary - 1) for row in shifted[-2:])
            forged = replace(receipt)
            ids = tuple(row.row_id for row in changed)
            object.__setattr__(forged, "row_ids", ids)
            object.__setattr__(forged, "row_ids_sha256", validation.ids_hash(ids))
            with patch.object(validation, "_population_statistics", side_effect=AssertionError("No arithmetic")):
                self.assert_rejected(self.estimate(changed, forged))

    def test_future_row_injection_never_reaches_statistics(self):
        rows, contract = fixture()
        future = replace(rows[0], decision_time=contract.receipt.window.evaluation_start + HOUR - 1)
        with patch.object(validation, "_population_statistics", side_effect=AssertionError("No arithmetic")):
            self.assert_rejected(self.estimate(rows + (future,), contract.receipt))

    def test_future_perturbation_cannot_affect_training_estimate(self):
        rows, contract = fixture()
        before = self.estimate(rows, contract.receipt)
        future = replace(rows[0], decision_time=contract.receipt.window.evaluation_start + HOUR - 1)
        changed_future = replace(future, values=(1e100,) * 8 + (0.,))
        self.assertNotEqual(future.values, changed_future.values)
        with patch.object(validation, "_population_statistics", side_effect=AssertionError("No arithmetic")):
            for unknown_row in (future, changed_future):
                self.assert_rejected(self.estimate(rows + (unknown_row,), contract.receipt))
        self.assertEqual(before, self.estimate(rows, contract.receipt))
        import inspect
        self.assertEqual(tuple(inspect.signature(estimate_preprocessing).parameters),
                         ("rows", "receipt", "expected_training_receipt", "feature_names"))

    def test_constant_features_accept_equality_only(self):
        for value in (0., -3., 1e308, math.ulp(0.), 2 ** 60):
            rows, contract = fixture(constant=value)
            result = self.estimate(rows, contract.receipt)
            self.assertEqual(result.status, "CONSISTENT")
            self.assertEqual(result.contract.mean, (value,) * 8)
            self.assertEqual(result.contract.scale, (1.,) * 8)
            equal = validation.apply_transform(rows[0], result.contract, contract.receipt)
            self.assertEqual(equal.values, (0.,) * 9)
            moved = replace(rows[0], values=(math.nextafter(float(value), math.inf),) + rows[0].values[1:])
            self.assertEqual(validation.apply_transform(moved, result.contract, contract.receipt).status, "OUT_OF_RANGE")

    def test_pooled_bounds_include_both_symbols_and_equality(self):
        rows, contract = fixture()
        changed = tuple(replace(row, values=((10. if row.symbol == "ETHUSDT" else -2.),) * 8
                                + (row.values[-1],)) for row in rows)
        result = self.estimate(changed, contract.receipt)
        self.assertEqual(result.contract.lower, (-2.,) * 8)
        self.assertEqual(result.contract.upper, (10.,) * 8)
        self.assertEqual(result.contract.mean, (4.,) * 8)
        self.assertEqual(result.contract.scale, (6.,) * 8)
        for row in changed[:2]:
            self.assertEqual(validation.apply_transform(row, result.contract, contract.receipt).status, "IN_RANGE")

    def test_overflow_is_invalid_with_no_partial_contract(self):
        rows, contract = fixture()
        for values in ((1e308, -1e308), (1e308, 5e307)):
            changed = tuple(replace(row, values=(values[i % 2],) * 8 + (row.values[-1],)) for i, row in enumerate(rows))
            self.assert_rejected(self.estimate(changed, contract.receipt))

    def test_underflow_of_mean_and_all_squared_deviations_rejected(self):
        rows, contract = fixture()
        for numbers in ([math.ulp(0.)] + [0.] * 999, [1e-300, -1e-300] * 500):
            changed = tuple(replace(row, values=(numbers[i],) * 8 + (row.values[-1],)) for i, row in enumerate(rows))
            result = self.estimate(changed, contract.receipt)
            self.assert_rejected(result)
            self.assertEqual(result.reasons, ("NUMERIC_UNDERFLOW",))

    def test_partial_squared_deviation_underflow_rejected_by_both_interfaces(self):
        rows, contract = fixture()
        numbers = [1e-200, -1e-200] + [1., -1.] * 499
        changed = tuple(replace(row, values=(numbers[i],) * 8 + (row.values[-1],)) for i, row in enumerate(rows))
        self.assert_rejected(self.estimate(changed, contract.receipt))
        supplied = replace(contract, lower=(-1.,) * 8, upper=(1.,) * 8, mean=(0.,) * 8,
                           scale=(math.sqrt(998 / 1000),) * 8)
        checked = validation.check_training_statistics(changed, supplied, supplied.receipt)
        self.assertEqual(checked.status, "INVALID")
        self.assertEqual(checked.reasons, ("NUMERIC_UNDERFLOW",))

    def test_inexact_integer_precision_rejected_without_conversion_repair(self):
        rows, contract = fixture()
        for number in (2 ** 53 + 1, 10 ** 10000):
            row = replace(rows[0])
            object.__setattr__(row, "values", (number,) * 8 + (0.,))
            self.assert_rejected(self.estimate((row,) + rows[1:], contract.receipt))
        with self.assertRaises(ValueError):
            replace(contract, mean=(2 ** 53 + 1,) + contract.mean[1:])

    def test_unsupported_nonfinite_and_bool_vectors_are_not_repaired(self):
        rows, contract = fixture()
        for number in (math.nan, math.inf, -math.inf, True, Decimal("1"), Decimal("sNaN"), object()):
            row = replace(rows[0])
            object.__setattr__(row, "values", (number,) * 8 + (0.,))
            with localcontext() as context:
                context.clear_flags(); original = context.copy()
                self.assert_rejected(self.estimate((row,) + rows[1:], contract.receipt))
                self.assertEqual(context.flags, original.flags)

    def test_malformed_containers_receipts_and_rows_reject(self):
        rows, contract = fixture()
        for bad in (None, {}, (object(),), "rows", iter(rows)):
            self.assert_rejected(self.estimate(bad, contract.receipt))
        for receipt in (None, object(), "receipt"):
            self.assert_rejected(estimate_preprocessing(rows, receipt, contract.receipt))
        foreign = replace(rows[0], status="DATA_QUALITY", reason="MISSING", values=None, atr14=None)
        self.assert_rejected(self.estimate((foreign,) + rows[1:], contract.receipt))

    def test_stage_evidence_and_hash_claims_are_revalidated(self):
        rows, contract = fixture()
        for field, value in (("stage", "development_evaluation"), ("evidence", "HISTORICAL"),
                             ("row_ids_sha256", "a" * 64), ("window", None)):
            receipt = replace(contract.receipt)
            object.__setattr__(receipt, field, value)
            self.assert_rejected(self.estimate(rows, receipt))

    def test_foreign_window_schema_cannot_impersonate_synthetic_chronology(self):
        @dataclass(frozen=True)
        class ForeignWindow:
            train_start: int
            evaluation_start: int
            evaluation_end: int
            evidence: str = "HISTORICAL"

        rows, contract = fixture()
        window = contract.receipt.window
        fake = replace(contract.receipt, window=ForeignWindow(
            window.train_start, window.evaluation_start, window.evaluation_end))
        self.assert_rejected(self.estimate(rows, fake))
        self.assertEqual(validation.check_training_statistics(
            rows, replace(contract, receipt=fake), fake).status, "INVALID")

    def test_list_input_and_originals_remain_unchanged(self):
        rows, contract = fixture()
        source = list(rows)
        before = repr((source, contract.receipt))
        result = self.estimate(source, contract.receipt)
        self.assertEqual(repr((source, contract.receipt)), before)
        self.assertEqual(result, self.estimate(rows, contract.receipt))
        source.clear()
        object.__setattr__(rows[0], "values", (99.,) * 8 + (0.,))
        object.__setattr__(contract.receipt.window, "evaluation_start", BASE + HOUR)
        self.assertEqual(result.contract.mean, (1.,) * 8)
        self.assertEqual(result.contract.receipt.window.evaluation_start, BASE + 800 * HOUR)

    def test_changed_training_content_changes_statistics_not_external_data(self):
        rows, contract = fixture()
        original = self.estimate(rows, contract.receipt)
        changed = tuple(replace(row, values=tuple(x + 1 for x in row.values[:8])
                                + (row.values[-1],)) for row in rows)
        other = self.estimate(changed, contract.receipt)
        self.assertNotEqual(original.contract.mean, other.contract.mean)
        self.assertEqual(original.contract.receipt, other.contract.receipt)

    def test_deterministic_immutable_result_has_no_model_or_activation(self):
        rows, contract = fixture()
        first = self.estimate(rows, contract.receipt)
        self.assertEqual(first, self.estimate(rows, contract.receipt))
        self.assertEqual(first.evidence, "SYNTHETIC_ONLY")
        with self.assertRaises(FrozenInstanceError):
            first.contract = None
        with self.assertRaises(TypeError):
            bool(first)
        for name in ("fit", "predict", "activate", "model"):
            self.assertFalse(hasattr(first, name))

    def test_failed_or_insufficient_result_cannot_retain_payload(self):
        _, contract = fixture()
        for status in ("INVALID", "INSUFFICIENT"):
            with self.assertRaises(ValueError):
                PreprocessingEstimate(validation.TrainingStatisticsCheck(status, ("REJECTED",)), contract)
        with self.assertRaises(ValueError):
            PreprocessingEstimate(validation.TrainingStatisticsCheck("CONSISTENT"))


if __name__ == "__main__":
    unittest.main()
