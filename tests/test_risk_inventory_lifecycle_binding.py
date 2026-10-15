"""M5 invented 2010 raw declarations; no market/account/engine activity."""
import ast
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal as D, DefaultContext, getcontext, localcontext, ROUND_DOWN
from pathlib import Path
import unittest
from unittest.mock import patch

from demo_futures.research_v2.contracts import Readiness
from demo_futures.research_v2.funding_contracts import CoverageState
from demo_futures.risk_remediation import inventory_lifecycle_binding as module
from demo_futures.risk_remediation.inventory_lifecycle_binding import (
    RevisionAssociation, BindingResources, BindingDeclaration, BindingDiagnostic, assess_binding,
)
from demo_futures.risk_remediation.snapshot_lifecycle_contract import EventKind, Completeness
from test_risk_budget_inventory_contract import inventory, change_raw
from test_risk_snapshot_lifecycle_contract import ledger, event, with_events, proof
from test_risk_funding_budget import BASE, envelope, scenario


def binding(count=2):
    i = inventory(count)
    l = ledger()
    ref = replace(l.snapshots[0].ref, snapshot_id=i.snapshot_id)
    l = replace(l, snapshots=(replace(l.snapshots[0], ref=ref, observed_at=BASE, available_at=BASE),),
        evidence=(replace(l.evidence[0], ref=ref),))
    a = RevisionAssociation(i.owner_id, i.source_id, i.version, i.snapshot_id, ref.revision,
        i.snapshot_time, i.evaluation_time, proof("association-proof", "INVENTORY_LIFECYCLE_ASSOCIATION"),
        proof("provenance-proof", "SYNTHETIC_INVENTORY_PROVENANCE"))
    return BindingDeclaration(i, l, a, BindingResources(i.resources, l.resources, 10000, 128))


def with_lifecycle(d, value):
    return replace(d, lifecycle=value, resources=replace(d.resources, lifecycle_ceiling=value.resources))


class BindingTests(unittest.TestCase):
    def reject(self, d, reason, status=Readiness.INVALID):
        out = assess_binding(d)
        self.assertEqual(out.status, status)
        self.assertIn(reason, out.reasons)
        self.assertEqual(out.aggregate_state, "BLOCKED")
        self.assertEqual(out.risk_clearance, "NOT CLEARED")
        return out

    def test_valid_binding_recomputes_full_raw_results(self):
        d = binding()
        out = assess_binding(d)
        self.assertEqual(out.status, Readiness.SUFFICIENT)
        self.assertEqual(out.positions, module.assess_inventory(d.inventory).positions)
        self.assertEqual(out.lifecycle, module.assess_lifecycle(d.lifecycle))
        self.assertEqual(out.authority, "SYNTHETIC_DIAGNOSTIC_ONLY")
        for name in ("approved", "token", "admission", "total_loss", "portfolio_budget"):
            self.assertFalse(hasattr(out, name))

    def test_each_assessor_runs_once_m4_then_m3(self):
        d = binding();order = []
        m4, m3 = module.assess_lifecycle, module.assess_inventory
        def lifecycle(raw):order.append("M4");return m4(raw)
        def inventory(raw):order.append("M3");return m3(raw)
        with patch.object(module, "assess_lifecycle", side_effect=lifecycle) as a, patch.object(module, "assess_inventory", side_effect=inventory) as b:
            self.assertEqual(assess_binding(d).status, Readiness.SUFFICIENT)
            self.assertEqual((a.call_count,b.call_count), (1,1))
        self.assertEqual(order, ["M4","M3"])

    def test_missing_revision_association_is_insufficient(self):
        out=self.reject(replace(binding(), association=None), "MISSING_ASSOCIATION", Readiness.INSUFFICIENT)
        self.assertEqual(len(out.positions),2)
        self.assertIsNotNone(out.lifecycle)

    def test_revision_must_match_explicit_integer_not_version_text(self):
        d = binding()
        self.reject(replace(d, association=replace(d.association, revision=1)), "REVISION_MISMATCH")
        for value in ("0", True, 0.0, None):
            a = replace(d.association);object.__setattr__(a, "revision", value)
            self.reject(replace(d, association=a), "INVALID_SCHEMA")

    def test_no_revision_association_inferred_from_matching_ids(self):
        d = binding()
        object.__delattr__(d.association, "revision")
        self.reject(d, "INVALID_SCHEMA")

    def test_missing_association_does_not_hide_invalid_child(self):
        d=binding()
        i=change_raw(d.inventory,"plans",0,quantity=D(11))
        out=self.reject(replace(d,inventory=i,association=None),"MISSING_ASSOCIATION")
        self.assertEqual(out.reasons,("M3_INVALID","MISSING_ASSOCIATION"))
        self.assertEqual(len(out.positions),2)

    def test_each_owner_source_version_association_mismatch(self):
        d = binding()
        for name in ("owner_id", "source_id", "version"):
            with self.subTest(field=name):
                self.reject(replace(d, association=replace(d.association, **{name:"other"})), "SCOPE_MISMATCH")

    def test_snapshot_id_association_mismatch(self):
        d = binding()
        self.reject(replace(d, association=replace(d.association, snapshot_id="missing")), "SNAPSHOT_MISMATCH")

    def test_lifecycle_missing_associated_snapshot_is_rejected(self):
        d = binding();l = ledger()
        self.reject(with_lifecycle(d,l), "SNAPSHOT_MISMATCH")

    def test_evaluation_and_snapshot_time_binding(self):
        d = binding()
        for name in ("evaluation_time", "snapshot_time"):
            self.reject(replace(d, association=replace(d.association, **{name:BASE-1})), "TIME_MISMATCH")
        l = replace(d.lifecycle, evaluation_time=BASE+1,
            evidence=(replace(d.lifecycle.evidence[0], observed_at=BASE+1, available_at=BASE+1),))
        self.reject(with_lifecycle(d,l), "TIME_MISMATCH")

    def test_snapshot_observation_must_match_inventory_snapshot_time(self):
        d = binding();l=replace(d.lifecycle, snapshots=(replace(d.lifecycle.snapshots[0], observed_at=BASE-1),))
        self.reject(with_lifecycle(d,l), "TIME_MISMATCH")

    def test_missing_association_or_provenance_proof_preserves_m3_positions(self):
        d = binding()
        for name in ("identity", "provenance"):
            out = self.reject(replace(d, association=replace(d.association, **{name:None})), "MISSING_EVIDENCE", Readiness.INSUFFICIENT)
            self.assertEqual(len(out.positions),2)

    def test_purpose_source_revision_and_authority_are_checked(self):
        d = binding()
        for changes in ({"assertion":"OTHER"},{"source_id":"other"},{"revision":"v2"},{"basis":"AUTHENTICATED"}):
            self.reject(replace(d, association=replace(d.association, identity=replace(d.association.identity, **changes))), "INVALID_EVIDENCE")

    def test_duplicate_association_provenance_identity_rejected(self):
        d = binding();p=replace(d.association.provenance,identity=d.association.identity.identity)
        self.reject(replace(d,association=replace(d.association,provenance=p)),"DUPLICATE_IDENTITY")

    def test_revoked_lifecycle_keeps_inventory_result(self):
        d = binding();out=self.reject(with_lifecycle(d,with_events(d.lifecycle,(event(d.lifecycle,issued_at=BASE,available_at=BASE),))),"M4_INSUFFICIENT",Readiness.INSUFFICIENT)
        self.assertEqual(out.lifecycle.reasons,("REVOKED",));self.assertEqual(len(out.positions),2)

    def test_active_successor_never_overrides_overall_insufficiency(self):
        d=binding();l=ledger(2)
        ref=replace(l.snapshots[1].ref,snapshot_id=d.inventory.snapshot_id)
        l=replace(l,snapshots=(l.snapshots[0],replace(l.snapshots[1],ref=ref,observed_at=BASE,available_at=BASE)),
            evidence=(l.evidence[0],replace(l.evidence[1],ref=ref)))
        l=with_events(l,(event(l,kind=EventKind.SUPERSEDE,issued_at=BASE,available_at=BASE),))
        a=replace(d.association,revision=1)
        out=self.reject(replace(with_lifecycle(d,l),association=a),"M4_INSUFFICIENT",Readiness.INSUFFICIENT)
        matched=next(row for row in out.lifecycle.snapshots if row.snapshot_id==a.snapshot_id)
        self.assertEqual(matched.state.value,"ACTIVE")
        self.assertEqual(out.inventory.status,Readiness.SUFFICIENT)
        self.assertEqual(len(out.positions),2)

    def test_expired_stale_future_unknown_and_incomplete_lifecycle(self):
        for kind in ("expired","stale","future","unknown","incomplete"):
            d=binding();l=d.lifecycle
            if kind=="expired":l=replace(l,snapshots=(replace(l.snapshots[0],expires_at=BASE),))
            elif kind=="stale":l=replace(l,evidence=(replace(l.evidence[0],observed_at=BASE-1),),snapshots=(replace(l.snapshots[0],observed_at=BASE-2),))
            elif kind=="future":l=replace(l,evidence=(replace(l.evidence[0],observed_at=BASE+1,available_at=BASE+1),))
            else:l=replace(l,evidence=(replace(l.evidence[0],completeness=Completeness.UNKNOWN if kind=="unknown" else Completeness.INCOMPLETE),))
            with self.subTest(kind=kind):self.reject(with_lifecycle(d,l),"M4_INSUFFICIENT",Readiness.INSUFFICIENT)

    def test_start_inclusive_and_expiry_exclusive_preserved(self):
        d=binding();l=replace(d.lifecycle,snapshots=(replace(d.lifecycle.snapshots[0],valid_from=BASE),))
        self.assertEqual(assess_binding(with_lifecycle(d,l)).status,Readiness.SUFFICIENT)
        l=replace(l,snapshots=(replace(l.snapshots[0],expires_at=BASE,valid_from=BASE-1),))
        self.reject(with_lifecycle(d,l),"M4_INSUFFICIENT",Readiness.INSUFFICIENT)

    def test_missing_lifecycle_evidence_fails_closed(self):
        d=binding();self.reject(with_lifecycle(d,replace(d.lifecycle,evidence=())),"M4_INSUFFICIENT",Readiness.INSUFFICIENT)

    def test_conflicting_snapshot_reuse_and_revision_ambiguity_propagate(self):
        d=binding();l=d.lifecycle
        l=replace(l,snapshots=l.snapshots*2,resources=replace(l.resources,max_snapshots=2))
        out=self.reject(with_lifecycle(d,l),"M4_INVALID")
        self.assertEqual(out.lifecycle.reasons,("IDENTITY_REUSE",));self.assertEqual(len(out.positions),2)

    def test_inventory_incomplete_and_missing_positions(self):
        from demo_futures.risk_remediation.budget_inventory_contract import Completeness as InventoryCompleteness
        d=binding()
        i=replace(d.inventory,completeness=InventoryCompleteness.INCOMPLETE,
            completeness_assertion=replace(d.inventory.completeness_assertion,complete=False))
        self.reject(replace(d,inventory=i),"M3_INSUFFICIENT",Readiness.INSUFFICIENT)
        self.reject(replace(d,inventory=replace(d.inventory,plans=d.inventory.plans[:1])),"M3_INVALID")

    def test_empty_inventory_requires_its_own_explicit_completeness(self):
        out=assess_binding(binding(0));self.assertEqual(out.status,Readiness.SUFFICIENT);self.assertEqual(out.positions,())
        d=binding(0);self.reject(replace(d,inventory=replace(d.inventory,completeness_assertion=None)),"M3_INSUFFICIENT",Readiness.INSUFFICIENT)

    def test_exceeds_and_within_are_retained_without_reserve_recomputation(self):
        d=binding();d=replace(d,inventory=change_raw(d.inventory,"plans",1,budget=D(51)))
        out=assess_binding(d);self.assertEqual(out.status,Readiness.SUFFICIENT)
        self.assertEqual(tuple(p.result.comparison for p in out.positions),("EXCEEDS","WITHIN"))
        self.assertEqual(tuple(p.result.adjusted_loss for p in out.positions),(D(51),D(51)))
        self.assertEqual(out.aggregate_state,"BLOCKED")

    def test_invalid_and_insufficient_positions_retained_in_order(self):
        d=binding();i=change_raw(d.inventory,"plans",0,quantity=D(11))
        e=envelope((scenario((),state=CoverageState.UNKNOWN),))
        i=replace(i,envelopes=(i.envelopes[0],replace(i.envelopes[1],value=e)))
        out=self.reject(replace(d,inventory=i),"M3_INVALID")
        self.assertEqual(tuple(p.result.status for p in out.positions),(Readiness.INVALID,Readiness.INSUFFICIENT))
        self.assertEqual(out.positions,out.inventory.positions)

    def test_both_dependencies_run_when_m4_is_insufficient(self):
        d=binding();l=replace(d.lifecycle,snapshots=(replace(d.lifecycle.snapshots[0],identity=None),))
        with patch.object(module,"assess_inventory",wraps=module.assess_inventory) as called:
            self.reject(with_lifecycle(d,l),"M4_INSUFFICIENT",Readiness.INSUFFICIENT)
            self.assertEqual(called.call_count,1)

    def test_both_invalid_dependencies_propagate_in_fixed_order(self):
        d=binding()
        ref=replace(d.lifecycle.snapshots[0].ref,source_id="other")
        l=replace(d.lifecycle,snapshots=(replace(d.lifecycle.snapshots[0],ref=ref),))
        i=change_raw(d.inventory,"plans",0,quantity=D(11))
        out=self.reject(replace(d,lifecycle=l,inventory=i),"M4_INVALID")
        self.assertEqual(out.reasons,("M4_INVALID","M3_INVALID"))
        self.assertEqual(len(out.positions),2)
        self.assertEqual(out.positions[0].result.status,Readiness.INVALID)

    def test_multi_snapshot_presentation_order_is_safe(self):
        d=binding();l=ledger(2)
        ref=replace(l.snapshots[0].ref,snapshot_id=d.inventory.snapshot_id)
        l=replace(l,snapshots=(replace(l.snapshots[0],ref=ref,observed_at=BASE,available_at=BASE),l.snapshots[1]),
            evidence=(replace(l.evidence[0],ref=ref),l.evidence[1]))
        a=with_lifecycle(d,l)
        b=with_lifecycle(d,replace(l,snapshots=l.snapshots[::-1],evidence=l.evidence[::-1]))
        self.assertEqual(assess_binding(a).status,Readiness.SUFFICIENT)
        self.assertEqual(assess_binding(a),assess_binding(b))

    def test_foreign_metadata_never_compared(self):
        class Foreign:
            def __eq__(self,other):raise AssertionError("foreign comparison")
            __ne__=__eq__
        for target in ("owner_id","snapshot_id","revision","snapshot_time","evaluation_time"):
            d=binding();object.__setattr__(d.association,target,Foreign())
            with self.subTest(target=target):self.reject(d,"INVALID_SCHEMA")
        d=binding();object.__setattr__(d.association.identity,"basis",Foreign());self.reject(d,"INVALID_SCHEMA")

    def test_foreign_nested_children_rejected_by_original_contracts(self):
        class Foreign:
            def __eq__(self,other):raise AssertionError("foreign comparison")
            __ne__=__eq__
        d=binding();object.__setattr__(d.inventory.plans[0].value,"quantity",Foreign())
        self.reject(d,"M3_INVALID")
        d=binding();object.__setattr__(d.lifecycle.snapshots[0].ref,"revision",Foreign())
        self.reject(d,"M4_INVALID")

    def test_tampered_deleted_fields_and_wrong_resource_shapes(self):
        for target in ("association","inventory","lifecycle","resources"):
            d=binding();obj,name={"association":(d.association,"revision"),"inventory":(d.inventory,"snapshot_id"),
                "lifecycle":(d.lifecycle,"evaluation_time"),"resources":(d.resources,"inventory_ceiling")}[target]
            object.__delattr__(obj,name)
            self.reject(d,"INVALID_SCHEMA")

    def test_forged_successful_diagnostics_never_replace_raw_inputs(self):
        d=binding();out=assess_binding(d)
        for name,value in (("inventory",out.inventory),("lifecycle",out.lifecycle),("association",out)):
            forged=replace(d);object.__setattr__(forged,name,value)
            self.reject(forged,"INVALID_SCHEMA")

    def test_declared_child_ceilings_checked_before_either_assessor(self):
        d=binding()
        for name,ceiling in (("inventory_ceiling",d.resources.inventory_ceiling),("lifecycle_ceiling",d.resources.lifecycle_ceiling)):
            for field in ceiling.__dataclass_fields__:
                with self.subTest(kind=name,field=field), patch.object(module,"assess_lifecycle",side_effect=AssertionError("early M4")),patch.object(module,"assess_inventory",side_effect=AssertionError("early M3")):
                    lower=replace(ceiling,**{field:0})
                    self.reject(replace(d,resources=replace(d.resources,**{name:lower})),"RESOURCE_BUDGET_EXCEEDED")

    def test_exact_metadata_text_and_integer_budget_boundaries(self):
        d=binding();a=d.association;i=d.inventory;l=d.lifecycle
        chars=sum(len(getattr(obj,n)) for obj in (a,i,l) for n in ("owner_id","source_id","version"))
        chars+=len(a.snapshot_id)+len(i.snapshot_id)
        chars+=sum(len(getattr(obj,n)) for obj in (a.identity,a.provenance) for n in ("identity","source_id","revision","assertion","basis"))
        exact=replace(d.resources,max_text_chars=chars,max_integer_bits=BASE.bit_length())
        self.assertEqual(assess_binding(replace(d,resources=exact)).status,Readiness.SUFFICIENT)
        for name in ("max_text_chars","max_integer_bits"):
            self.reject(replace(d,resources=replace(exact,**{name:getattr(exact,name)-1})),"RESOURCE_BUDGET_EXCEEDED")

    def test_shallow_collection_expansion_stops_before_children(self):
        d=binding();object.__setattr__(d.inventory,"plans",(object(),)*256)
        with patch.object(module,"assess_lifecycle",side_effect=AssertionError("early M4")):
            self.reject(d,"RESOURCE_BUDGET_EXCEEDED")

    def test_nested_expansion_is_bounded_by_child_preflight(self):
        d=binding();e=d.inventory.envelopes[0].value
        object.__setattr__(e,"scenarios",e.scenarios*256)
        out=self.reject(d,"M3_INVALID")
        self.assertEqual(out.inventory.reasons,("RESOURCE_BUDGET_EXCEEDED",))

    def test_decimal_digit_and_integer_limits_are_not_multiplied(self):
        d=binding();i=change_raw(d.inventory,"plans",0,quantity=D("1."+"0"*10001))
        out=self.reject(replace(d,inventory=i),"M3_INVALID")
        self.assertEqual(out.inventory.reasons,("RESOURCE_BUDGET_EXCEEDED",))
        d=binding();object.__setattr__(d.association,"revision",1<<256)
        self.reject(d,"RESOURCE_BUDGET_EXCEEDED")

    def test_unsupported_arithmetic_is_retained_without_amounts(self):
        d=binding();i=change_raw(d.inventory,"envelopes",0,entry_notional=D("1e1001"))
        out=self.reject(replace(d,inventory=i),"M3_INVALID")
        self.assertIsNone(out.positions[0].result.adjusted_loss)

    def test_reordered_safe_raw_collections_have_identical_results(self):
        d=binding();i=replace(d.inventory,required_position_ids=d.inventory.required_position_ids[::-1],
            plans=d.inventory.plans[::-1],envelopes=d.inventory.envelopes[::-1],bindings=d.inventory.bindings[::-1])
        self.assertEqual(assess_binding(d),assess_binding(replace(d,inventory=i)))

    def test_diagnostic_constructor_cannot_hide_child_failure(self):
        d=binding();out=self.reject(replace(d,inventory=change_raw(d.inventory,"plans",0,quantity=D(11))),"M3_INVALID")
        with self.assertRaises(ValueError):replace(out,status=Readiness.SUFFICIENT,reasons=())
        with self.assertRaises(ValueError):replace(out,inventory=None)
        with self.assertRaises(ValueError):BindingDiagnostic(Readiness.SUFFICIENT)
        with self.assertRaises(ValueError):BindingDiagnostic(Readiness.INVALID,("M3_INVALID",))

    def test_tampered_nested_authority_and_foreign_reasons_are_refused(self):
        out=assess_binding(binding());object.__setattr__(out.lifecycle,"authority","FORGED")
        with self.assertRaises(ValueError):replace(out)
        class Foreign:
            def __eq__(self,other):raise AssertionError("foreign reason")
        with self.assertRaises(ValueError):BindingDiagnostic(Readiness.INVALID,(Foreign(),))

    def test_constructor_exact_types_and_negative_budgets(self):
        d=binding()
        for call in (lambda:replace(d,inventory=object()),lambda:replace(d.association,revision=True),
                lambda:replace(d.resources,max_text_chars=-1),lambda:replace(d.resources,max_integer_bits=True)):
            with self.assertRaises(ValueError):call()
        a=replace(d.association,revision=-1);self.reject(replace(d,association=a),"INVALID_TIME")

    def test_immutable_output_and_refused_truth(self):
        d=binding();out=assess_binding(d)
        for obj,name in ((d,"association"),(d.association,"revision"),(out,"status")):
            with self.assertRaises(FrozenInstanceError):setattr(obj,name,None)
        with self.assertRaises(TypeError):bool(out)

    def test_decimal_settings_and_flags_preserved(self):
        d=binding();expected=assess_binding(d)
        with localcontext() as ctx:
            ctx.prec=2;ctx.rounding=ROUND_DOWN;before=ctx.copy()
            self.assertEqual(assess_binding(d),expected)
            self.assertEqual(dict(getcontext().flags),dict(before.flags))
            self.assertEqual(getcontext().prec,2)

    def test_no_io_or_engine_capability(self):
        d=binding()
        with patch("builtins.open",side_effect=AssertionError("I/O")),patch("io.open",side_effect=AssertionError("I/O")), \
                patch("sqlite3.connect",side_effect=AssertionError("database")),patch("socket.socket",side_effect=AssertionError("network")), \
                patch("demo_futures.risk.size_position",side_effect=AssertionError("sizing")):
            self.assertEqual(assess_binding(d).status,Readiness.SUFFICIENT)

    def test_static_dependencies_and_no_financial_computation(self):
        path=Path(__file__).resolve().parents[1]/"src/demo_futures/risk_remediation/inventory_lifecycle_binding.py"
        tree=ast.parse(path.read_text(encoding="utf-8"))
        self.assertFalse(any(isinstance(n,ast.Import) for n in ast.walk(tree)))
        modules={n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)}
        self.assertEqual(modules,{"dataclasses","research_v2.contracts","budget_inventory_contract","snapshot_lifecycle_contract"})
        calls={n.func.id if isinstance(n.func,ast.Name) else n.func.attr for n in ast.walk(tree)
            if isinstance(n,ast.Call) and isinstance(n.func,(ast.Name,ast.Attribute))}
        self.assertFalse(calls & {"open","connect","request","size_position","fit","predict","assess_plan_budget","assess_funding_budget"})
