"""Invented record consistency only. Never call label production or simulation."""
from dataclasses import fields, replace, FrozenInstanceError
from decimal import Decimal as D, getcontext, localcontext
from decimal import Inexact, Rounded, FloatOperation, ROUND_FLOOR
from functools import lru_cache
import hashlib
import json
import unittest
from unittest.mock import patch

from demo_futures.backtest import BacktestEngine, Trade
from demo_futures.research_v2 import assembly, labels
from demo_futures.research_v2.eligibility import (
    Association, Budgets, Payload, Result, Revision, validate_associations)
from demo_futures.research_v2.labels import ActionOutcome, PairedOutcome
from demo_futures.research_v2.opportunities import Opportunity
from demo_futures.research_v2.config import HORIZON, HOUR, STEP
from test_v2_assembly import fixture


def invented_pair(row):
    # Fixed zero-ledger metadata, not generated market labels or simulated fills.
    actions = []
    for side in ('LONG', 'SHORT'):
        values = {f.name:D('0') for f in fields(Trade)}
        values.update(symbol=row.symbol, side=side, signal_time=row.decision_time,
                      entry_time=row.decision_time+1, exit_time=row.decision_time+STEP,
                      quantity=D('1'), entry_price=D('100'), risk_budget=D('50'),
                      entry_reason='invented', exit_reason='invented',
                      funding_mark_fallbacks=0, uncertain_funding_credits_skipped=0)
        actions.append(ActionOutcome(side, 'VALID', 'constructed fixture only', Trade(**values), D('0')))
    return PairedOutcome(Opportunity(row), *actions)


@lru_cache
def inputs():
    d=fixture(); result=assembly.assemble(d)
    assert result.status=='FEATURE_ASSEMBLY_VALID'
    by_id={r.row_id:r for r in d.rows}; sources={s.series.symbol:s for s in d.sources}
    rows=[]
    for identity in d.train_ids+d.evaluation_ids:
        row=by_id[identity]; s=sources[row.symbol]
        rows.append(Association(identity, 'train' if identity in d.train_ids else 'development_evaluation',
                    d.window, invented_pair(row), s.identity, s.series.fixture_id, s.revision,
                    'r1', 'invented-producer', 'p1', row.decision_time+1+HORIZON,
                    'invented-horizon', 'invented-funding'))
    return d,result,tuple(rows),tuple(Revision(a.row_id,'r1') for a in rows),Budgets(
        2000,400000,3000000,3000000,20000000,40000000)


def check(*, rows=None, revisions=None, declaration=None, result=None, budgets=None):
    d,out,a,r,b=inputs()
    with patch.object(BacktestEngine,'run',side_effect=AssertionError('SIMULATOR_FORBIDDEN')), \
         patch.object(labels,'paired_outcome',side_effect=AssertionError('LABEL_PRODUCTION_FORBIDDEN')):
        return validate_associations(d if declaration is None else declaration,
                 out if result is None else result,a if rows is None else rows,
                 r if revisions is None else revisions,b if budgets is None else budgets)


class EligibilityTests(unittest.TestCase):
    def assert_failed(self, out, status):
        self.assertEqual(out.status,status,out.reasons);self.assertIsNone(out.payload)
        self.assertEqual(out.reasons,tuple(sorted(set(out.reasons))))

    def test_success_remains_inert_and_preserves_full_causal_coverage(self):
        d,original,rows,_,_=inputs();out=check()
        self.assertEqual(out.status,'SYNTHETIC_ASSOCIATION_CONSISTENT',out.reasons)
        self.assertEqual(out.payload.row_ids,d.train_ids+d.evaluation_ids)
        self.assertEqual(out.payload.coverage,original.payload.coverage)
        self.assertGreater(len(out.payload.coverage),len(rows))
        for name in ('label_provenance','external_provenance','external_completeness','training_readiness'):
            self.assertEqual(getattr(out.payload,name),'UNVERIFIED')
        self.assertEqual(out.payload.declared_provenance,'SYNTHETIC_DECLARATION_ONLY')
        self.assertEqual(out.payload.training_authorization,'NOT AUTHORIZED')
        self.assertEqual(out.payload.financial_validity,'NOT ESTABLISHED')
        self.assertEqual(hashlib.sha256(out.payload.canonical).hexdigest(),out.payload.sha256)
        with self.assertRaises(TypeError):bool(out)
        with self.assertRaises(FrozenInstanceError):out.payload.row_ids=()

    def test_missing_pair_and_each_missing_action_are_insufficient(self):
        _,verified,rows,_,_=inputs()
        # Isolate missing-label cases using the already revalidated fixture.
        # Real delegation on missing evidence is independently tested below.
        with patch.object(assembly,'assemble',return_value=verified):
            self.assert_failed(check(rows=rows[1:]),'INSUFFICIENT')
            self.assert_failed(check(rows=(replace(rows[0],pair=None),)+rows[1:]),'INSUFFICIENT')
            for side in ('long','short'):
                pair=replace(rows[0].pair);object.__setattr__(pair,side,None)
                out=check(rows=(replace(rows[0],pair=pair),)+rows[1:])
                self.assert_failed(out,'INSUFFICIENT');self.assertIn('MISSING_ACTION',out.reasons)

    def test_missing_action_cannot_mask_wrong_side(self):
        _,_,rows,_,_=inputs()
        for absent in ('long','short'):
            pair=replace(rows[0].pair)
            other='short' if absent=='long' else 'long'
            object.__setattr__(pair,absent,None)
            object.__setattr__(pair,other,getattr(rows[0].pair,absent))
            out=check(rows=(replace(rows[0],pair=pair),)+rows[1:])
            self.assert_failed(out,'INVALID');self.assertEqual(out.reasons,('WRONG_ACTION_SIDE',))

    def test_missing_evidence_revalidates_assembly_and_preserves_invalid_precedence(self):
        d,verified,rows,_,_=inputs();a=replace(rows[0],funding_evidence=None)
        with patch.object(assembly,'assemble',wraps=assembly.assemble) as delegated:
            out=check(rows=(a,)+rows[1:])
            self.assert_failed(out,'INSUFFICIENT');delegated.assert_called_once_with(d)
        forged=replace(verified,payload=replace(verified.payload,canonical=verified.payload.canonical+b' '))
        self.assert_failed(check(rows=(a,)+rows[1:],result=forged),'INVALID')
        failed=assembly.Result('INVALID',('INVALID_INPUT',))
        out=check(result=failed)
        self.assert_failed(out,'INVALID');self.assertEqual(out.reasons,('FEATURE_ASSEMBLY_INVALID',))

    def test_unavailable_assembly_cannot_hide_malformed_supplied_records(self):
        d,_,rows,revs,b=inputs();unavailable=assembly.Result('INSUFFICIENT',('missing',))
        for declaration,associations in ((object.__new__(assembly.Declaration),(object(),)),
                                         (d,(object(),)),(d,(replace(rows[0],source_id='conflict'),)+rows[1:])):
            out=validate_associations(declaration,unavailable,associations,revs,b)
            self.assert_failed(out,'INVALID')
        self.assert_failed(check(result=unavailable),'INSUFFICIENT')

    def test_duplicates_conflicts_orphans_and_order(self):
        _,_,rows,_,_=inputs()
        for changed in (rows+(rows[0],), rows[::-1],
                        (replace(rows[0],row_id='BTCUSDT:999'),)+rows[1:]):
            self.assert_failed(check(rows=changed),'INVALID')

    def test_same_id_changed_feature_content_rejects(self):
        _,_,rows,_,_=inputs();a=rows[0];row=a.pair.opportunity.features
        pair=replace(a.pair,opportunity=Opportunity(replace(row,values=(99.,)+row.values[1:])))
        out=check(rows=(replace(a,pair=pair),)+rows[1:])
        self.assert_failed(out,'INVALID');self.assertIn('FEATURE_CONTENT_MISMATCH',out.reasons)

    def test_equal_numbers_cannot_hide_changed_feature_encoding(self):
        _,_,rows,_,_=inputs();a=rows[0];row=a.pair.opportunity.features
        for value in (0,-0.0,D('0')):
            changed=replace(row,values=(value,)+row.values[1:])
            pair=replace(a.pair,opportunity=Opportunity(changed))
            out=check(rows=(replace(a,pair=pair),)+rows[1:])
            self.assert_failed(out,'INVALID');self.assertIn('FEATURE_CONTENT_MISMATCH',out.reasons)

    def test_trade_annotation_types_are_not_coerced(self):
        _,_,rows,_,_=inputs();a=rows[0]
        for change in ({'quantity':True},{'entry_price':100.0},{'entry_time':True}):
            trade=replace(a.pair.long.trade,**change)
            action=replace(a.pair.long);object.__setattr__(action,'trade',trade)
            pair=replace(a.pair);object.__setattr__(pair,'long',action)
            self.assert_failed(check(rows=(replace(a,pair=pair),)+rows[1:]),'INVALID')

    def test_source_window_stage_and_horizon_conflicts(self):
        _,_,rows,_,_=inputs();a=rows[0]
        changes=({'source_id':'other'},{'fixture_id':'other'},{'source_revision':'r2'},
                 {'window':replace(a.window,evaluation_end=a.window.evaluation_end+HOUR)},
                 {'stage':'development_evaluation'},{'horizon_end':a.horizon_end-HOUR},
                 {'evidence':'AUTHENTICATED_REAL_HISTORY'})
        for change in changes:
            self.assert_failed(check(rows=(replace(a,**change),)+rows[1:]),'INVALID')

    def test_missing_declarations_and_invalid_dominance(self):
        _,verified,rows,_,_=inputs();a=rows[0]
        with patch.object(assembly,'assemble',return_value=verified):
            for name in ('source_id','fixture_id','source_revision','revision','producer_id',
                         'producer_revision','horizon_end','horizon_evidence','funding_evidence'):
                self.assert_failed(check(rows=(replace(a,**{name:None}),)+rows[1:]),'INSUFFICIENT')
        out=check(rows=(replace(a,funding_evidence=None,source_id='conflicting'),)+rows[1:])
        self.assert_failed(out,'INVALID');self.assertIn('MISSING_FUNDING_EVIDENCE',out.reasons)

    def test_excluded_outcomes_never_become_no_trade_or_usable_subset(self):
        _,_,rows,_,_=inputs();a=rows[0]
        pair=replace(a.pair,long=ActionOutcome('LONG','FUNDING_UNCERTAIN','invented missingness'))
        out=check(rows=(replace(a,pair=pair),)+rows[1:])
        self.assert_failed(out,'INSUFFICIENT');self.assertIn('PAIR_NOT_VALID',out.reasons)

    def test_revision_missing_cycle_fork_duplicate_and_superseded(self):
        _,_,rows,revs,_=inputs();key=rows[0].row_id
        for changed,status in (
            (revs[1:],'INSUFFICIENT'),
            ((Revision(key,'r1','missing'),)+revs[1:],'INSUFFICIENT'),
            ((Revision(key,'r1','r2'),Revision(key,'r2','r1'))+revs[1:],'INVALID'),
            ((Revision(key,'r1'),Revision(key,'r2','r1'),Revision(key,'r3','r1'))+revs[1:],'INVALID'),
            (revs+(revs[0],),'INVALID'),
            (revs+(Revision(key,'r2','r1'),),'INVALID')):
            self.assert_failed(check(revisions=changed),status)

    def test_successful_declared_correction_changes_commitment(self):
        _,_,rows,revs,_=inputs();original=check()
        changed=check(rows=(replace(rows[0],revision='r2'),)+rows[1:],
                      revisions=revs+(Revision(rows[0].row_id,'r2','r1'),))
        self.assertEqual(changed.status,'SYNTHETIC_ASSOCIATION_CONSISTENT',changed.reasons)
        self.assertNotEqual(original.payload.sha256,changed.payload.sha256)

    def test_outcome_content_and_decimal_representation_are_bound(self):
        _,_,rows,_,_=inputs();a=rows[0];original=check()
        # Same IDs/revision do not conceal changed immutable payload bytes.
        changed_trade=replace(a.pair.long.trade,entry_reason='different invented declaration')
        changed_pair=replace(a.pair,long=replace(a.pair.long,trade=changed_trade,net_r=D('-0.00')))
        changed=check(rows=(replace(a,pair=changed_pair),)+rows[1:])
        self.assertEqual(changed.status,'SYNTHETIC_ASSOCIATION_CONSISTENT',changed.reasons)
        self.assertEqual(original.payload.row_ids,changed.payload.row_ids)
        self.assertNotEqual(original.payload.sha256,changed.payload.sha256)
        self.assertIn('["d",1,"0","-2"]',changed.payload.canonical.decode())
        for value in (D('NaN'),D('Infinity'),D('1e-10000000'),True):
            action=replace(a.pair.long);object.__setattr__(action,'net_r',value)
            pair=replace(a.pair,long=action)
            self.assert_failed(check(rows=(replace(a,pair=pair),)+rows[1:]),'INVALID')

    def test_encoding_decimal_context_determinism_and_input_immutability(self):
        _,_,rows,_,_=inputs();before=repr(rows);context=getcontext().copy()
        a,b=check(),check();self.assertEqual(a,b);self.assertEqual(repr(rows),before)
        self.assertEqual(getcontext().flags,context.flags);self.assertEqual(getcontext().prec,context.prec)
        wire=json.loads(a.payload.canonical)
        self.assertEqual(wire[0],'v2-label-association-1')
        self.assertIn('["d",0,"0","0"]',a.payload.canonical.decode())
        with localcontext() as c:
            c.prec+=1;changed=check()
        self.assertNotEqual(a.payload.sha256,changed.payload.sha256)

    def test_decimal_policy_flags_and_traps_are_preserved(self):
        inputs()
        def snapshot(c):
            return (c.prec,c.rounding,c.Emin,c.Emax,c.capitals,c.clamp,dict(c.flags),dict(c.traps))
        with localcontext() as context:
            context.prec=9;context.rounding=ROUND_FLOOR
            context.Emin=-99;context.Emax=99;context.capitals=0;context.clamp=1
            context.flags[Inexact]=True;context.flags[Rounded]=True
            context.traps[Inexact]=True;context.traps[FloatOperation]=True
            before=snapshot(context);out=check()
            self.assertEqual(out.status,'SYNTHETIC_ASSOCIATION_CONSISTENT',out.reasons)
            self.assertEqual(snapshot(context),before)

    def test_hostile_numeric_conversion_hooks_are_never_called(self):
        _,_,rows,_,_=inputs();a=rows[0]
        class Hostile:
            def __float__(self):raise AssertionError('FOREIGN_FLOAT_FORBIDDEN')
            def __eq__(self, other):raise AssertionError('FOREIGN_EQUALITY_FORBIDDEN')
        class ForeignFloat(float):
            def __float__(self):raise AssertionError('FLOAT_SUBCLASS_FORBIDDEN')
        class ForeignDecimal(D):
            def as_tuple(self):raise AssertionError('DECIMAL_SUBCLASS_FORBIDDEN')
        for value in (Hostile(),ForeignFloat(0),ForeignDecimal('0')):
            action=replace(a.pair.long);object.__setattr__(action,'net_r',value)
            pair=replace(a.pair);object.__setattr__(pair,'long',action)
            self.assert_failed(check(rows=(replace(a,pair=pair),)+rows[1:]),'INVALID')

    def test_resource_ceiling_and_one_below(self):
        _,_,rows,_,b=inputs()
        for name in ('pairs','nodes','text','numeric_chars','encoded_bytes','work'):
            self.assert_failed(check(budgets=replace(b,**{name:0})),'INVALID')
        exact=replace(b,pairs=len(rows));self.assertEqual(check(budgets=exact).status,'SYNTHETIC_ASSOCIATION_CONSISTENT')
        self.assert_failed(check(budgets=replace(exact,pairs=len(rows)-1)),'INVALID')

    def test_exact_encoded_byte_limit_and_one_below(self):
        _,_,_,_,b=inputs();out=check();wire=json.loads(out.payload.canonical)
        encoded_budget=dict(wire[4][2]);size=len(out.payload.canonical)
        while True:
            encoded_budget['encoded_bytes'][1]=str(size)
            encoded=json.dumps(wire,ensure_ascii=True,separators=(',',':'),sort_keys=True).encode('ascii')
            if len(encoded)==size:break
            size=len(encoded)
        exact=replace(b,encoded_bytes=size);out=check(budgets=exact)
        self.assertEqual(out.status,'SYNTHETIC_ASSOCIATION_CONSISTENT',out.reasons)
        self.assertEqual(out.payload.canonical,encoded)
        out=check(budgets=replace(exact,encoded_bytes=size-1))
        self.assert_failed(out,'INVALID');self.assertEqual(out.reasons,('RESOURCE_ENCODED_BYTES',))

    def test_forged_assembly_is_recomputed_and_cannot_supply_coverage(self):
        _,out,_,_,_=inputs();p=replace(out.payload,canonical=out.payload.canonical+b' ')
        self.assert_failed(check(result=replace(out,payload=p)),'INVALID')
        p=replace(out.payload,coverage=())
        self.assertEqual(check(result=replace(out,payload=p)).payload.coverage,out.payload.coverage)

    def test_failure_containment_and_result_non_consumability(self):
        d,result,rows,revs,b=inputs()
        for args in ((None,result,rows,revs,b),(d,result,[],revs,b),(d,result,rows,(),b),
                     (d,result,rows,revs,replace(b,work=True))):
            out=validate_associations(*args);self.assertIsNone(out.payload)
        with self.assertRaises(ValueError):Result('INVALID',('bad',),object())
        with self.assertRaises(ValueError):Result('SYNTHETIC_ASSOCIATION_CONSISTENT',(),object())

    def test_declaration_limits_and_foreign_rows_reject_before_delegation(self):
        d,_,_,_,b=inputs()
        class Foreign:
            @property
            def row_id(self):raise AssertionError('FOREIGN_HOOK_FORBIDDEN')
            def __eq__(self, other):raise AssertionError('FOREIGN_EQUALITY_FORBIDDEN')
        with patch.object(assembly,'assemble',side_effect=AssertionError('DELEGATION_FORBIDDEN')):
            self.assert_failed(check(declaration=replace(d,train_ids=d.train_ids*3)),'INVALID')
            self.assert_failed(check(declaration=replace(d,rows=(Foreign(),))),'INVALID')
            row=replace(d.rows[0]);object.__setattr__(row,'status',Foreign())
            self.assert_failed(check(declaration=replace(d,rows=(row,)+d.rows[1:])),'INVALID')
            window=replace(d.window);object.__setattr__(window,'train_start',Foreign())
            self.assert_failed(check(declaration=replace(d,window=window)),'INVALID')


if __name__=='__main__':unittest.main()
