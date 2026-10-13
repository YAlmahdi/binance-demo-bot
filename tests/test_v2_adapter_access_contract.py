"""Invented metadata only. No fixture creation, SQLite connection or market rows."""
from dataclasses import FrozenInstanceError, fields, replace
import sqlite3
import unittest
from unittest.mock import Mock, patch

from demo_futures.research_v2.adapter_access_contract import (
    AdapterAccessSpec, AdapterDiagnostics, PinnedSnapshotManifest,
    PROVENANCE_ASSERTIONS, SCHEMA_ID, validate_adapter_access,
)
from demo_futures.research_v2.config import HOUR, STEP
from demo_futures.research_v2.contracts import EvidenceIdentity, Readiness, REASON_ORDER
from demo_futures.research_v2.features import SyntheticSeries
from demo_futures.research_v2.funding_contracts import CoverageState, FundingClaim, assess_funding
from demo_futures.research_v2.loader_boundary import BoundaryRequest, assess_boundary, validate_request
from demo_futures.research_v2.quality_contracts import assess_candles
from demo_futures.research_v2.source_contracts import (
    AvailabilityMode, OriginalAvailability, PROJECTION, TARGET_START, TARGET_END,
    ScopedHashMetadata, SourceExpectation, SourceMetadata, assess_source,
)
from demo_futures.research_v2 import sqlite_fixture_contract as fixture


def declarations():
    common = dict(scope_id="invented-scope", source_id="invented-source", revision="r1",
                  snapshot_id="invented-snapshot", symbols=("BTCUSDT", "ETHUSDT"),
                  interval="5m", start=TARGET_START + 18 * HOUR,
                  end=TARGET_START + 20 * HOUR, context_start=TARGET_START,
                  context_end=TARGET_START + 24 * HOUR, prefix_start=TARGET_START,
                  prefix_end=TARGET_START + 18 * HOUR, horizon_end=TARGET_START + 24 * HOUR,
                  decision_time=TARGET_START + 19 * HOUR - 1, projection=PROJECTION,
                  approval_ref="invented-task-reference", prefix_basis_ref="invented-prefix-choice")
    hashes = (("BTCUSDT", "a" * 64), ("ETHUSDT", "b" * 64))
    spec = AdapterAccessSpec(**common,
        mode=AvailabilityMode.EXPLORATORY_CLOSED_BAR_APPROXIMATION.value,
        expected_scoped_sha256=hashes)
    manifest = PinnedSnapshotManifest(**common, schema_id=SCHEMA_ID, schema_version=1,
        scoped_sha256=hashes, approval_basis="SYNTHETIC_ASSERTION",
        provenance_refs=tuple((a, "invented-" + a, "SYNTHETIC_ASSERTION") for a in PROVENANCE_ASSERTIONS),
        retrieved_at=TARGET_START + 25 * HOUR, original_availability="UNKNOWN")
    return spec, manifest


def boundary(spec):
    return BoundaryRequest(spec.symbols, spec.context_start, spec.context_end,
        spec.decision_time, spec.scope_id, spec.source_id, spec.revision, AvailabilityMode(spec.mode))


def source(spec, manifest, symbol="BTCUSDT"):
    def ev(assertion):
        return EvidenceIdentity("invented-" + assertion, spec.source_id, spec.revision, assertion)
    return SourceMetadata(spec.scope_id, spec.source_id, spec.revision, symbol, "5m",
        spec.context_start, spec.context_end, spec.decision_time, manifest.retrieved_at,
        AvailabilityMode(spec.mode), OriginalAvailability.UNKNOWN,
        ev("SOURCE_IDENTITY"), ev("APPROVED_SYNTHETIC_SCOPE"),
        ScopedHashMetadata(dict(spec.expected_scoped_sha256)[symbol], spec.source_id,
            spec.revision, symbol, "5m", spec.context_start, spec.context_end))


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.spec, self.manifest = declarations()

    def check(self, reason, *, spec=None, manifest=None, status=Readiness.INVALID):
        checked = validate_adapter_access(self.spec if spec is None else spec,
                                          self.manifest if manifest is None else manifest)
        self.assertEqual(checked.status, status)
        self.assertIn(reason, checked.reasons)
        self.assertEqual(checked.reasons, tuple(r for r in REASON_ORDER if r in checked.reasons))
        return checked

    def test_valid_consistency_no_authority(self):
        d = validate_adapter_access(self.spec, self.manifest)
        self.assertEqual(d.status, Readiness.SUFFICIENT)
        self.assertEqual(d.authority, "INERT_VALIDATION_ONLY")
        self.assertEqual(d.historical_evidence, "UNAUTHENTICATED / NOT VERIFIED")
        self.assertEqual(d.risk_clearance, "NOT CLEARED")
        self.assertEqual(self.manifest.original_availability, "UNKNOWN")
        self.assertEqual({f.name for f in fields(d)},
            {"status", "reasons", "evidence", "authority", "historical_evidence", "risk_clearance"})

    def test_diagnostics_truth_test_refused(self):
        for d in (validate_adapter_access(self.spec, self.manifest),
                  validate_adapter_access(None, self.manifest)):
            with self.assertRaises(TypeError):
                bool(d)

    def test_frozen_slots(self):
        for value in (self.spec, self.manifest, validate_adapter_access(self.spec, self.manifest)):
            with self.assertRaises((FrozenInstanceError, AttributeError, TypeError)):
                value.authority = "REAL_ACCESS"
            self.assertFalse(hasattr(value, "__dict__"))

    def test_mutable_containers_refused(self):
        for change in ({"symbols": ["BTCUSDT"]}, {"projection": list(PROJECTION)},
                       {"expected_scoped_sha256": list(self.spec.expected_scoped_sha256)},
                       {"expected_scoped_sha256": (("BTCUSDT", {"digest": "a" * 64}),)}):
            with self.subTest(change=tuple(change)), self.assertRaises(ValueError):
                replace(self.spec, **change)
        with self.assertRaises(ValueError):
            replace(self.manifest, provenance_refs=[("SOURCE_IDENTITY", "invented", "SYNTHETIC_ASSERTION")])

    def test_primitive_subclasses_and_booleans_refused(self):
        class Text(str):
            pass
        class Number(int):
            pass
        for change in ({"source_id": Text("invented")}, {"start": True}, {"start": Number(1)},
                       {"symbols": (Text("BTCUSDT"),)}, {"start": float(self.spec.start)}):
            with self.subTest(field=tuple(change)), self.assertRaises(ValueError):
                replace(self.spec, **change)

    def test_capability_injection_refused(self):
        for value in (Mock(), lambda: None, object(), {"scope": self.spec}):
            self.check("INVALID_SCHEMA_OR_TIME", spec=value)
            with self.assertRaises(ValueError):
                replace(self.manifest, availability_ref=value)

    def test_foreign_subclass_refused(self):
        class Foreign(AdapterAccessSpec):
            pass
        obj = Foreign(**{f.name: getattr(self.spec, f.name) for f in fields(self.spec) if f.init})
        self.check("INVALID_SCHEMA_OR_TIME", spec=obj)

    def test_tampered_shape_revalidated(self):
        object.__setattr__(self.spec, "symbols", ["BTCUSDT"])
        self.check("INVALID_SCHEMA_OR_TIME")

    def test_missing_slot_fail_closed(self):
        object.__delattr__(self.manifest, "snapshot_id")
        self.check("INVALID_SCHEMA_OR_TIME")

    def test_empty_duplicate_unsupported_symbols(self):
        for symbols, reason in (((), "SOURCE_CONFLICT"), (("BTCUSDT", "BTCUSDT"), "SOURCE_CONFLICT"),
                                (("SOLUSDT",), "WRONG_SYMBOL"), (("BNBUSDT",), "WRONG_SYMBOL"),
                                (("XRPUSDT",), "WRONG_SYMBOL")):
            with self.subTest(symbols=symbols):
                self.check(reason, spec=replace(self.spec, symbols=symbols))

    def test_wrong_interval(self):
        self.check("WRONG_INTERVAL", spec=replace(self.spec, interval="1h"))

    def test_invalid_utc_boundaries(self):
        for field in ("start", "end", "context_start", "context_end", "prefix_start", "prefix_end", "horizon_end"):
            for value in (-1, getattr(self.spec, field) + 1):
                with self.subTest(field=field, value=value):
                    self.check("INVALID_SCHEMA_OR_TIME", spec=replace(self.spec, **{field: value}))
        with self.assertRaises(ValueError):
            replace(self.spec, start="2026-05-03T00:00:00")

    def test_invalid_decision_time(self):
        for t in (self.spec.start - 1, self.spec.end, self.spec.decision_time + 1):
            self.check("INVALID_SCHEMA_OR_TIME", spec=replace(self.spec, decision_time=t))

    def test_protected_decision_scope(self):
        self.check("PROTECTED_PERIOD", spec=replace(self.spec, start=TARGET_END,
                                                   end=TARGET_END + HOUR))

    def test_second_protected_period(self):
        from demo_futures.research_v2.source_contracts import PROTECTED
        self.check("PROTECTED_PERIOD", spec=replace(self.spec, start=PROTECTED[1][0],
                                                   end=PROTECTED[1][0] + HOUR))

    def test_prefix_outside_target(self):
        self.check("UNAUTHORIZED_DATES", spec=replace(self.spec,
            prefix_start=TARGET_START - STEP, context_start=TARGET_START - STEP))

    def test_horizon_protected_overlap(self):
        self.check("PROTECTED_PERIOD", spec=replace(self.spec,
            horizon_end=TARGET_END + STEP, context_end=TARGET_END + STEP))

    def test_prefix_and_context_must_match(self):
        for change in ({"prefix_start": self.spec.context_start + STEP},
                       {"prefix_end": self.spec.start - STEP},
                       {"context_start": self.spec.context_start + STEP},
                       {"horizon_end": self.spec.context_end - STEP}):
            self.check("UNAUTHORIZED_DATES", spec=replace(self.spec, **change))

    def test_reversed_or_empty_required_spans(self):
        for change in ({"end": self.spec.start}, {"prefix_start": self.spec.prefix_end},
                       {"horizon_end": self.spec.end - STEP}):
            self.check("UNAUTHORIZED_DATES", spec=replace(self.spec, **change))

    def test_explicit_prefix_not_a_warmup_certificate(self):
        # A tiny declared prefix is consistent metadata, not usable ATR history.
        changes = dict(prefix_start=self.spec.start - STEP, context_start=self.spec.start - STEP)
        self.assertEqual(validate_adapter_access(replace(self.spec, **changes),
            replace(self.manifest, **changes)).status, Readiness.SUFFICIENT)

    def test_exact_target_context_edges(self):
        changes = dict(context_end=TARGET_END, horizon_end=TARGET_END)
        self.assertEqual(validate_adapter_access(replace(self.spec, **changes),
            replace(self.manifest, **changes, retrieved_at=TARGET_END + HOUR)).status, Readiness.SUFFICIENT)

    def test_scope_binding_all_fields(self):
        for name, value in (("scope_id", "other"), ("source_id", "other"), ("snapshot_id", "other"),
                            ("approval_ref", "other"), ("prefix_basis_ref", "other"),
                            ("symbols", ("ETHUSDT", "BTCUSDT")),
                            ("decision_time", self.manifest.decision_time - HOUR)):
            with self.subTest(field=name):
                self.check("SOURCE_IDENTITY_MISMATCH", manifest=replace(self.manifest, **{name: value}))

    def test_revision_mismatch(self):
        self.check("REVISION_MISMATCH", manifest=replace(self.manifest, revision="r2"))

    def test_identifiers_not_paths_or_urls(self):
        for v in ("", "../source", "C:\\source", "https://example.invalid/source", "source:handle"):
            self.check("SOURCE_IDENTITY_MISMATCH", spec=replace(self.spec, source_id=v))

    def test_wrong_schema_version(self):
        for change in ({"schema_id": "other"}, {"schema_version": 2}):
            self.check("INVALID_SCHEMA_OR_TIME", manifest=replace(self.manifest, **change))

    def test_wrong_projection(self):
        self.check("INVALID_SCHEMA_OR_TIME", manifest=replace(self.manifest, projection=PROJECTION[:-1]))

    def test_malformed_hashes(self):
        for digest in ("", "a" * 63, "A" * 64, "g" * 64):
            self.check("SCOPED_HASH_INVALID", manifest=replace(self.manifest,
                scoped_sha256=(("BTCUSDT", digest), ("ETHUSDT", "b" * 64))))

    def test_pinned_hash_mismatch(self):
        self.check("SCOPED_HASH_INVALID", manifest=replace(self.manifest,
            scoped_sha256=(("BTCUSDT", "c" * 64), ("ETHUSDT", "b" * 64))))

    def test_hash_inventory_exact_unique_symbols(self):
        for rows in ((), self.manifest.scoped_sha256[:1], self.manifest.scoped_sha256[::-1],
                     (("BTCUSDT", "a" * 64), ("BTCUSDT", "a" * 64))):
            self.check("SCOPED_HASH_INVALID", manifest=replace(self.manifest, scoped_sha256=rows))

    def test_hash_algorithm_and_scope(self):
        for change in ({"hash_algorithm": "md5"}, {"hash_scope": "WHOLE_FILE"}):
            self.check("SCOPED_HASH_INVALID", manifest=replace(self.manifest, **change))

    def test_missing_approval_and_prefix_reference(self):
        for name in ("approval_ref", "prefix_basis_ref"):
            self.check("INVALID_EVIDENCE", spec=replace(self.spec, **{name: ""}),
                manifest=replace(self.manifest, **{name: ""}), status=Readiness.INSUFFICIENT)

    def test_unverified_approval_reference(self):
        self.check("INVALID_EVIDENCE", manifest=replace(self.manifest, approval_basis="UNKNOWN"),
                   status=Readiness.INSUFFICIENT)

    def test_missing_provenance(self):
        self.check("INVALID_EVIDENCE", manifest=replace(self.manifest, provenance_refs=()),
                   status=Readiness.INSUFFICIENT)

    def test_unknown_provenance(self):
        rows = tuple((a, i, "UNKNOWN") for a, i, _ in self.manifest.provenance_refs)
        self.check("INVALID_EVIDENCE", manifest=replace(self.manifest, provenance_refs=rows),
                   status=Readiness.INSUFFICIENT)

    def test_unsupported_evidence_claims(self):
        self.check("INVALID_EVIDENCE", manifest=replace(self.manifest, approval_basis="REAL_VERIFIED"))
        rows = tuple((a, i, "REAL_VERIFIED") for a, i, _ in self.manifest.provenance_refs)
        self.check("INVALID_EVIDENCE", manifest=replace(self.manifest, provenance_refs=rows))

    def test_duplicate_foreign_provenance(self):
        for rows in (self.manifest.provenance_refs + self.manifest.provenance_refs[:1],
                     (("FOREIGN", "invented", "SYNTHETIC_ASSERTION"),),
                     (("SOURCE_IDENTITY", "../path", "SYNTHETIC_ASSERTION"),)):
            self.check("INVALID_EVIDENCE", manifest=replace(self.manifest, provenance_refs=rows))

    def test_mode_required(self):
        self.check("INVALID_SCHEMA_OR_TIME", spec=replace(self.spec, mode="AUTO"))

    def test_unknown_strict_availability_insufficient(self):
        self.check("ORIGINAL_RECEIPT_UNKNOWN", spec=replace(self.spec,
            mode=AvailabilityMode.REQUIRE_VERIFIED_ASOF.value), status=Readiness.INSUFFICIENT)

    def test_unsupported_original_verification(self):
        self.check("ORIGINAL_AVAILABILITY_UNSUPPORTED", manifest=replace(self.manifest,
            original_availability="VERIFIED"))

    def test_late_original_receipt_still_insufficient(self):
        m = replace(self.manifest, original_availability="VERIFIED",
                    original_receipt=self.spec.decision_time + 2, availability_ref="invented-receipt")
        self.check("RECEIPT_LATE", manifest=m, status=Readiness.INSUFFICIENT)
        self.assertEqual(m.original_receipt, self.spec.decision_time + 2)

    def test_exact_synthetic_receipt_not_real_authenticity(self):
        s = replace(self.spec, mode=AvailabilityMode.REQUIRE_VERIFIED_ASOF.value)
        m = replace(self.manifest, original_availability="VERIFIED",
                    original_receipt=s.decision_time + 1, availability_ref="invented-receipt")
        d = validate_adapter_access(s, m)
        self.assertEqual(d.status, Readiness.SUFFICIENT)
        self.assertEqual(d.historical_evidence, "UNAUTHENTICATED / NOT VERIFIED")

    def test_invalid_retrieval_and_receipt_times(self):
        for change in ({"retrieved_at": self.manifest.context_end - 1},
                       {"original_receipt": -1}, {"original_receipt": self.manifest.retrieved_at + 1}):
            self.check("INVALID_SCHEMA_OR_TIME", manifest=replace(self.manifest, **change))

    def test_reasons_order_deterministic_invalid_dominates(self):
        s = replace(self.spec, interval="1h", symbols=("XRPUSDT",), source_id="../path")
        m = replace(self.manifest, approval_basis="UNKNOWN")
        a = validate_adapter_access(s, m)
        self.assertEqual(a, validate_adapter_access(s, m))
        self.assertEqual(a.status, Readiness.INVALID)
        self.assertIn("INVALID_EVIDENCE", a.reasons)

    def test_forged_diagnostics_payload_refused(self):
        for reason in (Mock(), lambda: None, "REAL_ACCESS"):
            with self.assertRaises(ValueError):
                AdapterDiagnostics(Readiness.INVALID, (reason,))
        with self.assertRaises(ValueError):
            AdapterDiagnostics("SUFFICIENT")


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.spec, self.manifest = declarations()

    def test_boundary_scope_preserved(self):
        self.assertEqual(validate_request(boundary(self.spec)).status, Readiness.SUFFICIENT)
        self.assertEqual(validate_request(replace(boundary(self.spec),
            end=TARGET_END + STEP)).status, Readiness.INVALID)

    def test_success_not_downstream_boundary_evidence(self):
        d = validate_adapter_access(self.spec, self.manifest)
        self.assertEqual(validate_request(d).status, Readiness.INVALID)
        checked = assess_boundary(boundary(self.spec), sources=(d,))
        self.assertEqual(checked.validation.status, Readiness.INVALID)

    def test_source_unknown_stays_insufficient_under_strict_mode(self):
        s = replace(self.spec, mode=AvailabilityMode.REQUIRE_VERIFIED_ASOF.value)
        m = source(s, self.manifest)
        checked = assess_source(m, SourceExpectation(s.scope_id, s.source_id, s.revision,
                                                    s.context_start, s.context_end))
        self.assertEqual(checked.status, Readiness.INSUFFICIENT)
        self.assertIn("ORIGINAL_RECEIPT_UNKNOWN", checked.reasons)

    def test_funding_unknown_not_cleared_by_metadata(self):
        self.assertEqual(validate_adapter_access(self.spec, self.manifest).status, Readiness.SUFFICIENT)
        claim = FundingClaim("BTCUSDT", self.spec.context_start, self.spec.context_end,
            self.spec.source_id, self.spec.revision, CoverageState.UNKNOWN)
        checked = assess_funding(claim)
        self.assertEqual(checked.validation.status, Readiness.INSUFFICIENT)
        self.assertEqual(checked.state, CoverageState.UNKNOWN)

    def test_missing_quality_context_stays_insufficient(self):
        empty = SyntheticSeries("BTCUSDT", (), self.spec.source_id)
        q = assess_candles(empty, self.spec.decision_time)
        self.assertEqual(q.structure.status, Readiness.INSUFFICIENT)
        self.assertEqual(q.causal.status, Readiness.INSUFFICIENT)
        self.assertEqual(q.market_realism, "UNKNOWN / NOT CERTIFIED")
        self.assertEqual(assess_candles(validate_adapter_access(self.spec, self.manifest),
            self.spec.decision_time).structure.status, Readiness.INVALID)

    def test_boundary_missing_funding_not_upgraded(self):
        req = boundary(self.spec)
        checked = assess_boundary(req, sources=tuple(source(self.spec, self.manifest, s)
                                                     for s in self.spec.symbols))
        self.assertEqual(checked.validation.status, Readiness.INSUFFICIENT)
        self.assertTrue(all(d.funding.status == Readiness.INSUFFICIENT for d in checked.symbols))
        with self.assertRaises(TypeError):
            bool(checked)

    def test_diagnostics_not_sqlite_request_no_connection(self):
        with patch.object(fixture.sqlite3, "connect") as connect, patch.object(fixture, "_lease_for") as lease:
            checked = fixture.inspect_fixture(validate_adapter_access(self.spec, self.manifest))
            self.assertEqual(checked.status, Readiness.INVALID)
            connect.assert_not_called()
            lease.assert_not_called()
            with self.assertRaises(TypeError):
                bool(checked)

    def test_sqlite_row_cap_and_strict_interior_unchanged(self):
        req = boundary(self.spec)
        cases = (replace(req, start=TARGET_START),
                 replace(req, start=TARGET_START + STEP, end=TARGET_END - STEP))
        self.assertEqual(fixture.MAX_ROWS, 4096)
        for scope in cases:
            request = fixture.SQLiteFixtureRequest(scope, fixture.FixtureToken("invented-not-owned"),
                fixture.FixtureSnapshot("a" * 64, "b" * 64), ())
            with self.assertRaises(fixture._Refused) as error:
                fixture._validate_request(request)
            self.assertEqual(error.exception.reason, "UNAPPROVED_SCOPE")

    def test_sqlite_fixed_query_predicates_no_sql_executed(self):
        gate = fixture._QueryGate(boundary(self.spec))
        sql, params = gate.queries["rows"]
        for fragment in ("symbol IN (?,?)", "interval=?", "open_time>=?", "open_time<?",
                         "close_time>=?", "close_time<?", "ORDER BY symbol,ordinal LIMIT ?"):
            self.assertIn(fragment, sql)
        self.assertEqual(params, ("BTCUSDT", "ETHUSDT", "5m", self.spec.context_start,
            self.spec.context_end, self.spec.context_start, self.spec.context_end, 4097))
        connection = Mock()
        for bad_sql, bad_params in (("ATTACH DATABASE 'ignored' AS external", ()),
                                   (sql, params[:-1] + (999999,)), (sql.replace("open_time<?", "1=1"), params)):
            with self.assertRaises(fixture._Refused):
                gate.execute(connection, "rows", bad_sql, bad_params)
        connection.execute.assert_not_called()

    def test_sqlite_authorizer_write_attach_extension_denials(self):
        gate = fixture._QueryGate(boundary(self.spec))
        gate.phase = "rows"
        for action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_DELETE, sqlite3.SQLITE_UPDATE,
                       sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_PRAGMA):
            self.assertEqual(gate.authorizer(action, "load_extension", None, "main", None), sqlite3.SQLITE_DENY)
        self.assertEqual(gate.authorizer(sqlite3.SQLITE_READ, "fixture_candles", "close", "external", None), sqlite3.SQLITE_DENY)

    def test_guard_rejects_io_and_unsafe_filesystem_operations(self):
        from verify_v2_adapter_access_contract import make_guard, ROOT
        events = []
        guard = make_guard(ROOT / "reports/research-v2/V2-ADAPTER-ACCESS-CONTRACT-INVENTED", events)
        for event, args in (("sqlite3.connect", ()), ("socket.connect", ()), ("subprocess.Popen", ()),
                            ("os.mkdir", ()), ("os.remove", ()), ("os.rmdir", ()), ("os.rename", ())):
            with self.subTest(event=event), self.assertRaises(RuntimeError):
                guard(event, args)
        self.assertEqual(len(events), 7)
        self.assertEqual(fixture._FIXTURES, {})


if __name__ == "__main__":
    unittest.main()
