"""Fixed declarations only. No SQL execution, fixtures or saved observations."""
from dataclasses import FrozenInstanceError, replace
import ast
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from demo_futures.research_v2.authorization_binding import validate_authorization
from demo_futures.research_v2.fixed_query_plan import (
    QueryPlanRequest, QueryPlanDiagnostics, PLAN_REASONS, build_query_plan, validate_query_plan,
)
from demo_futures.research_v2.contracts import Readiness
from demo_futures.research_v2.config import STEP
from demo_futures.research_v2.source_contracts import AvailabilityMode, PROJECTION, TARGET_START, TARGET_END, PROTECTED
from demo_futures.research_v2.funding_contracts import CoverageState, FundingClaim, assess_funding
from demo_futures.research_v2 import sqlite_fixture_contract as fixture
from test_v2_authorization_binding import inputs, NOW


class QueryPlanTests(unittest.TestCase):
    def setUp(self):
        self.record, self.spec, self.manifest = inputs()
        self.request = QueryPlanRequest(1024)

    def build(self, **changes):
        values = dict(record=self.record, spec=self.spec, manifest=self.manifest,
                      request=self.request, evaluated_at=NOW)
        values.update(changes)
        return build_query_plan(**values)

    def check(self, reason, **changes):
        d = self.build(**changes)
        self.assertNotEqual(d.status, Readiness.SUFFICIENT)
        self.assertIn(reason, d.reasons)
        self.assertIsNone(d.sql)
        self.assertEqual((d.parameters, d.declared_bounds, d.expected_rows), ((), (), 0))
        self.assertEqual(d.reasons, tuple(r for r in PLAN_REASONS if r in d.reasons))
        return d

    def test_valid_fixed_sql_projection_and_parameters(self):
        d = self.build()
        self.assertEqual(d.status, Readiness.SUFFICIENT)
        self.assertEqual(d.sql, "SELECT " + ",".join(PROJECTION) +
            " FROM main.fixture_candles INDEXED BY fixture_scope WHERE symbol=?"
            " AND interval=? AND open_time>=? AND open_time<? AND close_time>=? AND close_time<?"
            " ORDER BY symbol,ordinal LIMIT ?")
        self.assertEqual(d.parameters, tuple((s, "5m", self.spec.context_start,
            self.spec.context_end, self.spec.context_start, self.spec.context_end, 288)
            for s in ("BTCUSDT", "ETHUSDT")))
        self.assertEqual(d.expected_rows, 574)
        self.assertEqual(d.actual_authorization, "NOT VERIFIED")
        self.assertEqual(d.authority, "INERT_SQL_DECLARATION_ONLY")
        self.assertEqual(d.risk_clearance, "NOT CLEARED")

    def test_one_symbol_plan_uses_same_fixed_sql(self):
        r, s, m = self.record, self.spec, self.manifest
        for symbol, digest in self.manifest.scoped_sha256:
            hashes = ((symbol, digest),)
            r1 = replace(r, symbols=(symbol,), scoped_sha256=hashes)
            s1 = replace(s, symbols=(symbol,), expected_scoped_sha256=hashes)
            m1 = replace(m, symbols=(symbol,), scoped_sha256=hashes)
            d = self.build(record=r1, spec=s1, manifest=m1)
            self.assertEqual(d.status, Readiness.SUFFICIENT)
            self.assertEqual(d.sql, self.build().sql)
            self.assertEqual(d.parameters[0][:2], (symbol, "5m"))
            self.assertEqual(len(d.parameters), 1)
            self.assertEqual(d.expected_rows, 287)

    def test_explicit_prefix_decisions_and_horizon_binding(self):
        d = self.build()
        self.assertEqual(d.declared_bounds, (self.spec.context_start, self.spec.context_end,
            self.spec.prefix_start, self.spec.prefix_end, self.spec.start, self.spec.end,
            self.spec.horizon_end, self.spec.decision_time))

    def test_read_only_declarations_no_handle_or_execution(self):
        d = self.build()
        for name in ("execute", "connection", "cursor", "path", "rows", "read", "activate"):
            self.assertFalse(hasattr(d, name))
        with self.assertRaises(TypeError):
            bool(d)
        with self.assertRaises((FrozenInstanceError, TypeError, AttributeError)):
            d.sql = "DELETE"

    def test_missing_approval_emits_no_plan(self):
        self.check("APPROVAL_MISSING", record=None)

    def test_expired_revoked_or_unknown_approval_emits_no_plan(self):
        self.check("APPROVAL_EXPIRED", evaluated_at=self.record.expires_at)
        self.check("APPROVAL_REVOKED", record=replace(self.record, revoked=True, revocation_ref="invented"))
        self.check("APPROVAL_UNVERIFIED", record=replace(self.record, ledger_basis="UNKNOWN"))

    def test_no_cached_authorization_result_accepted(self):
        checked = validate_authorization(self.record, self.spec, self.manifest, evaluated_at=NOW)
        self.check("INVALID_SCHEMA_OR_TIME", record=checked)

    def test_dynamic_identifiers_and_injection_refused(self):
        for field in ("schema", "table"):
            for value in ("external", "sqlite_schema", "fixture_candles; DROP TABLE x", "../database", '"fixture_candles"'):
                self.check("QUERY_SCHEMA_MISMATCH", request=replace(self.request, **{field: value}))

    def test_storage_schema_and_version_drift(self):
        for change in ({"schema_id": "other"}, {"schema_version": 2}):
            self.check("QUERY_SCHEMA_MISMATCH", request=replace(self.request, **change))

    def test_projection_escalation(self):
        for projection in ((), ("*",), PROJECTION + ("available_at",), PROJECTION[::-1]):
            self.check("QUERY_PROJECTION_MISMATCH", request=replace(self.request, projection=projection))

    def test_ordering_escalation(self):
        for order in (("open_time",), ("ordinal", "symbol"), ("random()",), ()):
            self.check("QUERY_ORDER_MISMATCH", request=replace(self.request, order_by=order))

    def test_resource_request_bounds(self):
        for n in (-1, 0, 4097, 1025):
            self.check("QUERY_RESOURCE_LIMIT", request=replace(self.request, max_rows=n))

    def test_complete_declared_context_not_silently_truncated(self):
        self.check("QUERY_RESOURCE_LIMIT", request=replace(self.request, max_rows=573))
        d = self.build(request=replace(self.request, max_rows=574))
        self.assertEqual(d.status, Readiness.SUFFICIENT)
        self.assertEqual(tuple(row[-1] for row in d.parameters), (288, 288))

    def test_existing_fixture_cap_unchanged(self):
        self.assertEqual(fixture.MAX_ROWS, 4096)
        d = self.build(record=replace(self.record, max_rows=4096), request=QueryPlanRequest(4096))
        self.assertTrue(all(row[-1] <= fixture.MAX_ROWS + 1 for row in d.parameters))
        self.assertEqual(d.expected_rows, 574)

    def test_overlarge_scope_not_paginated_or_repaired(self):
        end = self.spec.context_start + 4097 * STEP
        changes = dict(context_end=end, horizon_end=end)
        m = replace(self.manifest, **changes, retrieved_at=end + STEP)
        self.check("QUERY_RESOURCE_LIMIT", record=replace(self.record, **changes),
                   spec=replace(self.spec, **changes), manifest=m)

    def test_strict_interior_edges_preserved_separately(self):
        for changes in (dict(context_start=TARGET_START, prefix_start=TARGET_START),
                        dict(context_end=TARGET_END, horizon_end=TARGET_END)):
            m = replace(self.manifest, **changes, retrieved_at=TARGET_END + STEP)
            self.check("UNAUTHORIZED_DATES", record=replace(self.record, **changes),
                       spec=replace(self.spec, **changes), manifest=m)

    def test_both_protected_periods(self):
        for start, end in PROTECTED:
            self.check("PROTECTED_PERIOD", spec=replace(self.spec, start=start, end=end))

    def test_prefix_and_horizon_escape(self):
        self.check("UNAUTHORIZED_DATES", spec=replace(self.spec, prefix_start=TARGET_START - STEP))
        self.check("PROTECTED_PERIOD", spec=replace(self.spec, horizon_end=TARGET_END + STEP))

    def test_invalid_symbols_and_intervals(self):
        for symbol in ("SOLUSDT", "BNBUSDT", "XRPUSDT"):
            self.check("WRONG_SYMBOL", spec=replace(self.spec, symbols=(symbol,)))
        self.check("WRONG_INTERVAL", spec=replace(self.spec, interval="15m"))

    def test_mutable_and_foreign_requests_refused(self):
        for v in (Mock(), {}, object(), lambda: None):
            self.check("INVALID_SCHEMA_OR_TIME", request=v)
        for change in ({"projection": list(PROJECTION)}, {"order_by": ["symbol", "ordinal"]},
                       {"max_rows": True}, {"table": Mock()}):
            with self.assertRaises(ValueError):
                replace(self.request, **change)

    def test_tampered_request_revalidated(self):
        object.__setattr__(self.request, "max_rows", Mock())
        self.check("INVALID_SCHEMA_OR_TIME")

    def test_query_content_rechecked_against_raw_binding(self):
        d = self.build()
        checked = validate_query_plan(d, self.record, self.spec, self.manifest, self.request, evaluated_at=NOW)
        self.assertEqual(checked, d)
        self.assertIsNot(checked, d)

    def test_altered_sql_refused(self):
        d = self.build()
        for sql in ("DELETE FROM fixture_candles", d.sql.replace("open_time<?", "1=1"),
                    d.sql + "; ATTACH DATABASE 'invented' AS external"):
            bad = replace(d)
            object.__setattr__(bad, "sql", sql)
            checked = validate_query_plan(bad, self.record, self.spec, self.manifest, self.request, evaluated_at=NOW)
            self.assertIn("QUERY_CONTENT_MISMATCH", checked.reasons)
            self.assertIsNone(checked.sql)

    def test_malformed_or_escalated_parameters_refused(self):
        d = self.build()
        first, second = d.parameters
        for parameters in ((), list(d.parameters), (first[:-1] + (999999,), second),
                           (("XRPUSDT",) + first[1:], second),
                           (first[:2] + (TARGET_START - STEP,) + first[3:], second),
                           (first[:-1] + (True,), second), (first[:-1] + (Mock(),), second),
                           (first, first), (first,), d.parameters[::-1]):
            bad = replace(d)
            object.__setattr__(bad, "parameters", parameters)
            checked = validate_query_plan(bad, self.record, self.spec, self.manifest, self.request, evaluated_at=NOW)
            self.assertIn("QUERY_CONTENT_MISMATCH", checked.reasons)
            self.assertIsNone(checked.sql)

    def test_plan_boundaries_and_authority_refused_if_tampered(self):
        d = self.build()
        for field, value in (("declared_bounds", (TARGET_START,) * 8), ("expected_rows", 575),
                             ("authority", "EXECUTE"), ("actual_authorization", Mock())):
            bad = replace(d)
            object.__setattr__(bad, field, value)
            checked = validate_query_plan(bad, self.record, self.spec, self.manifest, self.request, evaluated_at=NOW)
            self.assertIn("QUERY_CONTENT_MISMATCH", checked.reasons)

    def test_symbol_identity_not_inferred_from_joint_rows(self):
        d = self.build()
        self.assertEqual(d.sql.split(" FROM ")[0], "SELECT " + ",".join(PROJECTION))
        self.assertEqual(tuple(p[0] for p in d.parameters), ("BTCUSDT", "ETHUSDT"))
        self.assertEqual(len(d.parameters), 2)
        self.assertNotIn("symbol IN", d.sql)

    def test_sentinels_do_not_expand_total_admission_budget(self):
        d_expected = 574
        d = self.build(request=replace(self.request, max_rows=d_expected))
        self.assertEqual(d.expected_rows, d_expected)
        self.assertEqual(sum(p[-1] - 1 for p in d.parameters), d.expected_rows)
        self.assertEqual(sum(p[-1] for p in d.parameters), d.expected_rows + 2)

    def test_replay_of_plan_with_expired_approval_refused(self):
        d = self.build()
        checked = validate_query_plan(d, self.record, self.spec, self.manifest, self.request,
                                      evaluated_at=self.record.expires_at)
        self.assertIn("APPROVAL_EXPIRED", checked.reasons)
        self.assertIsNone(checked.sql)

    def test_foreign_plan_refused(self):
        for v in (Mock(), {}, None):
            checked = validate_query_plan(v, self.record, self.spec, self.manifest, self.request, evaluated_at=NOW)
            self.assertIn("QUERY_CONTENT_MISMATCH", checked.reasons)

    def test_unknown_availability_and_funding_unresolved(self):
        self.assertEqual(self.build().status, Readiness.SUFFICIENT)
        self.assertEqual(self.manifest.original_availability, "UNKNOWN")
        s = replace(self.spec, mode=AvailabilityMode.REQUIRE_VERIFIED_ASOF.value)
        self.check("ORIGINAL_RECEIPT_UNKNOWN", spec=s, record=replace(self.record, mode=s.mode))
        claim = FundingClaim("BTCUSDT", self.spec.context_start, self.spec.context_end,
            self.spec.source_id, self.spec.revision, CoverageState.UNKNOWN)
        self.assertEqual(assess_funding(claim).validation.status, Readiness.INSUFFICIENT)

    def test_plan_cannot_be_a_financial_input_or_sqlite_request(self):
        d = self.build()
        self.assertEqual(assess_funding(d).validation.status, Readiness.INVALID)
        with patch.object(fixture.sqlite3, "connect") as connect:
            self.assertEqual(fixture.inspect_fixture(d).status, Readiness.INVALID)
            connect.assert_not_called()

    def test_deterministic_plan_and_rejections(self):
        self.assertEqual(self.build(), self.build())
        bad = replace(self.request, table="foreign", max_rows=4097, projection=("*",))
        self.assertEqual(self.build(request=bad), self.build(request=bad))

    def test_static_no_io_or_execution_imports(self):
        root = Path(__file__).resolve().parents[1]
        for name in ("authorization_binding.py", "fixed_query_plan.py"):
            tree = ast.parse((root / "src/demo_futures/research_v2" / name).read_text())
            imports = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
            imports += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
            self.assertFalse(any(x in imports for x in ("sqlite3", "pathlib", "os", "socket", "hashlib")))
            calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
            self.assertFalse(any(isinstance(n.func, ast.Attribute) and n.func.attr in
                ("execute", "connect", "open", "read_bytes", "read_text", "activate") for n in calls))

    def test_guard_blocks_actual_io_and_preserves_mock_event_isolation(self):
        from verify_v2_authorization_query import make_guard, ROOT
        events = []
        guard = make_guard(ROOT / "reports/research-v2/V2-AUTHORIZATION-QUERY-INVENTED", events)
        for event in ("sqlite3.connect", "socket.connect", "subprocess.Popen", "os.mkdir", "os.remove"):
            with self.assertRaises(RuntimeError):
                guard(event, ())
        self.assertEqual(len(events), 5)
        self.assertEqual(fixture._FIXTURES, {})


if __name__ == "__main__":
    unittest.main()
