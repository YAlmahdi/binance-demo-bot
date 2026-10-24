"""Fresh interpreters, invented fixtures only; no training or provenance authority."""
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading
import unittest
from functools import lru_cache


ROOT = Path(__file__).resolve().parents[1]
TIMEOUT = 180
OUTPUT_LIMIT = 64 * 1024 * 1024  # Combined stdout/stderr; fixtures stay below this.
SEEDS = ('0', '1', '8675309')

# Only these literal environment values reach the child; no parent environment
# values are inspected or copied.
def child_environment(seed):
    if seed not in SEEDS:
        raise ValueError('Undeclared hash seed')
    return {'SYSTEMROOT': 'C:\\Windows', 'PYTHONHASHSEED': seed,
            'PYTHONIOENCODING': 'utf-8'} if sys.platform == 'win32' else {
                'PYTHONHASHSEED': seed, 'PYTHONIOENCODING': 'utf-8'}


# -I also ignores PYTHONHASHSEED, so use -E-free -s -S with explicit paths instead.
# -S disables site/customization; -s disables user site; sanitized env has no
# PYTHONPATH/PYTHONHOME. sys.path is replaced before importing project code.
CHILD = r'''
import sys, json, hashlib, base64, os
from pathlib import Path
root=Path(sys.argv[1]); mode=sys.argv[2]; precision=int(sys.argv[3]); seed=sys.argv[4]
assert not sys.flags.ignore_environment and sys.flags.no_site and sys.flags.no_user_site
assert sys.flags.dont_write_bytecode and os.environ['PYTHONHASHSEED']==seed
sys.path=[str(root/'src'),str(root/'tests')]+[p for p in sys.path if p and Path(p).absolute()!=root]
events=[]
def guard(event,args):
    if event in ('socket.connect','socket.getaddrinfo','sqlite3.connect','subprocess.Popen','os.system'):
        events.append(event); raise AssertionError('FORBIDDEN_RUNTIME_ACCESS')
    if event=='open':
        mode=args[1]; flags=args[2]
        if (isinstance(mode,str) and any(c in mode for c in 'wax+')) or (isinstance(flags,int) and flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC)):
            events.append('write'); raise AssertionError('WRITE_FORBIDDEN')
        if isinstance(args[0],(str,bytes,os.PathLike)):
            p=Path(os.fsdecode(args[0])).absolute()
            if p.is_relative_to(root) and (p.suffix not in ('.py','.pyc') or not any(p.is_relative_to(root/d) for d in ('src','tests'))):
                events.append('payload_read'); raise AssertionError('PAYLOAD_FORBIDDEN')
sys.addaudithook(guard)
from decimal import Context, setcontext, getcontext, ROUND_HALF_EVEN
from decimal import InvalidOperation, DivisionByZero, Overflow
from dataclasses import replace, fields
from unittest.mock import patch
from test_v2_assembly import fixture
from test_v2_eligibility import invented_pair
from demo_futures.backtest import BacktestEngine
from demo_futures.research_v2 import assembly, eligibility, labels
from demo_futures.research_v2.config import FEATURES, HORIZON
ctx=Context(prec=precision,rounding=ROUND_HALF_EVEN,Emin=-999999,Emax=999999,
            capitals=1,clamp=0,traps=[InvalidOperation,DivisionByZero,Overflow])
setcontext(ctx)
def policy():
    c=getcontext()
    return [c.prec,c.rounding,c.Emin,c.Emax,c.capitals,c.clamp,
            sorted(s.__name__ for s,on in c.traps.items() if on)]
before=policy()
def forbidden(*a,**k):
    events.append('simulation_or_label'); raise AssertionError('FORBIDDEN_PRODUCTION')
with patch.object(BacktestEngine,'run',side_effect=forbidden),patch.object(labels,'paired_outcome',side_effect=forbidden):
    d=fixture()
    if mode=='revision':
        d=replace(d,sources=(replace(d.sources[0],revision='r2'),d.sources[1]))
    elif mode=='content':
        r=d.rows[0];d=replace(d,rows=(replace(r,values=(r.values[0]+.001,)+r.values[1:]),)+d.rows[1:])
    elif mode!='base':raise AssertionError('UNKNOWN_MODE')
    out=assembly.assemble(d)
    result={'mode':mode,'context':before,'seed':seed,'hash_probe':hash('invented-seed-probe'),
            'features':list(d.feature_names),
            'row_ids':[r.row_id for r in d.rows], 'train_ids':list(d.train_ids),
            'evaluation_ids':list(d.evaluation_ids),'receipt_hash':d.receipt.row_ids_sha256,
            'window':{f.name:getattr(d.window,f.name) for f in fields(d.window)},
            'assembly_status':out.status,'assembly_reasons':out.reasons}
    assert d.feature_names==FEATURES
    assert all(r.row_id==f'{r.symbol}:{r.decision_time}' for r in d.rows)
    def payload(p):
        return {'canonical':base64.b64encode(p.canonical).decode('ascii'),'sha256':p.sha256,
                'authority':{f.name:getattr(p,f.name) for f in fields(p) if not f.init}}
    if out.payload is not None:
        result['assembly']=payload(out.payload)
        by_id={r.row_id:r for r in d.rows};sources={s.series.symbol:s for s in d.sources}
        associations=[]
        for identity in d.train_ids+d.evaluation_ids:
            r=by_id[identity];s=sources[r.symbol]
            associations.append(eligibility.Association(identity,'train' if identity in d.train_ids else 'development_evaluation',
                d.window,invented_pair(r),s.identity,s.series.fixture_id,s.revision,'r1','invented-producer','p1',
                r.decision_time+1+HORIZON,'invented-horizon','invented-funding'))
        checked=eligibility.validate_associations(d,out,tuple(associations),
            tuple(eligibility.Revision(a.row_id,'r1') for a in associations),
            eligibility.Budgets(2000,400000,3000000,3000000,20000000,40000000))
        assert checked.status=='SYNTHETIC_ASSOCIATION_CONSISTENT',checked.reasons
        result['eligibility']=payload(checked.payload)
        result['eligible_ids']=list(checked.payload.row_ids)
        result['bound_assembly']=checked.payload.assembly_sha256
    assert policy()==before
    assert not events
result['guard_events']=events
print(json.dumps(result,sort_keys=True,separators=(',',':')))
'''


def bounded_process(command, environment, *, timeout=TIMEOUT, limit=OUTPUT_LIMIT):
    """Drain both pipes with one shared cap; kill/reap on overflow or timeout."""
    process = subprocess.Popen(command, cwd=ROOT, env=environment,
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, shell=False)
    chunks = [[], []]
    count = 0
    lock = threading.Lock()
    overflow = threading.Event()

    def drain(pipe, index):
        nonlocal count
        with pipe:
            while True:
                block = pipe.read(65536)
                if not block:
                    return
                with lock:
                    count += len(block)
                    if count > limit:
                        overflow.set()
                        process.kill()
                        return
                    chunks[index].append(block)

    threads = [threading.Thread(target=drain, args=(pipe, i), daemon=True)
               for i, pipe in enumerate((process.stdout, process.stderr))]
    for thread in threads:
        thread.start()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        raise AssertionError('CHILD_TIMEOUT') from None
    finally:
        for thread in threads:
            thread.join(timeout=5)
    if any(t.is_alive() for t in threads):
        raise AssertionError('CHILD_PIPE_NOT_CLOSED')
    if overflow.is_set():
        raise AssertionError('CHILD_OUTPUT_LIMIT')
    stdout, stderr = (b''.join(c) for c in chunks)
    if process.returncode or stderr:
        raise AssertionError('CHILD_FAILED: ' + stderr[:4000].decode('utf-8', 'replace'))
    return stdout


@lru_cache(maxsize=6)
def capture(seed, mode='base', precision=28):
    if mode not in ('base', 'revision', 'content') or precision not in (28, 29):
        raise ValueError('Undeclared process configuration')
    raw = bounded_process([sys.executable, '-B', '-s', '-S', '-c', CHILD,
                           str(ROOT), mode, str(precision), seed], child_environment(seed))
    result = json.loads(raw)
    expected_context = [precision, 'ROUND_HALF_EVEN', -999999, 999999, 1, 0,
                        ['DivisionByZero', 'InvalidOperation', 'Overflow']]
    if result['context'] != expected_context or result['guard_events']:
        raise AssertionError('CONTEXT_OR_ACCESS_MISMATCH')
    for key in ('assembly', 'eligibility'):
        if key in result:
            p = result[key]
            canonical = base64.b64decode(p['canonical'], validate=True)
            if hashlib.sha256(canonical).hexdigest() != p['sha256']:
                raise AssertionError('CONTENT_DIGEST_MISMATCH')
    # Cached bytes, never a mutable shared result object.
    return raw


class FreshProcessTests(unittest.TestCase):
    def test_hash_seeds_preserve_complete_commitments_and_bindings(self):
        runs = [json.loads(capture(s)) for s in SEEDS]
        self.assertEqual([r['seed'] for r in runs], list(SEEDS))
        self.assertEqual(len({r['hash_probe'] for r in runs}), len(SEEDS))
        for r in runs:
            r.pop('seed'); r.pop('hash_probe')
        self.assertEqual(runs[0], runs[1])
        self.assertEqual(runs[0], runs[2])
        r = runs[0]
        self.assertEqual(r['assembly_status'], 'FEATURE_ASSEMBLY_VALID')
        self.assertEqual(r['eligible_ids'], r['train_ids'] + r['evaluation_ids'])
        self.assertEqual(r['bound_assembly'], r['assembly']['sha256'])
        for key in ('assembly', 'eligibility'):
            a = r[key]['authority']
            self.assertEqual(a['training_authorization'], 'NOT AUTHORIZED')
            self.assertEqual(a['training_readiness'], 'UNVERIFIED')
        self.assertEqual(r['assembly']['authority']['source_completeness'], 'UNVERIFIED')
        self.assertEqual(r['eligibility']['authority']['external_provenance'], 'UNVERIFIED')
        self.assertEqual(r['eligibility']['authority']['external_completeness'], 'UNVERIFIED')
        self.assertEqual(r['eligibility']['authority']['financial_validity'], 'NOT ESTABLISHED')

    def test_revision_changes_bindings_and_changed_features_fail_closed(self):
        original = json.loads(capture('0'))
        revised = json.loads(capture('0', 'revision'))
        for key in ('assembly', 'eligibility'):
            self.assertNotEqual(original[key]['canonical'], revised[key]['canonical'])
            self.assertNotEqual(original[key]['sha256'], revised[key]['sha256'])
        bad = json.loads(capture('0', 'content'))
        self.assertEqual(bad['assembly_status'], 'INVALID')
        self.assertIn('CAUSAL_CONTENT_MISMATCH', bad['assembly_reasons'])
        self.assertNotIn('assembly', bad)
        self.assertNotIn('eligibility', bad)

    def test_different_context_is_not_identical_context_replay(self):
        a = json.loads(capture('0'))
        b = json.loads(capture('0', precision=29))
        self.assertNotEqual(a['context'], b['context'])
        self.assertEqual(a['assembly'], b['assembly'])
        self.assertNotEqual(a['eligibility']['canonical'], b['eligibility']['canonical'])
        self.assertNotEqual(a['eligibility']['sha256'], b['eligibility']['sha256'])

    def test_child_environment_and_execution_limits(self):
        self.assertEqual(set(child_environment('0')) - {'SYSTEMROOT'},
                         {'PYTHONHASHSEED', 'PYTHONIOENCODING'})
        with self.assertRaisesRegex(AssertionError, 'CHILD_OUTPUT_LIMIT'):
            bounded_process([sys.executable, '-B', '-s', '-S', '-c',
                             "import sys;sys.stdout.write('x'*100000)"],
                            child_environment('0'), limit=1024)
        with self.assertRaisesRegex(AssertionError, 'CHILD_TIMEOUT'):
            bounded_process([sys.executable, '-B', '-s', '-S', '-c',
                             'import time;time.sleep(5)'],
                            child_environment('0'), timeout=.1)


if __name__ == '__main__':
    unittest.main()
