"""Invented constant candles; no labels or simulator."""
from dataclasses import replace
from functools import lru_cache
from decimal import Decimal
import hashlib
import json
import unittest
from demo_futures.data import Candle
from demo_futures.research_v2.config import HOUR, STEP, SYMBOLS, FEATURES
from demo_futures.research_v2.features import SyntheticSeries, ObservedCandle, feature_at
from demo_futures.research_v2.validation import DevelopmentWindow, TrainingReceipt, ids_hash
from demo_futures.research_v2.preprocessing import estimate_preprocessing
from demo_futures.research_v2.assembly import *

@lru_cache
def fixture():
    sources=[]
    for symbol in SYMBOLS:
        observations=tuple(ObservedCandle(Candle(i*STEP,100.,100.5,99.5,100.,100.,(i+1)*STEP-1,10000.,10),(i+1)*STEP)
                           for i in range(540*12))
        sources.append(Source('invented-'+symbol,'r1',SyntheticSeries(symbol,observations,'fixture-v1')))
    times=tuple(range(18,518))+tuple(range(531,537))
    # Constant feature values independently repeat after warmup; public assembler recomputes every row.
    prototypes={s.series.symbol:feature_at(s.series,18*HOUR-1) for s in sources}
    rows=tuple(replace(prototypes[s],decision_time=t*HOUR-1) for t in times for s in SYMBOLS)
    window=DevelopmentWindow(0,530*HOUR,536*HOUR)
    train=rows[:1000]; ids=tuple(r.row_id for r in train)
    receipt=TrainingReceipt(ids,ids_hash(ids),window)
    transform=estimate_preprocessing(train,receipt,receipt).contract
    evaluation=tuple(r.row_id for r in rows[1000:] if r.decision_time+1+4*HOUR<=window.evaluation_end)
    return Declaration(tuple(sources),rows,ids,evaluation,window,receipt,transform,
                       Budgets(2000,20000,400000,3000000,3000000,20000000,20000000))

class AssemblyTests(unittest.TestCase):
    def test_success_and_authority(self):
        out=assemble(fixture()); self.assertEqual(out.status,'FEATURE_ASSEMBLY_VALID',out.reasons)
        self.assertEqual(out.payload.label_eligibility,'UNVERIFIED')
        self.assertEqual(out.payload.financial_label_validity,'UNVERIFIED')
        self.assertEqual(out.payload.historical_authenticity,'UNVERIFIED')
        self.assertEqual(out.payload.source_completeness,'UNVERIFIED')
        self.assertEqual(out.payload.training_readiness,'UNVERIFIED')
        self.assertEqual(out.payload.training_authorization,'NOT AUTHORIZED')
        self.assertEqual(out.payload.sha256,hashlib.sha256(out.payload.canonical).hexdigest())
        self.assertEqual(len(out.payload.coverage),len(fixture().rows))
        self.assertEqual(len(out.payload.partition_exclusions),8)
        with self.assertRaises(TypeError):bool(out)
    def test_duplicates_order_schema(self):
        d=fixture()
        for changed in (replace(d,rows=d.rows+d.rows[:1]),replace(d,rows=d.rows[::-1]),replace(d,feature_names=FEATURES[::-1]),replace(d,train_ids=d.train_ids[:-1])):
            out=assemble(changed); self.assertIsNone(out.payload); self.assertNotEqual(out.status,'FEATURE_ASSEMBLY_VALID')
    def test_receipt_mismatch(self):
        d=fixture(); other=replace(d.receipt,window=replace(d.window,evaluation_end=537*HOUR))
        self.assertIsNone(assemble(replace(d,receipt=other)).payload)
    def test_consistent_receipt_and_transform_cannot_bind_another_window(self):
        d=fixture(); other=replace(d.receipt,window=replace(d.window,evaluation_end=537*HOUR))
        out=assemble(replace(d,receipt=other,transform=replace(d.transform,receipt=other)))
        self.assertEqual(out.reasons,('ASSEMBLY_RECEIPT_WINDOW_MISMATCH',))
        self.assertIsNone(out.payload)
    def test_content_revision_changes_digest(self):
        d=fixture(); changed=replace(d,sources=(replace(d.sources[0],revision='r2'),d.sources[1]))
        a,b=assemble(d),assemble(changed); self.assertEqual(b.status,'FEATURE_ASSEMBLY_VALID',b.reasons)
        self.assertNotEqual(a.payload.sha256,b.payload.sha256)
    def test_changed_features_same_id_reject(self):
        d=fixture(); row=replace(d.rows[0],values=(99.,)+d.rows[0].values[1:])
        self.assertEqual(assemble(replace(d,rows=(row,)+d.rows[1:])).reasons,('CAUSAL_CONTENT_MISMATCH',))
    def test_late_receipt_rejects(self):
        d=fixture(); source=d.sources[0]; obs=source.series.observations
        changed=replace(obs[0],available_at=600*HOUR)
        source=replace(source,series=replace(source.series,observations=(changed,)+obs[1:]))
        self.assertIsNone(assemble(replace(d,sources=(source,d.sources[1]))).payload)
    def test_resource_limits(self):
        d=fixture()
        for name in ('rows','observations','nodes','text','numeric_chars','encoded_bytes','work'):
            out=assemble(replace(d,budgets=replace(d.budgets,**{name:0})))
            self.assertIsNone(out.payload)
    def test_determinism_and_immutability(self):
        d=fixture(); before=repr(d); a=assemble(d); b=assemble(d)
        self.assertEqual(a,b); self.assertEqual(repr(d),before)
        with self.assertRaises(Exception):a.payload.sha256='bad'
    def test_future_change_preserves_earlier_features_but_changes_commitment(self):
        d=fixture(); source=d.sources[0]; obs=source.series.observations
        last=replace(obs[-1],candle=replace(obs[-1].candle,close=100.1))
        changed=replace(d,sources=(replace(source,series=replace(source.series,observations=obs[:-1]+(last,))),d.sources[1]))
        a,b=assemble(d),assemble(changed)
        self.assertEqual(b.status,'FEATURE_ASSEMBLY_VALID',b.reasons)
        self.assertEqual(a.payload.transformed,b.payload.transformed)
        self.assertNotEqual(a.payload.sha256,b.payload.sha256)
    def test_exact_row_budget_and_one_below(self):
        d=fixture(); exact=replace(d,budgets=replace(d.budgets,rows=len(d.rows)))
        self.assertEqual(assemble(exact).status,'FEATURE_ASSEMBLY_VALID')
        self.assertIsNone(assemble(replace(exact,budgets=replace(exact.budgets,rows=len(d.rows)-1))).payload)
    def test_exact_observation_budget_and_one_below(self):
        d=fixture(); count=sum(len(s.series.observations) for s in d.sources)
        exact=replace(d,budgets=replace(d.budgets,observations=count))
        self.assertEqual(assemble(exact).status,'FEATURE_ASSEMBLY_VALID')
        out=assemble(replace(exact,budgets=replace(exact.budgets,observations=count-1)))
        self.assertEqual(out.reasons,('RESOURCE_OBSERVATIONS',)); self.assertIsNone(out.payload)
    def test_wire_structure_and_exact_byte_budget(self):
        d=fixture(); out=assemble(d); wire=json.loads(out.payload.canonical)
        declaration=dict(wire[2]); self.assertEqual(wire[:2],['r','Declaration'])
        row=dict(declaration['rows'][1][0][2])
        self.assertEqual(row['values'],['t',[['f',v.hex()] for v in d.rows[0].values]])
        source=dict(declaration['sources'][1][0][2])
        series=dict(source['series'][2]); observation=dict(series['observations'][1][0][2])
        self.assertEqual(observation['available_at'],['i',str(STEP)])
        self.assertEqual(source['revision'],['s','r1'])
        self.assertEqual(declaration['train_ids'][1],[['s',v] for v in d.train_ids])
        # Independent wire-level fixed point: the limit's own decimal width is encoded.
        budget_fields=dict(declaration['budgets'][2]); size=len(out.payload.canonical)
        while True:
            budget_fields['encoded_bytes'][1]=str(size)
            encoded=json.dumps(wire,ensure_ascii=True,separators=(',',':'),sort_keys=True).encode('ascii')
            if len(encoded)==size:break
            size=len(encoded)
        exact=replace(d,budgets=replace(d.budgets,encoded_bytes=size))
        accepted=assemble(exact); self.assertEqual(accepted.status,'FEATURE_ASSEMBLY_VALID')
        self.assertEqual(accepted.payload.canonical,encoded)
        out=assemble(replace(exact,budgets=replace(exact.budgets,encoded_bytes=size-1)))
        self.assertEqual(out.reasons,('RESOURCE_ENCODED_BYTES',)); self.assertIsNone(out.payload)
    def test_numeric_types_and_missing_observations_fail_closed(self):
        d=fixture()
        for value in (Decimal('0'),True,2**53+1,float('nan'),float('inf')):
            row=replace(d.rows[0]); object.__setattr__(row,'values',(value,)+row.values[1:])
            self.assertIsNone(assemble(replace(d,rows=(row,)+d.rows[1:])).payload)
        source=d.sources[0]; obs=source.series.observations
        # Keep the caller's READY row, remove the corresponding decision candle.
        index=18*12-1
        missing=replace(source,series=replace(source.series,observations=obs[:index]+obs[index+1:]))
        out=assemble(replace(d,sources=(missing,d.sources[1])))
        self.assertEqual(out.reasons,('CAUSAL_CONTENT_MISMATCH',)); self.assertIsNone(out.payload)
    def test_partition_crossing_and_inactive_symbol(self):
        d=fixture()
        for changed in (replace(d,train_ids=d.train_ids+d.evaluation_ids),
                        replace(d,train_ids=d.train_ids[::-1]),
                        replace(d,evaluation_ids=d.evaluation_ids[::-1])):
            self.assertIsNone(assemble(changed).payload)
        row=replace(d.rows[0]); object.__setattr__(row,'symbol','SOLUSDT')
        self.assertIsNone(assemble(replace(d,rows=(row,)+d.rows[1:])).payload)
    def test_malformed_and_failure_containment(self):
        for d in (None,{},replace(fixture(),sources=())):
            self.assertIsNone(assemble(d).payload)
        with self.assertRaises(ValueError):Result('INVALID',('bad',),object())
        payload=Payload(b'', '', (), (), (), ())
        with self.assertRaises(ValueError):replace(payload,training_readiness='AUTHORIZED')
        d=fixture()
        self.assertIsNone(assemble(replace(d,sources=(replace(d.sources[0],identity=123),d.sources[1]))).payload)
        broken=replace(d.budgets);object.__delattr__(broken,'rows')
        self.assertIsNone(assemble(replace(d,budgets=broken)).payload)

if __name__=='__main__':unittest.main()
