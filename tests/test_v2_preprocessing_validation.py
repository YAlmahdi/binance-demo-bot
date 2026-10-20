"""Invented feature vectors only; no labels, model fits or simulator calls."""
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal, localcontext
import math
import unittest

from demo_futures.research_v2.config import FEATURES, HOUR, HORIZON, SYMBOLS
from demo_futures.research_v2.features import FeatureRow
from demo_futures.research_v2.validation import (
    DevelopmentWindow, TrainingReceipt, TransformContract, apply_transform,
    ids_hash,
)

BASE = 1262304000000  # Invented 2010 fixture, never historical market data.


def fixture(count=500, constant=None):
    window = DevelopmentWindow(BASE, BASE + 800 * HOUR, BASE + 1000 * HOUR)
    rows = tuple(
        FeatureRow(symbol, BASE + i * HOUR - 1, "READY", "SYNTHETIC_FIXTURE",
                   ((float(2 * (i % 2)) if constant is None else constant),) * 8
                   + (float(symbol == "ETHUSDT"),), 1.)
        for i in range(1, count + 1) for symbol in SYMBOLS
    )
    identities = tuple(row.row_id for row in rows)
    receipt = TrainingReceipt(identities, ids_hash(identities), window)
    lower, upper, mean = (0., 2., 1.) if constant is None else (constant,) * 3
    contract = TransformContract(receipt, (lower,) * 8, (upper,) * 8,
                                 (mean,) * 8, (1.,) * 8)
    return rows, contract


class ConstantContractTests(unittest.TestCase):
    def test_constant_requires_unit_scale(self):
        _, contract = fixture(constant=3.)
        with self.assertRaises(ValueError):
            replace(contract, scale=(2.,) * 8)

    def test_exact_constant_accepts_only_equality_and_preserves_flag(self):
        rows, contract = fixture(constant=3.)
        for row in rows[:2]:
            result = apply_transform(row, contract, contract.receipt)
            self.assertEqual(result.values, (0.,) * 8 + (row.values[-1],))
            changed = replace(row, values=(math.nextafter(3., math.inf),) + row.values[1:])
            abstention = apply_transform(changed, contract, contract.receipt)
            self.assertEqual(abstention.status, "OUT_OF_RANGE")
            self.assertIsNone(abstention.values)


class TrainingStatisticsTests(unittest.TestCase):
    def check(self, rows, contract, receipt=None):
        from demo_futures.research_v2.validation import check_training_statistics
        return check_training_statistics(rows, contract, receipt or contract.receipt)

    def test_population_statistics_and_determinism(self):
        rows, contract = fixture()
        first = self.check(rows, contract)
        self.assertEqual(first.status, "CONSISTENT")
        self.assertEqual(first.reasons, ())
        self.assertEqual(first, self.check(rows, contract))
        self.assertEqual(first.evidence, "SYNTHETIC_ONLY")
        self.assertEqual(first.authority, "INERT_VALIDATION_ONLY")
        with self.assertRaises(TypeError):
            bool(first)
        with self.assertRaises(FrozenInstanceError):
            first.status = "INVALID"

    def test_sample_standard_deviation_is_not_population(self):
        rows, contract = fixture()
        result = self.check(rows, replace(contract, scale=(math.sqrt(1000 / 999),) * 8))
        self.assertEqual(result.status, "INVALID")
        self.assertIn("log_return_1:STATISTICS_MISMATCH", result.reasons)

    def test_each_continuous_feature_metadata_is_checked(self):
        rows, contract = fixture()
        for name, value in (("lower", -1.), ("upper", 3.), ("mean", .5), ("scale", 2.)):
            for i in range(8):
                values = list(getattr(contract, name)); values[i] = value
                with self.subTest(field=name, feature=FEATURES[i]):
                    result = self.check(rows, replace(contract, **{name: values}))
                    self.assertEqual(result.reasons, (FEATURES[i] + ":STATISTICS_MISMATCH",))

    def test_exact_constants_including_large_and_negative_values(self):
        for value in (0., -3., 1e308):
            rows, contract = fixture(constant=value)
            with self.subTest(value=value):
                self.assertEqual(self.check(rows, contract).status, "CONSISTENT")

    def test_empty_and_insufficient_training_never_get_fallback(self):
        rows, contract = fixture(count=499)
        self.assertEqual(self.check(rows, contract).status, "INSUFFICIENT")
        self.assertEqual(self.check((), contract).status, "INSUFFICIENT")

    def test_per_symbol_minimum_is_preserved(self):
        rows, contract = fixture(count=701)
        rows = tuple(r for r in rows if r.symbol == "BTCUSDT" or r.decision_time < BASE + 299 * HOUR)
        identities = tuple(r.row_id for r in rows)
        receipt = replace(contract.receipt, row_ids=identities, row_ids_sha256=ids_hash(identities))
        self.assertEqual(len(rows), 1000)
        self.assertEqual(self.check(rows, replace(contract, receipt=receipt)).status, "INSUFFICIENT")

    def test_duplicate_missing_and_reordered_training_rows_reject(self):
        rows, contract = fixture()
        for changed in (rows + rows[:1], rows[1:], rows[::-1]):
            with self.subTest():
                self.assertEqual(self.check(changed, contract).status, "INVALID")

    def test_changed_value_with_same_id_is_detected(self):
        rows, contract = fixture()
        changed = (replace(rows[0], values=(1.,) + rows[0].values[1:]),) + rows[1:]
        self.assertEqual(self.check(changed, contract).status, "INVALID")

    def test_wrong_fold_receipt_rejects(self):
        rows, contract = fixture()
        other = replace(contract.receipt, window=replace(contract.receipt.window,
                                                       evaluation_end=BASE + 1001 * HOUR))
        self.assertEqual(self.check(rows, contract, other).status, "INVALID")

    def test_evaluation_rows_cannot_influence_training_validation(self):
        rows, contract = fixture()
        evaluation = replace(rows[0], decision_time=contract.receipt.window.evaluation_start + HOUR - 1,
                             values=(1e100,) * 8 + (0.,))
        self.assertEqual(self.check(rows + (evaluation,), contract).status, "INVALID")
        self.assertEqual(self.check(rows, contract).status, "CONSISTENT")

    def test_purged_and_buffer_rows_cannot_be_declared_training(self):
        _, contract = fixture()
        cutoff = contract.receipt.window.evaluation_start
        for boundary in (cutoff - 4 * HOUR, cutoff - 7 * HOUR):
            identity = f"BTCUSDT:{boundary - 1}"
            with self.assertRaises(ValueError):
                replace(contract.receipt, row_ids=(identity,), row_ids_sha256=ids_hash((identity,)))

    def test_invalid_admitted_row_is_not_silently_dropped(self):
        rows, contract = fixture()
        excluded = replace(rows[0], status="DATA_QUALITY", reason="MISSING", values=None, atr14=None)
        self.assertEqual(self.check((excluded,) + rows[1:], contract).status, "INVALID")

    def test_overflow_and_underflow_fail_without_repair(self):
        rows, contract = fixture()
        for magnitude in (1e308, 1e-300):
            changed = tuple(replace(r, values=((magnitude if i % 4 < 2 else -magnitude),) * 8
                                   + (r.values[-1],)) for i, r in enumerate(rows))
            candidate = replace(contract, lower=(-magnitude,) * 8, upper=(magnitude,) * 8,
                                mean=(0.,) * 8, scale=(magnitude,) * 8)
            with self.subTest(magnitude=magnitude):
                self.assertEqual(self.check(changed, candidate).status, "INVALID")

    def test_nonfinite_bool_and_schema_fail_closed(self):
        rows, contract = fixture()
        for value in (float("nan"), float("inf"), True):
            with self.assertRaises(ValueError):
                replace(contract, mean=(value,) + contract.mean[1:])
        with self.assertRaises(ValueError):
            replace(contract, feature_names=FEATURES[::-1])
        for bad in (None, {}, (object(),)):
            with self.subTest(value=type(bad).__name__):
                self.assertEqual(self.check(bad, contract).status, "INVALID")

    def test_future_dependent_labels_are_not_an_input(self):
        import inspect
        from demo_futures.research_v2.validation import check_training_statistics
        self.assertEqual(tuple(inspect.signature(check_training_statistics).parameters),
                         ("rows", "contract", "expected_training_receipt"))

    def test_no_input_mutation_or_statistics_emission(self):
        rows, contract = fixture()
        source = list(rows)
        snapshot = tuple(source), repr(contract)
        result = self.check(source, contract)
        self.assertEqual((tuple(source), repr(contract)), snapshot)
        self.assertFalse(hasattr(result, "mean"))
        self.assertFalse(hasattr(result, "scale"))

    def test_feature_columns_remain_distinct(self):
        rows, contract = fixture()
        rows = tuple(replace(r, values=tuple(r.values[j] * (j + 1) + j for j in range(8))
                             + (r.values[-1],)) for r in rows)
        contract = replace(contract, lower=tuple(float(j) for j in range(8)),
                           upper=tuple(float(3 * j + 2) for j in range(8)),
                           mean=tuple(float(2 * j + 1) for j in range(8)),
                           scale=tuple(float(j + 1) for j in range(8)))
        self.assertEqual(self.check(rows, contract).status, "CONSISTENT")

    def test_receipt_type_required_at_contract_boundary(self):
        _, contract = fixture()
        with self.assertRaises(ValueError):
            replace(contract, receipt=None)

    def test_tampered_frozen_row_is_revalidated(self):
        rows, contract = fixture()
        for values in ((True,) + rows[0].values[1:], (math.nan,) + rows[0].values[1:],
                       rows[0].values[:-1] + (1.,)):
            row = replace(rows[0])
            object.__setattr__(row, "values", values)
            self.assertEqual(self.check((row,) + rows[1:], contract).status, "INVALID")

    def test_row_lists_are_captured_without_aliasing(self):
        rows, contract = fixture()
        source = list(rows)
        result = self.check(source, contract)
        source.clear()
        self.assertEqual(result.status, "CONSISTENT")
        self.assertEqual(self.check(rows, contract), result)

    def test_decimal_metadata_cannot_pass_then_fail_float_transform(self):
        _, contract = fixture(constant=3.)
        for name in ("lower", "upper", "mean", "scale"):
            values = tuple(Decimal(str(value)) for value in getattr(contract, name))
            with self.subTest(field=name), self.assertRaises(ValueError):
                replace(contract, **{name: values})

    def test_decimal_feature_rows_reject_without_conversion_or_context_changes(self):
        rows, contract = fixture(constant=3.)
        for value in (Decimal('3'), Decimal('sNaN')):
            row = replace(rows[0])
            object.__setattr__(row, 'values', (value,) * 8 + (0.,))
            with self.subTest(value=str(value)), localcontext() as context:
                context.clear_flags()
                original = context.copy()
                self.assertEqual(self.check((row,) + rows[1:], contract).status, 'INVALID')
                self.assertEqual(apply_transform(row, contract, contract.receipt).status, 'DATA_QUALITY')
                self.assertEqual(context.flags, original.flags)
                self.assertEqual(context.prec, original.prec)
                self.assertEqual(context.rounding, original.rounding)

    def test_foreign_numeric_hooks_are_not_executed(self):
        class Foreign:
            def __float__(self):
                raise AssertionError('Must not coerce foreign numeric objects')

        rows, contract = fixture()
        with self.assertRaises(ValueError):
            replace(contract, mean=(Foreign(),) + contract.mean[1:])
        row = replace(rows[0])
        object.__setattr__(row, 'values', (Foreign(),) + row.values[1:])
        self.assertEqual(self.check((row,) + rows[1:], contract).status, 'INVALID')
        self.assertEqual(apply_transform(row, contract, contract.receipt).status, 'DATA_QUALITY')

    def test_oversized_integer_metadata_is_rejected_without_overflow_escape(self):
        _, contract = fixture()
        with self.assertRaises(ValueError):
            replace(contract, mean=(10 ** 10000,) + contract.mean[1:])

    def test_integer_and_float_vectors_have_same_supported_arithmetic(self):
        rows, contract = fixture()
        rows = tuple(replace(row, values=tuple(int(x) for x in row.values)) for row in rows)
        self.assertEqual(self.check(rows, contract).status, 'CONSISTENT')
        self.assertEqual(apply_transform(rows[0], contract, contract.receipt).status, 'IN_RANGE')

    def test_malformed_frozen_records_fail_closed(self):
        rows, contract = fixture()
        deleted = replace(contract)
        object.__delattr__(deleted, 'receipt')
        from demo_futures.research_v2.validation import check_training_statistics
        self.assertEqual(check_training_statistics(rows, deleted, contract.receipt).status, 'INVALID')


if __name__ == "__main__":
    unittest.main()
