"""M7 acceptance/adversarial fixtures: invented 2010 declarations only."""
from dataclasses import FrozenInstanceError, replace
from decimal import DefaultContext, getcontext, localcontext
import unittest
from unittest.mock import patch

from demo_futures.research_v2.contracts import Readiness
from demo_futures.risk_remediation import content_commitment_session as m7
from demo_futures.risk_remediation import inventory_content_commitment as m6
from test_inventory_content_commitment import limits as encoding_limits, FULL_GOLDENS
from test_risk_inventory_lifecycle_binding import binding, with_lifecycle
from test_risk_snapshot_lifecycle_contract import event, with_events, ledger
from demo_futures.risk_remediation.snapshot_lifecycle_contract import EventKind
from test_risk_funding_budget import BASE

SAMPLE = {}


def raw_at(delta=0, revision=0, snapshot=None):
    raw = binding(0)
    i, l, a = raw.inventory, raw.lifecycle, raw.association
    snapshot = i.snapshot_id if snapshot is None else snapshot
    ref = replace(l.snapshots[0].ref, snapshot_id=snapshot, revision=revision)
    i = replace(i, snapshot_id=snapshot, evaluation_time=BASE + delta, expires_at=BASE + 10,
        completeness_assertion=replace(i.completeness_assertion, snapshot_id=snapshot),
        joint_assertion=replace(i.joint_assertion, snapshot_id=snapshot))
    l = replace(l, evaluation_time=BASE + delta, snapshots=(replace(l.snapshots[0], ref=ref),),
        evidence=(replace(l.evidence[0], ref=ref, observed_at=BASE + delta, available_at=BASE + delta),))
    return replace(raw, inventory=i, lifecycle=l, association=replace(a, snapshot_id=snapshot,
        revision=revision, evaluation_time=BASE + delta))


def observation(sequence=0, raw=None, claim=True, **changes):
    raw = raw_at(sequence) if raw is None else raw
    resources = encoding_limits()
    manifest = m6.commit_content(raw, resources).manifest if claim else None
    return replace(m7.ObservationDeclaration(f"observation-{sequence}", sequence,
        raw.association.evaluation_time if raw.association is not None else BASE,
        raw, resources, manifest), **changes)


def resources(count):
    enc = encoding_limits()
    return m7.TranscriptResources(count, 100000, 128, enc,
        enc.max_nodes * count, enc.max_string_codepoints * count, enc.max_string_bytes * count,
        enc.max_decimal_digits * count, enc.max_canonical_bytes * count)


def transcript(count=2):
    rows = tuple(observation(i) for i in range(count))
    raw = rows[-1].raw_binding
    return m7.TranscriptDeclaration("invented-session", raw.association.owner_id,
        raw.association.source_id, raw.association.version, BASE + count - 1,
        rows[:-1], rows[-1], resources(count))


def forged(value, **changes):
    copy = object.__new__(type(value))
    for name in value.__dataclass_fields__:
        object.__setattr__(copy, name, changes.get(name, getattr(value, name)))
    return copy


class TranscriptTests(unittest.TestCase):
    def check(self, d, status=Readiness.SUFFICIENT, reason=None):
        out = m7.assess_transcript(d)
        self.assertIs(out.status, status)
        if reason is not None:
            self.assertIn(reason, out.reasons)
        if status is not Readiness.SUFFICIENT:
            self.assertIsNone(out.candidate_manifest)
        return out

    def test_valid_prefix_and_determinism(self):
        d = transcript(3)
        a = self.check(d)
        self.assertEqual(a, self.check(d))
        self.assertEqual(tuple(r.observation_id for r in a.observations), tuple(r.observation_id for r in d.prior) + (d.candidate.observation_id,))
        self.assertIs(a.candidate_manifest, a.observations[-1].commitment.manifest)
        SAMPLE.update(digest=a.candidate_manifest.digest, byte_length=a.candidate_manifest.byte_length,
            status=a.status.value, reasons=a.reasons, sequences=tuple(r.sequence for r in a.observations))

    def test_empty_prefix_does_not_verify_external_history(self):
        out = self.check(transcript(1))
        self.assertEqual(out.history_scope, "SUPPLIED_TRANSCRIPT_ONLY")
        self.assertEqual((out.external_provenance, out.external_replay_authority), ("NOT VERIFIED", "NOT VERIFIED"))
        self.assertEqual(out.aggregate_state, "BLOCKED")
        self.assertEqual(out.risk_clearance, "NOT CLEARED")

    def test_missing_claim_recomputes_once_and_keeps_complete_result(self):
        d = transcript();d = replace(d, candidate=replace(d.candidate, claimed_manifest=None))
        actual = m6.commit_content
        with patch.object(m6, "commit_content", wraps=actual) as calls:
            out = self.check(d, Readiness.INSUFFICIENT, "MISSING_CLAIM")
        self.assertEqual(calls.call_count, 2)
        self.assertIs(out.observations[-1].commitment.status, Readiness.SUFFICIENT)
        self.assertIsNotNone(out.observations[-1].commitment.binding.inventory)

    def test_every_claim_field_compared_and_recalculation_retained(self):
        for name in m7.MANIFEST_FIELDS:
            d = transcript(1);claim=d.candidate.claimed_manifest;old=getattr(claim,name)
            new=old+1 if type(old) is int else ("0" if old[0] != "0" else "1")+old[1:] if name=="digest" else old+"x"
            claim=forged(claim,**{name:new})
            reason="UNSUPPORTED_VERSION" if name in ("schema","algorithm") else "CLAIM_MISMATCH"
            with self.subTest(field=name):
                out=self.check(replace(d,candidate=replace(d.candidate,claimed_manifest=claim)),Readiness.INVALID,reason)
                self.assertIs(out.observations[0].commitment.status,Readiness.SUFFICIENT)

    def test_malformed_claim_values_retain_safe_reassessment(self):
        d=transcript(1)
        for changes in ({"digest":"BAD"},{"byte_length":0},{"owner_id":""},
                {"byte_length":-1},{"revision":-1},{"evaluation_time":-1}):
            with self.subTest(changes=changes):
                out=self.check(replace(d,candidate=replace(d.candidate,claimed_manifest=forged(d.candidate.claimed_manifest,**changes))),Readiness.INVALID,"CLAIM_MISMATCH")
                self.assertIsNotNone(out.observations[0].commitment)

    def test_scope_mismatch(self):
        for name in m7.SCOPE:
            with self.subTest(field=name):self.check(replace(transcript(),**{name:"other"}),Readiness.INVALID,"SCOPE_MISMATCH")

    def test_duplicate_ids_mark_all_members(self):
        d=transcript();d=replace(d,candidate=replace(d.candidate,observation_id=d.prior[0].observation_id))
        out=self.check(d,Readiness.INVALID,"DUPLICATE_OBSERVATION_ID")
        self.assertTrue(all("DUPLICATE_OBSERVATION_ID" in r.reasons for r in out.observations))

    def test_sequence_gaps_repeats_and_order_not_repaired(self):
        for sequence in (0,2):
            d=transcript();self.check(replace(d,candidate=replace(d.candidate,sequence=sequence)),Readiness.INVALID,"SEQUENCE_MISMATCH")
        d=transcript(3)
        self.check(replace(d,prior=tuple(reversed(d.prior))),Readiness.INVALID,"SEQUENCE_MISMATCH")

    def test_conflict_marks_all_including_repeated_first_commitment(self):
        raw=raw_at();other=replace(raw,resources=replace(raw.resources,max_text_chars=10001))
        rows=(observation(0,raw),observation(1,raw),observation(2,other))
        d=replace(transcript(3),evaluation_time=BASE,prior=rows[:2],candidate=rows[2])
        out=self.check(d,Readiness.INVALID,"CONTEXT_CONTENT_CONFLICT")
        self.assertTrue(all("CONTEXT_CONTENT_CONFLICT" in r.reasons for r in out.observations))
        self.assertNotIn("CONTEXT_REPLAY",out.reasons)

    def test_same_context_replay_only_later_member(self):
        raw=raw_at();d=replace(transcript(),evaluation_time=BASE,prior=(observation(0,raw),),candidate=observation(1,raw))
        out=self.check(d,Readiness.INSUFFICIENT,"CONTEXT_REPLAY")
        self.assertNotIn("CONTEXT_REPLAY",out.observations[0].reasons)
        self.assertIn("CONTEXT_REPLAY",out.observations[1].reasons)

    def test_outer_encoding_budget_change_not_new_content(self):
        raw=raw_at();first=observation(0,raw);second=observation(1,raw)
        second=replace(second,encoding_resources=replace(second.encoding_resources,max_nodes=99999))
        d=replace(transcript(),evaluation_time=BASE,prior=(first,),candidate=second)
        self.check(d,Readiness.INSUFFICIENT,"CONTEXT_REPLAY")

    def test_later_snapshot_evaluation_is_distinct_context(self):
        out=self.check(transcript())
        self.assertNotEqual(out.observations[0].commitment.manifest.digest,out.observations[1].commitment.manifest.digest)

    def test_snapshot_revision_and_time_association_conflicts(self):
        d=transcript();candidate=observation(1,raw_at(1,revision=1))
        out=self.check(replace(d,candidate=candidate),Readiness.INVALID,"SNAPSHOT_ASSOCIATION_CONFLICT")
        self.assertTrue(all("SNAPSHOT_ASSOCIATION_CONFLICT" in r.reasons for r in out.observations))
        raw=raw_at(1);i,l,a=raw.inventory,raw.lifecycle,raw.association
        raw=replace(raw,inventory=replace(i,snapshot_time=BASE-1,completeness_assertion=replace(i.completeness_assertion,snapshot_time=BASE-1)),
            lifecycle=replace(l,snapshots=(replace(l.snapshots[0],observed_at=BASE-1),)),association=replace(a,snapshot_time=BASE-1))
        self.check(replace(d,candidate=observation(1,raw)),Readiness.INVALID,"SNAPSHOT_ASSOCIATION_CONFLICT")

    def test_revision_cannot_name_two_snapshots(self):
        d=transcript();candidate=observation(1,raw_at(1,snapshot="snapshot-other"))
        out=self.check(replace(d,candidate=candidate),Readiness.INVALID,"REVISION_IDENTITY_CONFLICT")
        self.assertTrue(all("REVISION_IDENTITY_CONFLICT" in r.reasons for r in out.observations))

    def test_higher_revision_does_not_imply_supersession(self):
        d=transcript();self.check(replace(d,candidate=observation(1,raw_at(1,revision=7,snapshot="other"))))

    def test_stale_candidate_and_future_availability(self):
        d=transcript(1)
        self.check(replace(d,evaluation_time=BASE+1),Readiness.INSUFFICIENT,"STALE_CONTEXT")
        self.check(replace(d,candidate=replace(d.candidate,available_at=BASE+1)),Readiness.INSUFFICIENT,"FUTURE_UNAVAILABLE")
        future=observation(0,raw_at(1));self.check(replace(d,candidate=future),Readiness.INSUFFICIENT,"FUTURE_UNAVAILABLE")
        self.check(replace(d,candidate=replace(d.candidate,available_at=BASE-1)),Readiness.INVALID,"INVALID_TIME")

    def test_chronology_and_content_conflict_combine(self):
        raw=raw_at();changed=replace(raw,resources=replace(raw.resources,max_text_chars=10001))
        first=observation(0,raw,available_at=BASE+1);second=observation(1,changed,available_at=BASE)
        d=replace(transcript(),evaluation_time=BASE,prior=(first,),candidate=second)
        out=self.check(d,Readiness.INVALID,"CONTEXT_CONTENT_CONFLICT")
        self.assertIn("UNORDERED_OBSERVATIONS",out.reasons)
        self.assertIn("FUTURE_UNAVAILABLE",out.reasons)

    def test_nonmonotonic_evaluation_chronology_combines_stale(self):
        d=transcript();d=replace(d,prior=(observation(0,raw_at(1),available_at=BASE+1),),candidate=observation(1,raw_at(),available_at=BASE+1))
        out=self.check(d,Readiness.INVALID,"UNORDERED_OBSERVATIONS")
        self.assertIn("STALE_CONTEXT",out.reasons)

    def test_invalid_and_insufficient_children_all_recomputed(self):
        d=transcript();raw=replace(d.prior[0].raw_binding,association=None)
        first=replace(d.prior[0],raw_binding=raw,claimed_manifest=None)
        bad=forged(d.candidate.raw_binding,inventory=object())
        d=replace(d,prior=(first,),candidate=replace(d.candidate,raw_binding=bad))
        actual=m6.commit_content
        with patch.object(m6,"commit_content",wraps=actual) as calls:out=self.check(d,Readiness.INVALID,"M6_INVALID")
        self.assertEqual(calls.call_count,2)
        self.assertIn("M6_INSUFFICIENT",out.reasons)
        self.assertIsNotNone(out.observations[0].commitment.binding.inventory)
        self.assertIsNotNone(out.observations[1].commitment)

    def test_revoked_expired_superseded_and_whole_lifecycle_failures(self):
        for kind in ("revoked","expired","superseded","stale"):
            raw=raw_at();l=raw.lifecycle
            if kind=="revoked":l=with_events(l,(event(l,issued_at=BASE,available_at=BASE),))
            elif kind=="expired":l=replace(l,snapshots=(replace(l.snapshots[0],expires_at=BASE),))
            elif kind=="stale":
                raw=raw_at(1);l=raw.lifecycle
                l=replace(l,evidence=(replace(l.evidence[0],observed_at=BASE,available_at=BASE),))
            else:
                # Existing complete M4 supersession ledger: active successor
                # cannot make the whole result sufficient.
                l=ledger(2);l=with_events(l,(event(l,kind=EventKind.SUPERSEDE),))
            raw=with_lifecycle(raw,l);row=observation(0,raw,claim=False)
            with self.subTest(kind=kind):
                out=self.check(replace(transcript(1),candidate=row,evaluation_time=row.available_at),Readiness.INSUFFICIENT,"M6_INSUFFICIENT")
                self.assertIsNotNone(out.observations[0].commitment.binding.lifecycle)

    def test_raw_safe_reorder_preserves_commitment_and_replay(self):
        raw=binding(2);i=raw.inventory
        shuffled=replace(raw,inventory=replace(i,required_position_ids=tuple(reversed(i.required_position_ids)),plans=tuple(reversed(i.plans)),envelopes=tuple(reversed(i.envelopes)),bindings=tuple(reversed(i.bindings))))
        d=replace(transcript(),evaluation_time=BASE,prior=(observation(0,raw),),candidate=observation(1,shuffled))
        self.check(d,Readiness.INSUFFICIENT,"CONTEXT_REPLAY")

    def test_mandatory_lifecycle_order_not_repaired(self):
        raw=raw_at();l=ledger(2)
        l=with_events(l,(event(l,index=0,event_id="b"),event(l,index=1,event_id="a")))
        raw=with_lifecycle(raw,l)
        out=self.check(replace(transcript(1),candidate=observation(0,raw,claim=False)),Readiness.INVALID,"M6_INVALID")
        self.assertIn("UNORDERED_EVENTS",out.observations[0].commitment.binding.lifecycle.reasons)

    def test_resource_configuration_and_per_call_ceiling_before_m6(self):
        for field in m7.RESOURCE_FIELDS:
            if field=="per_observation_ceiling":continue
            for bad in (-1,True,1<<64,object()):
                d=transcript(1);object.__setattr__(d.resources,field,bad)
                with self.subTest(field=field),patch.object(m6,"commit_content",side_effect=AssertionError("early M6")):
                    self.check(d,Readiness.INVALID,"INVALID_SCHEMA")
        for field in m7.ENCODING_FIELDS:
            d=transcript(1)
            object.__setattr__(d.resources.per_observation_ceiling,field,getattr(d.candidate.encoding_resources,field)-1)
            with self.subTest(encoding=field),patch.object(m6,"commit_content",side_effect=AssertionError("early M6")):
                self.check(d,Readiness.INVALID,"RESOURCE_BUDGET_EXCEEDED")

    def test_aggregate_exact_and_one_below_every_dimension(self):
        d=transcript();self.check(d)
        for name in m7.TOTAL_FIELDS:
            field=name.replace("max_","max_total_",1)
            bad=replace(d.resources,**{field:getattr(d.resources,field)-1})
            with self.subTest(field=field),patch.object(m6,"commit_content",side_effect=AssertionError("early M6")):
                self.check(replace(d,resources=bad),Readiness.INVALID,"RESOURCE_BUDGET_EXCEEDED")
        self.check(replace(d,resources=replace(d.resources,max_observations=1)),Readiness.INVALID,"RESOURCE_BUDGET_EXCEEDED")

    def test_metadata_text_and_integer_exact_boundaries(self):
        d=transcript(1)
        text=sum(len(getattr(d,n)) for n in ("session_id",)+m7.SCOPE)+len(d.candidate.observation_id)
        text+=sum(len(getattr(d.candidate.claimed_manifest,n)) for n in m7.MANIFEST_FIELDS if type(getattr(d.candidate.claimed_manifest,n)) is str)
        bits=BASE.bit_length()
        exact=replace(d.resources,max_metadata_chars=text,max_integer_bits=bits)
        self.check(replace(d,resources=exact))
        for changes in ({"max_metadata_chars":text-1},{"max_integer_bits":bits-1}):
            self.check(replace(d,resources=replace(exact,**changes)),Readiness.INVALID,"RESOURCE_BUDGET_EXCEEDED")

    def test_hostile_fields_never_invoke_foreign_hooks(self):
        class Meta(type):
            def __eq__(self,other):raise AssertionError("metaclass eq")
            def __hash__(self):raise AssertionError("metaclass hash")
        class Foreign(metaclass=Meta):
            def __eq__(self,other):raise AssertionError("eq")
            def __lt__(self,other):raise AssertionError("lt")
            def __bool__(self):raise AssertionError("bool")
        for group,names in (("declaration",m7.TRANSCRIPT_FIELDS),("row",m7.OBSERVATION_FIELDS),("claim",m7.MANIFEST_FIELDS),("encoding",m7.ENCODING_FIELDS),("resources",m7.RESOURCE_FIELDS)):
            for name in names:
                d=transcript(1);target={"declaration":d,"row":d.candidate,"claim":d.candidate.claimed_manifest,"encoding":d.candidate.encoding_resources,"resources":d.resources}[group]
                object.__setattr__(target,name,Foreign())
                with self.subTest(group=group,field=name),patch.object(m6,"commit_content",side_effect=AssertionError("early M6")):
                    self.check(d,Readiness.INVALID,"INVALID_SCHEMA")

    def test_missing_fields_subclasses_and_supplied_diagnostics_rejected(self):
        d=transcript(1);object.__delattr__(d.candidate,"available_at")
        self.check(d,Readiness.INVALID,"INVALID_SCHEMA")
        d=transcript(1);object.__setattr__(d.candidate,"raw_binding",m6.commit_content(raw_at(),encoding_limits()))
        self.check(d,Readiness.INVALID,"INVALID_SCHEMA")
        class Sub(m7.ObservationDeclaration):pass
        d=transcript(1);row=d.candidate
        self.check(forged(d,candidate=Sub(*(getattr(row,n) for n in m7.OBSERVATION_FIELDS))),Readiness.INVALID,"INVALID_SCHEMA")

    def test_owned_metadata_and_encoding_limits_used_after_capture(self):
        d=transcript();actual=m6.commit_content;calls=[]
        def assess(raw,limits):
            calls.append(limits)
            object.__setattr__(d.candidate,"observation_id","mutated-original")
            object.__setattr__(d.candidate.encoding_resources,"max_nodes",0)
            return actual(raw,limits)
        with patch.object(m6,"commit_content",side_effect=assess):out=self.check(d)
        self.assertEqual(out.observations[-1].observation_id,"observation-1")
        self.assertTrue(all(limit.max_nodes>0 for limit in calls))

    def test_detectable_metadata_mutation_during_preflight(self):
        d=transcript(1);original=m7._encoding;changed=False
        def intercept(value,observed):
            nonlocal changed
            owned=original(value,observed)
            if value is d.candidate.encoding_resources and not changed:
                object.__setattr__(d.candidate,"sequence",9);changed=True
            return owned
        with patch.object(m7,"_encoding",side_effect=intercept):self.check(d,Readiness.INVALID,"CAPTURE_CHANGED")

    def test_diagnostic_constructor_status_child_and_authority_invariants(self):
        out=self.check(transcript(1));row=out.observations[0]
        for value in (out,row):
            with self.assertRaises(TypeError):bool(value)
            with self.assertRaises(FrozenInstanceError):value.status=Readiness.INVALID
        for reason in m7.REASONS:
            if reason in m7.PREFLIGHT:continue
            with self.subTest(reason=reason),self.assertRaises(ValueError):m7.TranscriptDiagnostic(m7._status((reason,)),(reason,))
        for changes in ({"status":Readiness.INVALID},{"reasons":("CLAIM_MISMATCH",)},{"commitment":None}):
            with self.assertRaises(ValueError):replace(row,**changes)
        with self.assertRaises(ValueError):replace(out,candidate_manifest=None)
        for name,_ in m7.LABELS:
            bad=forged(row,**{name:"FORGED"})
            with self.subTest(label=name),self.assertRaises(ValueError):replace(out,observations=(bad,))
        dependency=forged(row.commitment,authority="FORGED")
        with self.assertRaises(ValueError):replace(row,commitment=dependency)

    def test_success_constructor_rejects_omitted_cross_row_failures(self):
        row=self.check(transcript(1)).observations[0]
        repeated=replace(row,sequence=1,observation_id="different")
        with self.subTest(case="replay"),self.assertRaises(ValueError):
            m7.TranscriptDiagnostic(Readiness.SUFFICIENT,(),(row,repeated),repeated.commitment.manifest)
        out=self.check(transcript());second=replace(out.observations[1],observation_id=out.observations[0].observation_id)
        with self.subTest(case="duplicate_id"),self.assertRaises(ValueError):
            replace(out,observations=(out.observations[0],second))

    def test_bool_negative_and_invalid_identity_metadata(self):
        d=transcript(1)
        for name in ("sequence","available_at"):
            self.check(forged(d,candidate=forged(d.candidate,**{name:True})),Readiness.INVALID,"INVALID_SCHEMA")
        self.check(forged(d,evaluation_time=True),Readiness.INVALID,"INVALID_SCHEMA")
        self.check(replace(d,evaluation_time=-1),Readiness.INVALID,"INVALID_TIME")
        self.check(replace(d,candidate=replace(d.candidate,sequence=-1)),Readiness.INVALID,"INVALID_SCHEMA")
        for changes in ({"session_id":""},{"owner_id":"not valid"}):
            self.check(replace(d,**changes),Readiness.INVALID,"INVALID_IDENTITY")

    def test_omitted_external_history_or_new_session_cannot_be_verified(self):
        original=self.check(transcript(1))
        other=self.check(replace(transcript(1),session_id="another-caller-session"))
        self.assertEqual(original.candidate_manifest,other.candidate_manifest)
        self.assertEqual(other.external_replay_authority,"NOT VERIFIED")

    def test_decimal_context_and_forbidden_io(self):
        d=transcript();expected=m7.assess_transcript(d);saved=DefaultContext.copy()
        try:
            DefaultContext.prec=1
            for flag in DefaultContext.traps:DefaultContext.traps[flag]=True
            with localcontext() as ctx:
                ctx.prec=1
                for flag in ctx.traps:ctx.traps[flag]=True
                flags=dict(ctx.flags)
                with patch('builtins.open',side_effect=AssertionError('IO')):
                    self.assertEqual(m7.assess_transcript(d),expected)
                self.assertEqual(dict(ctx.flags),flags)
        finally:
            DefaultContext.prec=saved.prec;DefaultContext.traps.update(saved.traps)
