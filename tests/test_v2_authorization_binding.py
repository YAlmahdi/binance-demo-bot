"""Invented approval records; no actual authorization, ledger, files or SQL."""
from dataclasses import FrozenInstanceError, fields, replace
import unittest
from unittest.mock import Mock, patch

from demo_futures.research_v2.adapter_access_contract import validate_adapter_access
from demo_futures.research_v2.authorization_binding import (
    AUTHORIZATION_REASONS, AuthorizationDiagnostics, SyntheticApprovalRecord, validate_authorization,
)
from demo_futures.research_v2.config import HOUR, STEP
from demo_futures.research_v2.contracts import Readiness
from demo_futures.research_v2.funding_contracts import CoverageState, FundingClaim, assess_funding
from demo_futures.research_v2.source_contracts import AvailabilityMode, PROTECTED, TARGET_START, TARGET_END
from demo_futures.research_v2.loader_boundary import validate_request
from demo_futures.research_v2 import sqlite_fixture_contract as sqlite_fixture
from test_v2_adapter_access_contract import declarations


NOW = TARGET_END + 10 * HOUR  # Explicit invented evaluation instant, not a clock read.


def inputs():
    spec, manifest = declarations()
    # Explicitly declared interior scope, not an implicit prefix convention.
    change = dict(context_start=TARGET_START + STEP, prefix_start=TARGET_START + STEP)
    spec, manifest = replace(spec, **change), replace(manifest, **change)
    shared = ("scope_id", "source_id", "revision", "snapshot_id", "symbols", "interval", "start",
              "end", "context_start", "context_end", "prefix_start", "prefix_end", "horizon_end",
              "decision_time", "projection", "prefix_basis_ref")
    values = {name: getattr(spec, name) for name in shared}
    values.update({name: getattr(manifest, name) for name in
                  ("schema_id", "schema_version", "scoped_sha256", "provenance_refs", "hash_algorithm", "hash_scope")})
    record = SyntheticApprovalRecord(**values, record_id=spec.approval_ref,
        ledger_ref="invented-independent-record", approval_basis="SYNTHETIC_ASSERTION",
        ledger_basis="SYNTHETIC_ASSERTION", mode=spec.mode, issued_at=NOW - HOUR,
        expires_at=NOW + HOUR, revoked=False, revocation_ref="", max_rows=1024)
    return record, spec, manifest


class AuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.record, self.spec, self.manifest = inputs()

    def check(self, reason, *, record=None, spec=None, manifest=None, evaluated_at=NOW,
              status=Readiness.INVALID):
        d = validate_authorization(self.record if record is None else record,
            self.spec if spec is None else spec, self.manifest if manifest is None else manifest,
            evaluated_at=evaluated_at)
        self.assertEqual(d.status, status)
        self.assertIn(reason, d.reasons)
        self.assertEqual(d.reasons, tuple(r for r in AUTHORIZATION_REASONS if r in d.reasons))
        return d

    def test_valid_binding_not_actual_authorization(self):
        d = validate_authorization(self.record, self.spec, self.manifest, evaluated_at=NOW)
        self.assertEqual(d.status, Readiness.SUFFICIENT)
        self.assertEqual(d.actual_authorization, "NOT VERIFIED")
        self.assertEqual(d.authority, "SYNTHETIC_CONSISTENCY_ONLY")
        self.assertEqual(d.historical_evidence, "UNAUTHENTICATED / NOT VERIFIED")
        self.assertEqual(d.risk_clearance, "NOT CLEARED")
        self.assertEqual({f.name for f in fields(d)}, {"status", "reasons", "evidence", "authority",
            "actual_authorization", "historical_evidence", "risk_clearance"})

    def test_missing_record_even_when_metadata_passes(self):
        self.assertEqual(validate_adapter_access(self.spec, self.manifest).status, Readiness.SUFFICIENT)
        d = validate_authorization(None, self.spec, self.manifest, evaluated_at=NOW)
        self.assertEqual(d.status, Readiness.INSUFFICIENT)
        self.assertIn("APPROVAL_MISSING", d.reasons)

    def test_metadata_success_not_an_approval_record(self):
        self.check("INVALID_SCHEMA_OR_TIME", record=validate_adapter_access(self.spec, self.manifest))

    def test_precomputed_binding_not_an_approval_record(self):
        d = validate_authorization(self.record, self.spec, self.manifest, evaluated_at=NOW)
        self.check("INVALID_SCHEMA_OR_TIME", record=d)
        self.assertEqual(validate_request(d).status, Readiness.INVALID)

    def test_immutable_and_no_truth_testing(self):
        for v in (self.record, validate_authorization(self.record, self.spec, self.manifest, evaluated_at=NOW)):
            with self.assertRaises((FrozenInstanceError, TypeError, AttributeError)):
                v.actual_authorization = "YES"
            self.assertFalse(hasattr(v, "__dict__"))
        with self.assertRaises(TypeError):
            bool(validate_authorization(self.record, self.spec, self.manifest, evaluated_at=NOW))

    def test_mutable_nested_fields_refused(self):
        for change in ({"symbols": list(self.record.symbols)}, {"projection": list(self.record.projection)},
                       {"scoped_sha256": list(self.record.scoped_sha256)},
                       {"provenance_refs": (("SOURCE_IDENTITY", {}, "SYNTHETIC_ASSERTION"),)}):
            with self.assertRaises(ValueError):
                replace(self.record, **change)

    def test_foreign_types_and_capabilities_refused(self):
        for v in (Mock(), lambda: None, {}, object()):
            self.check("INVALID_SCHEMA_OR_TIME", record=v)
            with self.assertRaises(ValueError):
                replace(self.record, ledger_ref=v)

    def test_scalar_subclasses_booleans_floats_refused(self):
        class Text(str):
            pass
        for change in ({"source_id": Text("invented")}, {"issued_at": True},
                       {"expires_at": float(NOW)}, {"revoked": 1}, {"max_rows": False}):
            with self.assertRaises(ValueError):
                replace(self.record, **change)

    def test_foreign_record_subclass_refused(self):
        class Foreign(SyntheticApprovalRecord):
            pass
        v = Foreign(**{f.name: getattr(self.record, f.name) for f in fields(self.record) if f.init})
        self.check("INVALID_SCHEMA_OR_TIME", record=v)

    def test_tampered_or_missing_record_fields_revalidated(self):
        for field, v in (("scoped_sha256", []), ("ledger_ref", Mock()), ("evidence", "REAL")):
            r = replace(self.record)
            object.__setattr__(r, field, v)
            self.check("UNAPPROVED_SCOPE" if field == "evidence" else "INVALID_SCHEMA_OR_TIME", record=r)
        object.__delattr__(self.record, "record_id")
        self.check("INVALID_SCHEMA_OR_TIME")

    def test_evaluation_time_exact_primitive(self):
        for t in (-1, True, float(NOW), "now", None, Mock()):
            self.check("INVALID_SCHEMA_OR_TIME", evaluated_at=t)

    def test_evaluation_time_is_required(self):
        with self.assertRaises(TypeError):
            validate_authorization(self.record, self.spec, self.manifest)

    def test_inclusive_issuance_exclusive_expiry(self):
        self.assertEqual(validate_authorization(self.record, self.spec, self.manifest,
            evaluated_at=self.record.issued_at).status, Readiness.SUFFICIENT)
        self.check("APPROVAL_NOT_YET_VALID", evaluated_at=self.record.issued_at - 1)
        self.check("APPROVAL_EXPIRED", evaluated_at=self.record.expires_at)
        self.check("APPROVAL_EXPIRED", evaluated_at=self.record.expires_at + 1)

    def test_invalid_validity_interval(self):
        for change in ({"issued_at": -1}, {"expires_at": self.record.issued_at},
                       {"expires_at": self.record.issued_at - 1}):
            self.check("INVALID_SCHEMA_OR_TIME", record=replace(self.record, **change))

    def test_revoked_record_and_evidence(self):
        self.check("APPROVAL_REVOKED", record=replace(self.record, revoked=True, revocation_ref="invented-revocation"))
        d = self.check("APPROVAL_REVOKED", record=replace(self.record, revoked=True))
        self.assertIn("INVALID_EVIDENCE", d.reasons)

    def test_contradictory_revocation_declaration(self):
        self.check("APPROVAL_METADATA_MISMATCH", record=replace(self.record, revocation_ref="invented-revocation"))

    def test_missing_approval_and_ledger_identity(self):
        for field in ("record_id", "ledger_ref"):
            self.check("APPROVAL_MISSING", record=replace(self.record, **{field: ""}), status=Readiness.INSUFFICIENT)

    def test_approval_id_mismatch(self):
        self.check("APPROVAL_IDENTITY_MISMATCH", record=replace(self.record, record_id="other-record"))

    def test_no_urls_or_paths_as_ledger_references(self):
        for v in ("../ledger", "C:\\ledger", "https://example.invalid/ledger"):
            self.check("INVALID_EVIDENCE", record=replace(self.record, ledger_ref=v))

    def test_unknown_bases_remain_insufficient(self):
        for field in ("approval_basis", "ledger_basis"):
            for value in ("", "UNKNOWN"):
                self.check("APPROVAL_UNVERIFIED", record=replace(self.record, **{field: value}), status=Readiness.INSUFFICIENT)

    def test_real_approval_claims_refused(self):
        for field in ("approval_basis", "ledger_basis"):
            self.check("INVALID_EVIDENCE", record=replace(self.record, **{field: "REAL_VERIFIED"}))

    def test_scope_and_source_identity_binding(self):
        for field in ("scope_id", "source_id", "snapshot_id", "prefix_basis_ref"):
            self.check("APPROVAL_SCOPE_MISMATCH", record=replace(self.record, **{field: "other"}))

    def test_revision_drift(self):
        self.check("REVISION_MISMATCH", record=replace(self.record, revision="r2"))

    def test_symbols_interval_and_projection(self):
        for change in ({"symbols": ("XRPUSDT",)}, {"symbols": ("BTCUSDT", "BTCUSDT")},
                       {"symbols": self.record.symbols[::-1]}, {"interval": "1h"},
                       {"projection": self.record.projection[:-1]}):
            self.check("APPROVAL_SCOPE_MISMATCH", record=replace(self.record, **change))

    def test_all_temporal_scope_fields_exact(self):
        for field in ("start", "end", "context_start", "context_end", "prefix_start", "prefix_end", "horizon_end", "decision_time"):
            self.check("APPROVAL_SCOPE_MISMATCH", record=replace(self.record, **{field: getattr(self.record, field) + STEP}))

    def test_both_protected_intervals_rejected(self):
        for start, end in PROTECTED:
            self.check("PROTECTED_PERIOD", spec=replace(self.spec, start=start, end=end))

    def test_prefix_and_horizon_escape(self):
        for change in ({"prefix_start": TARGET_START - STEP}, {"horizon_end": TARGET_END + STEP}):
            self.check("UNAUTHORIZED_DATES", spec=replace(self.spec, **change))

    def test_hash_scope_algorithm_and_values_bound(self):
        self.check("SCOPED_HASH_INVALID", record=replace(self.record, scoped_sha256=()))
        self.check("SCOPED_HASH_INVALID", record=replace(self.record,
            scoped_sha256=(("BTCUSDT", "f" * 64), ("ETHUSDT", "b" * 64))))
        for field, value in (("hash_algorithm", "md5"), ("hash_scope", "WHOLE_FILE"),
                             ("schema_id", "other"), ("schema_version", 2), ("mode", "AUTO")):
            self.check("APPROVAL_METADATA_MISMATCH", record=replace(self.record, **{field: value}))

    def test_provenance_absent_or_conflicting(self):
        self.check("INVALID_EVIDENCE", record=replace(self.record, provenance_refs=()), status=Readiness.INSUFFICIENT)
        rows = (self.record.provenance_refs[0],) * 3
        self.check("INVALID_EVIDENCE", record=replace(self.record, provenance_refs=rows))

    def test_metadata_contract_revalidated(self):
        self.check("REVISION_MISMATCH", manifest=replace(self.manifest, revision="r2"))
        self.check("SCOPED_HASH_INVALID", manifest=replace(self.manifest, scoped_sha256=()))
        object.__setattr__(self.spec, "symbols", [])
        self.check("INVALID_SCHEMA_OR_TIME")

    def test_resource_ceiling_not_expandable(self):
        for v in (0, -1, 4097):
            self.check("APPROVAL_RESOURCE_INVALID", record=replace(self.record, max_rows=v))

    def test_unknown_original_availability_remains_unresolved(self):
        self.assertEqual(self.manifest.original_availability, "UNKNOWN")
        s = replace(self.spec, mode=AvailabilityMode.REQUIRE_VERIFIED_ASOF.value)
        r = replace(self.record, mode=s.mode)
        self.check("ORIGINAL_RECEIPT_UNKNOWN", record=r, spec=s, status=Readiness.INSUFFICIENT)

    def test_funding_unknown_not_upgraded(self):
        d = validate_authorization(self.record, self.spec, self.manifest, evaluated_at=NOW)
        claim = FundingClaim("BTCUSDT", self.spec.context_start, self.spec.context_end,
            self.spec.source_id, self.spec.revision, CoverageState.UNKNOWN)
        self.assertEqual(d.status, Readiness.SUFFICIENT)
        self.assertEqual(assess_funding(claim).validation.status, Readiness.INSUFFICIENT)

    def test_diagnostics_cannot_reach_sqlite_reader(self):
        d = validate_authorization(self.record, self.spec, self.manifest, evaluated_at=NOW)
        with patch.object(sqlite_fixture.sqlite3, "connect") as connect:
            self.assertEqual(sqlite_fixture.inspect_fixture(d).status, Readiness.INVALID)
            connect.assert_not_called()

    def test_deterministic_reasons_invalid_dominates(self):
        r = replace(self.record, revoked=True, revocation_ref="invented", ledger_basis="UNKNOWN")
        d = self.check("APPROVAL_REVOKED", record=r)
        self.assertIn("APPROVAL_UNVERIFIED", d.reasons)
        self.assertEqual(d, validate_authorization(r, self.spec, self.manifest, evaluated_at=NOW))

    def test_diagnostic_payloads_and_authority_tampering_refused(self):
        with self.assertRaises(ValueError):
            AuthorizationDiagnostics(Readiness.INVALID, (Mock(),))
        d = AuthorizationDiagnostics(Readiness.SUFFICIENT)
        object.__setattr__(d, "authority", Mock())
        with self.assertRaises(ValueError):
            d.__post_init__()


if __name__ == "__main__":
    unittest.main()
