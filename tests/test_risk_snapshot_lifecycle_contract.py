"""Invented 2010 M4 ledgers, no market/account/engine inputs."""
import ast
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
import unittest
from unittest.mock import patch

from demo_futures.research_v2.contracts import EvidenceIdentity, Readiness
from demo_futures.risk_remediation.snapshot_lifecycle_contract import (
    Completeness, EventKind, SnapshotState, SnapshotRef, SnapshotDeclaration,
    LifecycleEvent, LifecycleEvidence, LifecycleResources, LifecycleDeclaration,
    SnapshotDiagnostic, LifecycleDiagnostic, assess_lifecycle,
)

BASE = 1262304000000


def proof(identity, purpose):
    return EvidenceIdentity(identity, "invented-source", "v1", purpose)


def ledger(count=1, **changes):
    scope = ("invented-owner", "invented-source", "v1")
    refs = tuple(SnapshotRef(*scope, f"snapshot-{i:03d}", i) for i in range(count))
    snapshots = tuple(SnapshotDeclaration(r, BASE - 10, BASE + 10, BASE - 5, BASE - 4,
        proof("declaration-" + r.snapshot_id, "SNAPSHOT_DECLARATION")) for r in refs)
    claims = tuple(LifecycleEvidence(r, Completeness.COMPLETE, BASE, BASE, BASE + 10, (),
        proof("ledger-" + r.snapshot_id, "LIFECYCLE_COMPLETENESS")) for r in refs)
    return replace(LifecycleDeclaration(*scope, BASE, snapshots, (), claims,
        LifecycleResources(count, count, count, 100000, 128)), **changes)


def event(d, index=0, kind=EventKind.REVOKE, **changes):
    r = d.snapshots[index].ref
    value = LifecycleEvent("event-" + r.snapshot_id, r, kind, BASE - 2, BASE - 1, BASE,
        d.snapshots[index + 1].ref if kind is EventKind.SUPERSEDE else None,
        proof("event-proof-" + r.snapshot_id, "LIFECYCLE_EVENT"))
    return replace(value, **changes)


def with_events(d, events):
    claims = tuple(replace(c, event_ids=tuple(sorted(e.event_id for e in events if e.ref == c.ref)))
        for c in d.evidence)
    return replace(d, events=events, evidence=claims)


class LifecycleTests(unittest.TestCase):
    def test_diagnostic_revision_ambiguity_is_not_hidden(self):
        rows = (SnapshotDiagnostic("snapshot-a", 0, SnapshotState.ACTIVE),
            SnapshotDiagnostic("snapshot-b", 0, SnapshotState.ACTIVE))
        with self.assertRaises(ValueError):
            LifecycleDiagnostic(Readiness.SUFFICIENT, snapshots=rows)

    def test_same_time_collision_on_one_snapshot_is_rejected(self):
        d = ledger()
        d = replace(d, resources=replace(d.resources, max_events=2, max_references=2))
        e = event(d)
        self.reject(with_events(d, (e, replace(e, event_id="other-event"))), "CONTRADICTORY_EVENT")

    def test_zero_time_origin_has_no_implicit_grace_or_clock(self):
        d = ledger(evaluation_time=0)
        s = replace(d.snapshots[0], valid_from=0, expires_at=1, observed_at=0, available_at=0)
        c = replace(d.evidence[0], observed_at=0, available_at=0, expires_at=1)
        d = replace(d, snapshots=(s,), evidence=(c,))
        self.assertEqual(assess_lifecycle(d).status, Readiness.SUFFICIENT)
        self.reject(with_events(d, (event(d, issued_at=0, available_at=0, effective_at=0),)),
            "REVOKED", Readiness.INSUFFICIENT)

    def test_supplied_successful_diagnostic_cannot_replace_raw_snapshot(self):
        d = ledger()
        result = assess_lifecycle(d)
        self.reject(replace(d, snapshots=(result,)), "INVALID_SCHEMA")

    def reject(self, value, reason, status=Readiness.INVALID):
        result = assess_lifecycle(value)
        self.assertEqual(result.status, status)
        self.assertIn(reason, result.reasons)
        self.assertEqual(result.aggregate_state, "BLOCKED")
        self.assertEqual(result.risk_clearance, "NOT CLEARED")
        return result

    def test_valid_complete_snapshot_is_diagnostic_only(self):
        result = assess_lifecycle(ledger())
        self.assertEqual(result.status, Readiness.SUFFICIENT)
        self.assertEqual(result.snapshots[0].state, SnapshotState.ACTIVE)
        self.assertEqual(result.authority, "SYNTHETIC_DIAGNOSTIC_ONLY")
        for name in ("approved", "admission", "token", "joint_loss", "funding_allowance"):
            self.assertFalse(hasattr(result, name))

    def test_snapshot_start_inclusive_expiry_exclusive(self):
        d = ledger()
        self.assertEqual(assess_lifecycle(replace(d, snapshots=(replace(d.snapshots[0], valid_from=BASE),))).status,
            Readiness.SUFFICIENT)
        self.reject(replace(d, snapshots=(replace(d.snapshots[0], expires_at=BASE),)), "EXPIRED", Readiness.INSUFFICIENT)
        self.reject(replace(d, snapshots=(replace(d.snapshots[0], valid_from=BASE + 1),)), "NOT_YET_VALID", Readiness.INSUFFICIENT)

    def test_revocation_effective_time_inclusive(self):
        d = ledger()
        out = self.reject(with_events(d, (event(d),)), "REVOKED", Readiness.INSUFFICIENT)
        self.assertEqual(out.snapshots[0].state, SnapshotState.REVOKED)
        self.reject(with_events(d, (event(d, effective_at=BASE + 1),)), "FUTURE_UNAVAILABLE", Readiness.INSUFFICIENT)

    def test_supersession_requires_declared_higher_revision(self):
        d = ledger(2)
        out = self.reject(with_events(d, (event(d, kind=EventKind.SUPERSEDE),)), "SUPERSEDED", Readiness.INSUFFICIENT)
        self.assertEqual(tuple(s.state for s in out.snapshots), (SnapshotState.SUPERSEDED, SnapshotState.ACTIVE))
        e = event(d, index=1, replacement=d.snapshots[0].ref)
        e = replace(e, kind=EventKind.SUPERSEDE)
        self.reject(with_events(d, (e,)), "CONTRADICTORY_EVENT")

    def test_integer_revisions_do_not_use_lexicographic_order(self):
        d = ledger(2)
        r = replace(d.snapshots[1].ref, revision=10)
        d = replace(d, snapshots=(d.snapshots[0], replace(d.snapshots[1], ref=r)),
            evidence=(d.evidence[0], replace(d.evidence[1], ref=r)))
        self.reject(with_events(d, (event(d, kind=EventKind.SUPERSEDE),)), "SUPERSEDED", Readiness.INSUFFICIENT)
        for value in ("10", True, 1.0):
            ref = replace(r)
            object.__setattr__(ref, "revision", value)
            self.reject(replace(d, snapshots=(replace(d.snapshots[0], ref=ref),)), "INVALID_SCHEMA")

    def test_duplicate_snapshot_id_and_revision_ambiguity(self):
        d = ledger(2)
        self.reject(replace(d, snapshots=(d.snapshots[0], d.snapshots[0])), "IDENTITY_REUSE")
        s = replace(d.snapshots[1], ref=replace(d.snapshots[1].ref, revision=0))
        self.reject(replace(d, snapshots=(d.snapshots[0], s)), "REVISION_AMBIGUITY")

    def test_duplicate_event_id_is_replay(self):
        d = ledger(2)
        e = event(d)
        self.reject(with_events(d, (e, replace(event(d, 1), event_id=e.event_id))), "REPLAY")

    def test_same_snapshot_multiple_terminal_events_are_contradictory(self):
        d = ledger()
        d = replace(d, resources=replace(d.resources, max_events=2, max_references=2))
        e = event(d)
        self.reject(with_events(d, (e, replace(e, event_id="other-event", issued_at=BASE - 1))), "CONTRADICTORY_EVENT")

    def test_same_time_distinct_snapshots_have_deterministic_order(self):
        d = ledger(2)
        events = (event(d), event(d, 1))
        self.reject(with_events(d, events), "REVOKED", Readiness.INSUFFICIENT)
        self.reject(with_events(d, events[::-1]), "UNORDERED_EVENTS")

    def test_unordered_event_issue_times_rejected(self):
        d = ledger(2)
        events = (event(d, issued_at=BASE - 1), event(d, 1, issued_at=BASE - 2))
        self.reject(with_events(d, events), "UNORDERED_EVENTS")

    def test_snapshot_and_claim_presentation_order_does_not_change_output(self):
        d = ledger(3)
        self.assertEqual(assess_lifecycle(d), assess_lifecycle(replace(d,
            snapshots=d.snapshots[::-1], evidence=d.evidence[::-1])))

    def test_each_scope_field_is_bound_on_every_reference(self):
        d = ledger()
        for name in ("owner_id", "source_id", "version"):
            for kind in ("snapshot", "event", "claim"):
                with self.subTest(field=name, kind=kind):
                    ref = replace(d.snapshots[0].ref, **{name: "other"})
                    if kind == "snapshot":changed = replace(d, snapshots=(replace(d.snapshots[0], ref=ref),))
                    elif kind == "event":changed = with_events(d, (replace(event(d), ref=ref),))
                    else:changed = replace(d, evidence=(replace(d.evidence[0], ref=ref),))
                    self.reject(changed, "SCOPE_MISMATCH")

    def test_unknown_event_or_revision_reference_rejected(self):
        d = ledger()
        for changes in ({"snapshot_id": "missing"}, {"revision": 50}):
            ref = replace(d.snapshots[0].ref, **changes)
            self.reject(with_events(d, (replace(event(d), ref=ref),)), "REFERENCE_MISMATCH")

    def test_revoke_cannot_claim_replacement(self):
        d = ledger(2)
        self.reject(with_events(d, (event(d, replacement=d.snapshots[1].ref),)), "CONTRADICTORY_EVENT")

    def test_missing_supersession_target_and_unknown_target_rejected(self):
        d = ledger(2)
        for target in (None, replace(d.snapshots[1].ref, snapshot_id="missing")):
            self.reject(with_events(d, (event(d, kind=EventKind.SUPERSEDE, replacement=target),)), "REFERENCE_MISMATCH")

    def test_expired_or_unavailable_successor_cannot_replace(self):
        d = ledger(2)
        e = event(d, kind=EventKind.SUPERSEDE)
        for changes in ({"expires_at": BASE}, {"available_at": BASE}, {"valid_from": BASE + 1}):
            changed = replace(d, snapshots=(d.snapshots[0], replace(d.snapshots[1], **changes)))
            self.reject(with_events(changed, (e,)), "CONTRADICTORY_EVENT")

    def test_supersession_merge_and_reverse_temporal_chain_rejected(self):
        d = ledger(3)
        events = (event(d, kind=EventKind.SUPERSEDE, replacement=d.snapshots[2].ref),
            event(d, 1, kind=EventKind.SUPERSEDE))
        self.reject(with_events(d, events), "CONTRADICTORY_EVENT")
        events = (event(d, kind=EventKind.SUPERSEDE), event(d, 1, issued_at=BASE - 1))
        self.reject(with_events(d, events), "CONTRADICTORY_EVENT")

    def test_forward_terminal_chain_does_not_reactivate_snapshot(self):
        d = ledger(3)
        events = (event(d, kind=EventKind.SUPERSEDE, effective_at=BASE - 2),
            event(d, 1, issued_at=BASE - 1, effective_at=BASE))
        out = self.reject(with_events(d, events), "SUPERSEDED", Readiness.INSUFFICIENT)
        self.assertIn("REVOKED", out.reasons)

    def test_complete_event_reference_list_must_match_exactly(self):
        d = ledger()
        self.reject(replace(d, evidence=(replace(d.evidence[0], event_ids=("missing",)),)), "REFERENCE_MISMATCH")
        self.reject(replace(d, events=(event(d),)), "REFERENCE_MISMATCH")

    def test_duplicate_event_reference_is_replay(self):
        d = ledger()
        d = replace(d, resources=replace(d.resources, max_references=2))
        e = event(d)
        self.reject(replace(with_events(d, (e,)), evidence=(replace(d.evidence[0], event_ids=(e.event_id, e.event_id)),)), "REPLAY")

    def test_missing_snapshot_or_completeness_evidence_is_insufficient(self):
        self.reject(ledger(0), "MISSING_SNAPSHOTS", Readiness.INSUFFICIENT)
        d = ledger()
        self.reject(replace(d, evidence=()), "MISSING_EVIDENCE", Readiness.INSUFFICIENT)
        self.reject(replace(d, snapshots=(replace(d.snapshots[0], identity=None),)), "MISSING_EVIDENCE", Readiness.INSUFFICIENT)

    def test_unknown_and_incomplete_ledger_never_prove_absence(self):
        d = ledger()
        for state in (Completeness.UNKNOWN, Completeness.INCOMPLETE):
            self.reject(replace(d, evidence=(replace(d.evidence[0], completeness=state),)), state.value, Readiness.INSUFFICIENT)

    def test_stale_observation_rejected_without_grace(self):
        d = ledger()
        self.reject(replace(d, evidence=(replace(d.evidence[0], observed_at=BASE - 1),)), "STALE_EVIDENCE", Readiness.INSUFFICIENT)

    def test_completeness_expiry_is_exclusive(self):
        d = ledger(evaluation_time=BASE + 10)
        self.reject(d, "EXPIRED", Readiness.INSUFFICIENT)
        d = ledger()
        claim = replace(d.evidence[0], observed_at=BASE - 1, available_at=BASE - 1, expires_at=BASE)
        self.reject(replace(d, evidence=(claim,)), "STALE_EVIDENCE", Readiness.INSUFFICIENT)

    def test_future_snapshot_claim_and_event_unavailable(self):
        d = ledger()
        self.reject(replace(d, snapshots=(replace(d.snapshots[0], available_at=BASE + 1),),
            evidence=(replace(d.evidence[0], available_at=BASE + 1),)), "FUTURE_UNAVAILABLE", Readiness.INSUFFICIENT)
        self.reject(replace(d, evidence=(replace(d.evidence[0], observed_at=BASE + 1, available_at=BASE + 1),)), "FUTURE_UNAVAILABLE", Readiness.INSUFFICIENT)
        self.reject(with_events(d, (event(d, available_at=BASE + 1),)), "FUTURE_UNAVAILABLE", Readiness.INSUFFICIENT)

    def test_impossible_time_relationships_rejected(self):
        d = ledger()
        for changes in ({"observed_at": BASE}, {"valid_from": BASE + 10}):
            self.reject(replace(d, snapshots=(replace(d.snapshots[0], **changes),)), "INVALID_TIME")
        for changes in ({"issued_at": BASE - 6}, {"available_at": BASE - 3}, {"effective_at": BASE - 3}):
            self.reject(with_events(d, (event(d, **changes),)), "INVALID_TIME")

    def test_evidence_purpose_source_version_and_authority_required(self):
        d = ledger()
        for changes in ({"assertion": "OTHER"}, {"source_id": "other"}, {"revision": "v2"}, {"basis": "AUTHENTICATED"}):
            self.reject(replace(d, evidence=(replace(d.evidence[0], identity=replace(d.evidence[0].identity, **changes)),)), "INVALID_EVIDENCE")

    def test_evidence_identity_reuse_rejected_even_when_caller_claims_validity(self):
        d = ledger(2)
        proof2 = replace(d.evidence[1].identity, identity=d.evidence[0].identity.identity)
        self.reject(replace(d, evidence=(d.evidence[0], replace(d.evidence[1], identity=proof2))), "IDENTITY_REUSE")

    def test_foreign_nested_comparisons_never_called(self):
        class Foreign:
            def __eq__(self, other):raise AssertionError("foreign comparison")
            __ne__ = __eq__
            def __lt__(self, other):raise AssertionError("foreign ordering")
        for target in ("scope", "ref", "revision", "basis", "kind", "event_id", "reference"):
            d = ledger()
            if target == "scope":object.__setattr__(d, "owner_id", Foreign())
            elif target == "ref":object.__setattr__(d.snapshots[0], "ref", Foreign())
            elif target == "revision":object.__setattr__(d.snapshots[0].ref, "revision", Foreign())
            elif target == "basis":object.__setattr__(d.evidence[0].identity, "basis", Foreign())
            elif target == "reference":object.__setattr__(d.evidence[0], "event_ids", (Foreign(),))
            else:
                e = event(d);object.__setattr__(e, target, Foreign());d = replace(d, events=(e,))
            with self.subTest(target=target):self.reject(d, "INVALID_SCHEMA")

    def test_deleted_nested_fields_fail_closed(self):
        for target in ("resources", "ref", "identity", "claim", "event"):
            d = ledger()
            e = event(d);d = with_events(d, (e,))
            obj, name = {"resources": (d.resources, "max_events"), "ref": (d.snapshots[0].ref, "revision"),
                "identity": (d.evidence[0].identity, "assertion"), "claim": (d.evidence[0], "event_ids"),
                "event": (e, "issued_at")}[target]
            object.__delattr__(obj, name)
            with self.subTest(target=target):self.reject(d, "INVALID_SCHEMA")

    def test_mutable_collections_and_wrong_enum_shapes_rejected(self):
        for name in ("snapshots", "events", "evidence"):
            d = ledger();object.__setattr__(d, name, [])
            self.reject(d, "INVALID_SCHEMA")
        d = ledger();object.__setattr__(d.evidence[0], "completeness", "COMPLETE")
        self.reject(d, "INVALID_SCHEMA")

    def test_constructor_exact_primitive_types(self):
        d = ledger()
        for call in (lambda: replace(d, evaluation_time=True), lambda: replace(d.snapshots[0].ref, revision="1"),
                lambda: replace(d.resources, max_events=True), lambda: replace(d.evidence[0], event_ids=[]),
                lambda: replace(event(d), kind="REVOKE")):
            with self.assertRaises(ValueError):call()

    def test_negative_timestamps_and_revisions_rejected(self):
        self.reject(ledger(evaluation_time=-1), "INVALID_TIME")
        d = ledger();r = replace(d.snapshots[0].ref, revision=-1)
        self.reject(replace(d, snapshots=(replace(d.snapshots[0], ref=r),)), "INVALID_TIME")

    def test_all_caller_budget_dimensions_enforced(self):
        d = ledger();d = with_events(d, (event(d),))
        for name in d.resources.__dataclass_fields__:
            with self.subTest(budget=name):
                self.reject(replace(d, resources=replace(d.resources, **{name: 0})), "RESOURCE_BUDGET_EXCEEDED")

    def test_counts_gate_nested_walks_before_malformed_items(self):
        d = ledger();object.__setattr__(d, "events", (object(),) * 256)
        self.reject(d, "RESOURCE_BUDGET_EXCEEDED")
        d = ledger();object.__setattr__(d.evidence[0], "event_ids", (object(),) * 256)
        self.reject(d, "RESOURCE_BUDGET_EXCEEDED")

    def test_exact_record_reference_and_integer_budgets(self):
        d = with_events(ledger(), (event(ledger()),))
        bits = (BASE + 10).bit_length()
        d = replace(d, resources=LifecycleResources(1, 1, 1, 100000, bits))
        self.reject(d, "REVOKED", Readiness.INSUFFICIENT)
        self.reject(replace(d, resources=replace(d.resources, max_integer_bits=bits - 1)), "RESOURCE_BUDGET_EXCEEDED")

    def test_exact_text_budget_boundary(self):
        # Independent fixture charge: scope once; each supplied reference/identity at each use.
        d = ledger()
        def ref_chars(r):return sum(len(getattr(r, n)) for n in ("owner_id", "source_id", "version", "snapshot_id"))
        def proof_chars(p):return sum(len(getattr(p, n)) for n in ("identity", "source_id", "revision", "assertion", "basis"))
        chars = sum(len(getattr(d, n)) for n in ("owner_id", "source_id", "version"))
        chars += sum(ref_chars(r.ref) + proof_chars(r.identity) for r in d.snapshots + d.evidence)
        self.assertEqual(assess_lifecycle(replace(d, resources=replace(d.resources, max_text_chars=chars))).status, Readiness.SUFFICIENT)
        self.reject(replace(d, resources=replace(d.resources, max_text_chars=chars - 1)), "RESOURCE_BUDGET_EXCEEDED")

    def test_large_revision_and_long_identity_refused_by_budget(self):
        d = ledger();object.__setattr__(d.snapshots[0].ref, "revision", 1 << 256)
        self.reject(d, "RESOURCE_BUDGET_EXCEEDED")
        self.reject(ledger(owner_id="a" * 200), "INVALID_IDENTITY")

    def test_output_invariants_foreign_reason_and_hidden_failure(self):
        with self.assertRaises(ValueError):LifecycleDiagnostic(Readiness.SUFFICIENT)
        with self.assertRaises(ValueError):LifecycleDiagnostic(Readiness.INSUFFICIENT, ("INVALID_SCHEMA",))
        row = SnapshotDiagnostic("snapshot-000", 0, SnapshotState.REVOKED)
        with self.assertRaises(ValueError):LifecycleDiagnostic(Readiness.SUFFICIENT, snapshots=(row,))
        with self.assertRaises(ValueError):LifecycleDiagnostic(Readiness.INSUFFICIENT, ("REVOKED",), ())
        class Foreign:
            def __eq__(self, other):raise AssertionError("foreign diagnostic")
        with self.assertRaises(ValueError):LifecycleDiagnostic(Readiness.INVALID, (Foreign(),))

    def test_tampered_nested_diagnostic_revalidated(self):
        out = assess_lifecycle(ledger());row = out.snapshots[0]
        object.__setattr__(row, "state", "ACTIVE")
        with self.assertRaises(ValueError):replace(out)

    def test_immutable_records_and_truth_refusal(self):
        d = ledger();out = assess_lifecycle(d)
        for obj, name in ((d, "owner_id"), (d.snapshots[0], "ref"), (out, "status")):
            with self.assertRaises(FrozenInstanceError):setattr(obj, name, None)
        for obj in (out, out.snapshots[0]):
            with self.assertRaises(TypeError):bool(obj)

    def test_no_io_or_risk_engine_consumer(self):
        with patch("builtins.open", side_effect=AssertionError("I/O")), patch("io.open", side_effect=AssertionError("I/O")), \
                patch("sqlite3.connect", side_effect=AssertionError("database")), patch("socket.socket", side_effect=AssertionError("network")), \
                patch("demo_futures.risk.size_position", side_effect=AssertionError("sizing")):
            self.assertEqual(assess_lifecycle(ledger()).status, Readiness.SUFFICIENT)

    def test_static_dependencies_are_only_immutable_contract_vocabulary(self):
        path = Path(__file__).resolve().parents[1] / "src/demo_futures/risk_remediation/snapshot_lifecycle_contract.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertEqual(modules, {"dataclasses", "enum", "research_v2.contracts"})
        self.assertFalse(any(isinstance(n, ast.Import) for n in ast.walk(tree)))
        calls = {n.func.id if isinstance(n.func, ast.Name) else n.func.attr for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, (ast.Name, ast.Attribute))}
        self.assertFalse(calls & {"open", "connect", "request", "size_position", "fit", "predict", "assess_inventory", "assess_plan_budget"})
