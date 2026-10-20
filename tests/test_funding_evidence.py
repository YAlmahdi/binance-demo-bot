import copy
import ast
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from decimal import getcontext, localcontext, ROUND_DOWN
import unittest

from demo_futures.funding_evidence import (
    MAX_INTERVALS, MAX_RECORDS, MAX_RECORD_FIELDS, MAX_TIMESTAMP, UTC_UNIX_MILLISECONDS,
    utc_milliseconds, validate_funding_evidence,
)


def record(timestamp=1000, **fields):
    return dict(symbol="BTCUSDT", fundingTime=timestamp,
                fundingRate=".001", markPrice="100", **fields)


def review(rows, intervals=(("one", 0, 2000),), **kwargs):
    return validate_funding_evidence(rows, intervals, symbol="BTCUSDT",
                                    timestamp_unit=kwargs.get("unit", UTC_UNIX_MILLISECONDS))


class FundingEvidenceTests(unittest.TestCase):
    def test_nonstring_dictionary_keys_reject_before_lookup_hooks(self):
        class ForeignKey:
            def __hash__(self):
                return hash("symbol")

            def __eq__(self, other):
                raise AssertionError("caller-defined comparison during record lookup")

        with self.assertRaises(ValueError):
            review([{ForeignKey(): "untrusted"}])

    def test_event_identity_reuse_across_timestamps_is_visible(self):
        rows = [dict(record(1000), eventId="same-id"),
                dict(record(2000), eventId="same-id")]
        result = review(rows)
        self.assertEqual([g.timestamp for g in result.groups], [1000, 2000])
        self.assertEqual(result.intervals[0].timestamps, (1000, 2000))
        self.assertEqual([(issue.code, issue.source_indices) for issue in result.issues],
                         [("REUSED_EVENT_ID", (0, 1))])
        self.assertEqual(result.completeness, "NOT_VERIFIED")

    def test_record_field_limit_is_explicit_and_checked_before_lookups(self):
        row = record()
        row.update({f"metadata-{i}": None for i in range(MAX_RECORD_FIELDS - len(row))})
        self.assertEqual(len(row), MAX_RECORD_FIELDS)
        self.assertEqual(len(review([row]).groups), 1)
        row["one-too-many"] = None
        with self.assertRaises(ValueError): review([row])

    def test_reused_ids_preserve_type_and_all_source_indices(self):
        rows = [dict(record(1000), eventId=1), dict(record(1000), eventId=1),
                dict(record(2000), eventId=1), dict(record(2000), eventId="1")]
        output = review(rows)
        reused = [i for i in output.issues if i.code == "REUSED_EVENT_ID"]
        self.assertEqual(reused[0].source_indices, (0, 1, 2))
        self.assertEqual(len(reused), 1)
        self.assertEqual([len(g.observations) for g in output.groups], [2, 2])
        self.assertEqual(output, review(rows))
        # Separate interval identities remain separate references, not liabilities.
        output = review(rows, (("position-a", 0, 2000), ("position-b", 0, 2000)))
        self.assertEqual([i.interval_id for i in output.intervals], ["position-a", "position-b"])

    def test_same_timestamp_duplicate_id_is_not_cross_time_reuse(self):
        output = review([dict(record(), eventId="one"), dict(record(), eventId="one")])
        self.assertEqual([i.code for i in output.issues], ["DUPLICATE_EVENT"])

    def test_extreme_finite_decimal_strings_do_not_use_ambient_precision(self):
        for rate in ("-1e-9999", "1e9999", "-0.000", "1" * 128):
            with self.subTest(rate=rate), localcontext() as ctx:
                ctx.prec, ctx.rounding = 1, ROUND_DOWN
                ctx.Emin, ctx.Emax = -9, 9
                for signal in ctx.traps:
                    ctx.traps[signal] = True
                ctx.clear_flags()
                row = record(); row["fundingRate"] = rate
                output = review([row, row.copy()])
                self.assertEqual(output.groups[0].observations[0].funding_rate, rate)
                self.assertFalse(output.groups[0].conflicting)
                self.assertFalse(any(ctx.flags.values()))

    def test_fixed_labels_cannot_be_upgraded_through_public_construction(self):
        output = review([record()])
        for field, value in (("authority", "AUTHENTICATED"), ("completeness", "COMPLETE")):
            with self.assertRaises(FrozenInstanceError): setattr(output, field, value)
            with self.assertRaises(ValueError): replace(output, **{field: value})
        self.assertFalse(hasattr(output, "approved"))
        self.assertFalse(hasattr(output, "order"))

    def test_static_dependency_boundary_excludes_financial_and_io_calls(self):
        source = Path(__file__).resolve().parents[1] / "src/demo_futures/funding_evidence.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        imports.update(alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
                       for alias in node.names)
        self.assertEqual(imports, {"dataclasses", "datetime", "decimal", "re"})
        forbidden = {"open", "read_text", "read_bytes", "write_text", "write_bytes", "connect",
                     "request", "fit", "predict", "size_position", "assess_plan_budget", "run"}
        calls = {node.func.id if isinstance(node.func, ast.Name) else node.func.attr
                 for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, (ast.Name, ast.Attribute))}
        self.assertFalse(calls & forbidden)

    def test_fresh_import_has_no_external_or_project_integration_side_effects(self):
        root = Path(__file__).resolve().parents[1] / "src"
        code = "\n".join([
            "import sys, dataclasses, datetime, decimal, re, importlib.util",
            f"sys.path.insert(0, {str(root)!r})",
            f"allowed_sources = [{str(root / 'demo_futures/__init__.py')!r}, "
            f"{str(root / 'demo_futures/funding_evidence.py')!r}]",
            "allowed = set(allowed_sources + [importlib.util.cache_from_source(p) for p in allowed_sources])",
            "def guard(event, args):",
            "    if event.startswith(('socket.', 'subprocess.', 'sqlite3.')) or event == 'os.system':",
            "        raise AssertionError('external operation during import')",
            "    if event == 'open' and args[0] not in allowed:",
            "        raise AssertionError('unexpected file access during import')",
            "sys.addaudithook(guard)",
            "import demo_futures.funding_evidence",
            "assert {n for n in sys.modules if n.startswith('demo_futures')} == "
            "{'demo_futures', 'demo_futures.funding_evidence'}",
        ])
        result = subprocess.run([sys.executable, "-I", "-B", "-c", code],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_utc_conversion_uses_exact_milliseconds(self):
        value = datetime(2000, 1, 1, 0, 0, 0, 123000, tzinfo=timezone.utc)
        self.assertEqual(utc_milliseconds(value), 946684800123)
        self.assertEqual(utc_milliseconds(datetime(1970, 1, 1, tzinfo=timezone.utc)), 0)

    def test_ambiguous_dates_and_submillisecond_precision_reject(self):
        for value in (datetime(2000, 1, 1), datetime(2000, 1, 1, tzinfo=timezone(timedelta(hours=1))),
                      datetime(2000, 1, 1, microsecond=1, tzinfo=timezone.utc),
                      datetime(1969, 1, 1, tzinfo=timezone.utc), "2000-01-01Z"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                utc_milliseconds(value)

    def test_exact_entry_and_exit_boundaries(self):
        result = review([record(t) for t in (999, 1000, 1001, 2000, 2001)], (("one", 1000, 2000),))
        self.assertEqual(result.intervals[0].timestamps, (1001, 2000))

    def test_overlap_references_one_unique_group(self):
        result = review([record()], (("a", 0, 1000), ("b", 999, 2000)))
        self.assertEqual(len(result.groups), 1)
        self.assertEqual([i.timestamps for i in result.intervals], [(1000,), (1000,)])

    def test_identical_duplicates_are_preserved_and_diagnosed(self):
        result = review([record(), record()])
        self.assertEqual(result.issues[0].code, "DUPLICATE_EVENT")
        self.assertEqual(result.groups[0].source_indices, (0, 1))
        self.assertEqual(len(result.groups[0].observations), 2)
        self.assertEqual(result.intervals[0].timestamps, (1000,))

    def test_equal_numeric_encodings_preserve_original_strings(self):
        second = record(); second["fundingRate"] = "0.0010"
        result = review([record(), second])
        self.assertFalse(result.groups[0].conflicting)
        self.assertEqual(result.groups[0].observations[1].funding_rate, "0.0010")

    def test_conflicts_retain_all_alternatives(self):
        for field, value in (("fundingRate", "-.001"), ("markPrice", "101"),
                             ("rateType", "changed"), ("eventId", "revision")):
            other = record(); other[field] = value
            with self.subTest(field=field):
                result = review([record(), other])
                self.assertTrue(result.groups[0].conflicting)
                self.assertEqual(result.issues[-1].code, "CONFLICTING_EVENT")
                self.assertEqual(len(result.groups[0].observations), 2)

    def test_missing_marks_have_no_price_fallback(self):
        for value in (None, "", "omitted"):
            item = record()
            if value == "omitted": del item["markPrice"]
            else: item["markPrice"] = value
            with self.subTest(value=value):
                result = review([item])
                self.assertIsNone(result.groups[0].observations[0].mark_price)
                self.assertEqual(result.issues[0].code, "MISSING_MARK")

    def test_missing_or_invalid_rates_reject(self):
        for value in (None, "", "NaN", "Infinity", True, 0.001, "1_0", " 0.1", "1e10000"):
            item = record(); item["fundingRate"] = value
            with self.subTest(value=value), self.assertRaises(ValueError): review([item])
        item = record(); del item["fundingRate"]
        with self.assertRaises(ValueError): review([item])

    def test_invalid_mark_prices_reject(self):
        for value in ("0", "-1", "NaN", 100, True, " " ):
            item = record(); item["markPrice"] = value
            with self.subTest(value=value), self.assertRaises(ValueError): review([item])

    def test_timestamp_types_and_bounds_reject(self):
        for value in (True, "1000", 1000.0, -1, None, MAX_TIMESTAMP + 1):
            with self.subTest(value=value), self.assertRaises(ValueError): review([record(value)])

    def test_ambiguous_contracts_reject_without_unit_guessing(self):
        for unit in (None, "seconds", "milliseconds", True):
            with self.subTest(unit=unit), self.assertRaises(ValueError): review([], unit=unit)

    def test_order_anomalies_are_visible_even_with_sorted_output(self):
        result = review([record(2000), record(1000)])
        self.assertEqual([g.timestamp for g in result.groups], [1000, 2000])
        self.assertEqual(result.issues[0].code, "OUT_OF_ORDER")
        self.assertEqual(result.issues[0].source_indices, (0, 1))

    def test_empty_observations_never_claim_complete_history(self):
        result = review([])
        self.assertEqual(result.intervals[0].timestamps, ())
        self.assertEqual(result.completeness, "NOT_VERIFIED")
        self.assertEqual(result.authority, "LOCAL_OBSERVATIONS_ONLY")

    def test_deterministic_and_does_not_mutate_inputs_or_decimal_context(self):
        rows = [record(2000), record(1000), record(1000)]
        intervals = [["one", 0, 2000]]
        original = copy.deepcopy((rows, intervals))
        ctx = getcontext().copy()
        first = review(rows, intervals)
        self.assertEqual(first, review(rows, intervals))
        self.assertEqual((rows, intervals), original)
        self.assertEqual(getcontext().flags, ctx.flags)
        self.assertEqual(getcontext().prec, ctx.prec)
        rows[0]["fundingRate"] = "9"
        self.assertEqual(first.groups[1].observations[0].funding_rate, ".001")

    def test_interval_shape_ids_and_order_reject(self):
        for intervals in ((("x", 1, 1),), (("x", 2, 1),), (("x", False, 1),),
                          (("x", 0, 1), ("x", 1, 2)), (("", 0, 1),), (("x", 0),)):
            with self.subTest(intervals=intervals), self.assertRaises(ValueError): review([], intervals)

    def test_schema_scope_and_bounded_input_reject(self):
        wrong = record(); wrong["symbol"] = "ETHUSDT"
        for rows in ([wrong], [None], [dict(record(), symbol=True)], [record()] * (MAX_RECORDS + 1)):
            with self.assertRaises(ValueError): review(rows)
        with self.assertRaises(ValueError): review([], [(str(i), 0, 1) for i in range(MAX_INTERVALS + 1)])
        with self.assertRaises(ValueError): review(iter([]))

    def test_optional_ids_and_rate_types_are_bounded(self):
        for field, values in (("eventId", (True, -1, 2**64, [], "")), ("rateType", ([], True, ""))):
            for value in values:
                item = record(); item[field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError): review([item])
        result = review([dict(record(), eventId="synthetic-id", rateType="Regular")])
        self.assertEqual(result.groups[0].observations[0].event_id, "synthetic-id")

    def test_validation_performs_no_io(self):
        active = [True]

        def guard(event, args):
            if active[0] and (event == "open" or event.startswith(("socket.", "subprocess.", "sqlite3."))):
                raise AssertionError("unexpected I/O during pure validation")

        sys.addaudithook(guard)
        try:
            result = review([record(1000), record(1000), record(2000)])
            self.assertEqual(len(result.groups), 2)
        finally:
            active[0] = False

    def test_plain_containers_and_numeric_string_limits(self):
        class CustomDict(dict):
            pass

        class CustomInt(int):
            pass

        for rows in ([CustomDict(record())], [record(CustomInt(1000))],
                     [dict(record(), fundingRate="1" * 129)]):
            with self.assertRaises(ValueError): review(rows)
        result = review([record(0), record(MAX_TIMESTAMP)], ())
        self.assertEqual(result.intervals, ())
        self.assertEqual(len(result.groups), 2)


if __name__ == "__main__":
    unittest.main()
