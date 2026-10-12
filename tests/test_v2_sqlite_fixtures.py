"""New temporary SQLite fixtures with invented records only; never repository DBs."""
from contextlib import closing
from dataclasses import asdict, astuple, FrozenInstanceError, fields, is_dataclass, replace
import hashlib
from pathlib import Path
import sqlite3
import stat
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_v2_loader_boundary import request as boundary_request, contexts, evidence
from demo_futures.data import Candle
from demo_futures.research_v2.config import HOUR, STEP
from demo_futures.research_v2.contracts import Readiness, result
from demo_futures.research_v2.features import ObservedCandle, SyntheticSeries
from demo_futures.research_v2.source_contracts import AvailabilityMode, OriginalAvailability, PROJECTION, TARGET_START, TARGET_END
from demo_futures.research_v2.sqlite_fixture_contract import (
    ACCESS_PROJECTION, FIXTURE_SCHEMA, MAX_ROWS, AccessDiagnostics, FixtureToken,
    FixtureSnapshot, SQLiteFixtureRequest, inspect_fixture, temporary_fixture,
    _FIXTURES, _QueryGate, _Refused, _json, _provenance, _reader, _rows_digest,
)


def scope(**changes):
    base = TARGET_START + 24 * HOUR
    return boundary_request(start=changes.pop('start', base), end=changes.pop('end', base + 22 * HOUR),
                            decision_time=changes.pop('decision_time', base + 18 * HOUR - 1), **changes)


def fixture(owner, request_scope=None, *, transform=None, decoys=(), alter_schema=False,
            metadata_change=None, source_change=None):
    """All prices, receipts, identities and decoys are fictional test values."""
    request_scope = scope() if request_scope is None else request_scope
    sources, _, series = contexts(request_scope)
    rows = [(s.symbol, '5m', i, *astuple(o.candle), o.available_at)
            for s in series for i, o in enumerate(s.observations)]
    rows = rows if transform is None else transform(rows)
    sources = tuple(replace(m, scoped_hash=replace(m.scoped_hash, digest=_rows_digest(
        request_scope, [r for r in rows if r[0] == m.symbol], PROJECTION))) for m in sources)
    sources = sources if source_change is None else source_change(sources)
    provenance = _provenance(request_scope, sources)
    snapshot = FixtureSnapshot(hashlib.sha256(provenance.encode()).hexdigest(), _rows_digest(request_scope, rows))
    metadata = (owner.token.fixture_id, 1, request_scope.revision, _json(ACCESS_PROJECTION), provenance)
    if metadata_change is not None: metadata = metadata_change(metadata)
    with closing(sqlite3.connect(str(owner.path))) as connection:
        for sql in FIXTURE_SCHEMA: connection.execute(sql)
        if alter_schema: connection.execute('CREATE TABLE unexpected_table (value TEXT)')
        connection.execute('INSERT INTO fixture_identity VALUES (?,?,?,?,?)', metadata)
        connection.executemany('INSERT INTO fixture_candles VALUES (' + ','.join('?' for _ in ACCESS_PROJECTION) + ')', rows + list(decoys))
        connection.commit()
    owner.seal()
    return SQLiteFixtureRequest(request_scope, owner.token, snapshot, sources), rows


class SQLiteFixtureTests(unittest.TestCase):
    def test_valid_fixture_returns_only_diagnostics_and_unknown_funding(self):
        with temporary_fixture() as owner:
            req, rows = fixture(owner); out = inspect_fixture(req)
            self.assertEqual(out.status, Readiness.SUFFICIENT)
            self.assertEqual(out.row_count, len(rows))
            self.assertEqual(out.rows_sha256, req.snapshot.rows_sha256)
            self.assertEqual(out.historical_evidence, 'UNAUTHENTICATED / NOT VERIFIED')
            self.assertEqual(out.boundary.validation.status, Readiness.INSUFFICIENT)
            self.assertIn('FUNDING_COVERAGE_UNPROVEN', out.boundary.validation.reasons)

    def test_invalid_scopes_rejected_before_connection(self):
        with temporary_fixture() as owner:
            req, _ = fixture(owner)
            variants = (replace(req.scope, symbols=('XRPUSDT',)), replace(req.scope, interval='15m'),
                        replace(req.scope, end=TARGET_END + STEP), replace(req.scope, start=TARGET_START),
                        replace(req.scope, end=TARGET_END), replace(req.scope, end=req.scope.start),
                        replace(req.scope, start=req.scope.start + 1), replace(req.scope, evidence='REAL_HISTORY'))
            with patch('sqlite3.connect', side_effect=AssertionError('No connection allowed')):
                for bad in variants:
                    self.assertEqual(inspect_fixture(replace(req, scope=bad)).status, Readiness.INVALID)

    def test_valid_date_range_exceeding_fixture_budget_rejected_before_connection(self):
        with temporary_fixture() as owner:
            req, _ = fixture(owner)
            with patch('sqlite3.connect', side_effect=AssertionError('No connection allowed')):
                out = inspect_fixture(replace(req, scope=replace(req.scope, end=req.scope.start + 30 * 24 * HOUR)))
            self.assertEqual(out.reasons, ('UNAPPROVED_SCOPE',))

    def test_path_escapes_absolute_paths_and_uri_names_never_connect(self):
        with temporary_fixture() as owner:
            req, _ = fixture(owner)
            with patch('sqlite3.connect', side_effect=AssertionError('No unsafe connection')):
                for name in ('../outside.sqlite', '..\\outside.sqlite', 'C:/outside.sqlite', 'file:outside.sqlite?mode=ro', 'data/private.sqlite'):
                    out = inspect_fixture(replace(req, fixture=replace(req.fixture, relative_name=name)))
                    self.assertEqual(out.reasons, ('FIXTURE_PATH_UNSAFE',))

    def test_copied_unregistered_and_expired_tokens_never_connect(self):
        with temporary_fixture() as owner:
            req, _ = fixture(owner)
            with patch('sqlite3.connect', side_effect=AssertionError('No connection')):
                for token in (replace(req.fixture), FixtureToken('not-minted')):
                    self.assertEqual(inspect_fixture(replace(req, fixture=token)).reasons, ('FIXTURE_NOT_OWNED',))
        with patch('sqlite3.connect', side_effect=AssertionError('Expired fixture')):
            self.assertEqual(inspect_fixture(req).reasons, ('FIXTURE_NOT_OWNED',))

    def test_unsealed_fixture_never_connects(self):
        with temporary_fixture() as owner:
            req, _ = fixture(owner)
            _FIXTURES[owner.token.fixture_id]['sealed'] = False
            with patch('sqlite3.connect', side_effect=AssertionError('Not sealed')):
                self.assertEqual(inspect_fixture(req).reasons, ('FIXTURE_NOT_OWNED',))

    def test_symlink_and_windows_reparse_metadata_refused_before_connection(self):
        with temporary_fixture() as owner:
            req, _ = fixture(owner); original = Path.lstat
            for attributes, mode in ((0, stat.S_IFLNK), (0x400, stat.S_IFREG)):
                def mocked(path):
                    if path == owner.path:
                        return SimpleNamespace(st_mode=mode, st_file_attributes=attributes)
                    return original(path)
                with patch.object(Path, 'lstat', mocked), patch('sqlite3.connect', side_effect=AssertionError('Link connection')):
                    self.assertEqual(inspect_fixture(req).reasons, ('FIXTURE_PATH_UNSAFE',))

    def test_replaced_inode_or_root_identity_refused(self):
        with temporary_fixture() as owner:
            req, _ = fixture(owner); lease = _FIXTURES[owner.token.fixture_id]
            actual = lease['file_key']; lease['file_key'] = (actual[0], actual[1] + 1)
            try:
                with patch('sqlite3.connect', side_effect=AssertionError('Replaced fixture')):
                    self.assertEqual(inspect_fixture(req).reasons, ('FIXTURE_IDENTITY_MISMATCH',))
            finally: lease['file_key'] = actual

    def test_protected_symbol_and_interval_decoys_excluded(self):
        with temporary_fixture() as owner:
            s = scope(); prototype = ('BTCUSDT', '5m', 999, s.start, 'PROTECTED_DECOY', 0., 0., 0., 0., s.start + STEP - 1, 0., 0, s.start + STEP)
            protected = list(prototype); protected[3] = TARGET_END; protected[9] = TARGET_END + STEP - 1; protected[12] = TARGET_END + STEP
            other_symbol = list(prototype); other_symbol[0] = 'XRPUSDT'
            other_interval = list(prototype); other_interval[1] = '15m'
            before = list(prototype); before[3] = s.start - STEP; before[9] = s.start - 1
            req, rows = fixture(owner, s, decoys=(tuple(protected), tuple(other_symbol), tuple(other_interval), tuple(before)))
            out = inspect_fixture(req)
            self.assertEqual(out.status, Readiness.SUFFICIENT)
            self.assertEqual(out.row_count, len(rows))
            self.assertEqual(out.rows_sha256, _rows_digest(s, rows))

    def test_half_open_end_and_close_timestamp_decoys_excluded(self):
        with temporary_fixture() as owner:
            s = scope(); t = s.end
            decoy = ('BTCUSDT','5m',999,t,100.,101.,99.,100.,100.,t + STEP - 1,10000.,10,t + STEP)
            crosses = list(decoy); crosses[3] = s.start
            req, rows = fixture(owner, s, decoys=(decoy, tuple(crosses)))
            self.assertEqual(inspect_fixture(req).row_count, len(rows))

    def test_single_symbol_query_excludes_other_permitted_symbol(self):
        with temporary_fixture() as owner:
            s = scope(symbols=('BTCUSDT',)); t = s.start
            decoy = ('ETHUSDT','5m',999,t,100.,101.,99.,100.,100.,t + STEP - 1,10000.,10,t + STEP)
            req, rows = fixture(owner, s, decoys=(decoy,))
            self.assertEqual(inspect_fixture(req).row_count, len(rows))

    def test_query_allowlist_rejects_unscoped_sql_and_changed_parameters(self):
        with temporary_fixture() as owner:
            req, _ = fixture(owner); lease = _FIXTURES[owner.token.fixture_id]
            with _reader(lease, req.scope) as (con, gate):
                for sql, params in (('SELECT * FROM fixture_candles', ()),
                                    (gate.queries['rows'][0], ())):
                    with self.assertRaises(_Refused): gate.execute(con, 'rows', sql, params)

    def test_authorizer_denies_writes_attach_extensions_pragmas_and_extra_reads(self):
        with temporary_fixture() as owner:
            req, _ = fixture(owner); lease = _FIXTURES[owner.token.fixture_id]
            with _reader(lease, req.scope) as (con, gate):
                gate.phase = 'rows'
                sqls = ('UPDATE fixture_candles SET close=1', 'DELETE FROM fixture_candles',
                        'CREATE TABLE denied (v)', 'DROP TABLE fixture_candles',
                        "ATTACH DATABASE '' AS other", "SELECT load_extension('never-load')",
                        'PRAGMA database_list', 'PRAGMA query_only=OFF',
                        'SELECT sql FROM sqlite_master', 'SELECT random()', 'COMMIT')
                for sql in sqls:
                    with self.subTest(sql=sql), self.assertRaises(sqlite3.DatabaseError): con.execute(sql)
            self.assertEqual(inspect_fixture(req).status, Readiness.SUFFICIENT)

    def test_readonly_uri_query_only_and_snapshot_transaction(self):
        with temporary_fixture() as owner:
            req, _ = fixture(owner)
            with _reader(_FIXTURES[owner.token.fixture_id], req.scope) as (con, gate):
                self.assertTrue(con.in_transaction)
                self.assertEqual(gate.phase, 'transaction')
                with self.assertRaises(sqlite3.DatabaseError): con.execute('INSERT INTO fixture_identity VALUES (1,1,1,1,1)')

    def test_schema_drift_refused(self):
        with temporary_fixture() as owner:
            req, _ = fixture(owner, alter_schema=True)
            self.assertEqual(inspect_fixture(req).reasons, ('SCHEMA_MISMATCH',))

    def test_identity_version_revision_and_projection_drift_refused(self):
        for index, value in ((0,'other-fixture'), (1,2), (2,'r2'), (3,'["*"]')):
            with temporary_fixture() as owner:
                def change(row):
                    values = list(row); values[index] = value; return tuple(values)
                req, _ = fixture(owner, metadata_change=change)
                self.assertEqual(inspect_fixture(req).reasons, ('SNAPSHOT_MISMATCH',))

    def test_request_hash_and_projection_mismatch_before_connection(self):
        with temporary_fixture() as owner:
            req, _ = fixture(owner)
            with patch('sqlite3.connect', side_effect=AssertionError('Invalid manifest')):
                for changed in (replace(req.snapshot, provenance_sha256='0'*64),
                                replace(req.snapshot, projection=('close',)), replace(req.snapshot, schema_version=2)):
                    self.assertEqual(inspect_fixture(replace(req, snapshot=changed)).reasons, ('SNAPSHOT_MISMATCH',))

    def test_row_and_per_symbol_hash_mismatch(self):
        with temporary_fixture() as owner:
            req, _ = fixture(owner)
            self.assertEqual(inspect_fixture(replace(req, snapshot=replace(req.snapshot, rows_sha256='0'*64))).reasons,
                             ('SCOPED_HASH_INVALID',))
        with temporary_fixture() as owner:
            req, _ = fixture(owner, source_change=lambda sources: tuple(replace(s, scoped_hash=replace(s.scoped_hash, digest='0'*64)) for s in sources))
            self.assertEqual(inspect_fixture(req).reasons, ('SCOPED_HASH_INVALID',))

    def test_provenance_source_or_scope_mismatch_rejected_before_connection(self):
        with temporary_fixture() as owner:
            req, _ = fixture(owner)
            with patch('sqlite3.connect', side_effect=AssertionError('Source mismatch')):
                for changed in (replace(req.sources[0], revision='r2'), replace(req.sources[0], source_id='other')):
                    self.assertEqual(inspect_fixture(replace(req, sources=(changed, req.sources[1]))).status, Readiness.INVALID)

    def test_gaps_rejected_without_repair(self):
        with temporary_fixture() as owner:
            req, rows = fixture(owner, transform=lambda rows: [tuple([*r[:2], r[2]-int(r[2]>20), *r[3:]]) for r in rows if r[2]!=20])
            out = inspect_fixture(req)
            self.assertEqual(out.status, Readiness.INSUFFICIENT)
            self.assertEqual(out.row_count, len(rows))
            self.assertIn('CANDLE_GAP', out.reasons)

    def test_truncated_prefix_is_not_reseeded(self):
        with temporary_fixture() as owner:
            s = scope(symbols=('BTCUSDT',))
            req, _ = fixture(owner, s, transform=lambda rows: [tuple([*r[:2],r[2]-16,*r[3:]]) for r in rows if r[2]>=16])
            with patch('demo_futures.research_v2.loader_boundary.assess_candles', side_effect=AssertionError('No reseed')):
                out = inspect_fixture(req)
            self.assertEqual(out.status, Readiness.INSUFFICIENT)
            self.assertEqual(out.boundary.symbols[0].causal.reasons, ('CANDLE_GAP',))

    def test_raw_ordinal_order_preserved_and_unordered_timestamps_rejected(self):
        def reverse_times(rows):
            values = list(rows); a,b=values[20],values[21]
            values[20]=(*a[:3],*b[3:]); values[21]=(*b[:3],*a[3:]); return values
        with temporary_fixture() as owner:
            req, _ = fixture(owner, transform=reverse_times)
            self.assertEqual(inspect_fixture(req).status, Readiness.INVALID)

    def test_quality_flags_retained_without_new_exclusion(self):
        def wide(rows):
            return [tuple([*r[:5],103.,97.,*r[7:]]) if r[2]==215 else r for r in rows]
        with temporary_fixture() as owner:
            req, _ = fixture(owner, transform=wide); out=inspect_fixture(req)
            self.assertEqual(out.status, Readiness.SUFFICIENT)
            self.assertIn('RANGE_GT_5_PERCENT_REVIEW_ONLY', tuple(f.reason for f in out.boundary.symbols[0].flags))

    def test_exact_200_bar_warmup_and_insufficient_199(self):
        base=TARGET_START+24*HOUR
        for count,status in ((200,Readiness.SUFFICIENT),(199,Readiness.INSUFFICIENT)):
            with temporary_fixture() as owner:
                req,_=fixture(owner, scope(start=base+(216-count)*STEP))
                self.assertEqual(inspect_fixture(req).status,status)

    def test_supplied_receipts_preserved_and_late_candles_refused(self):
        with temporary_fixture() as owner:
            req,_=fixture(owner); out=inspect_fixture(req)
            self.assertEqual(out.boundary.symbols[0].original_availability,OriginalAvailability.UNKNOWN)
            self.assertEqual(out.boundary.symbols[0].retrieved_at,req.sources[0].retrieved_at)
            self.assertIsNone(out.boundary.symbols[0].original_receipt)
        with temporary_fixture() as owner:
            def late(rows):return [(*r[:-1],r[-1]+1) if r[2]==215 else r for r in rows]
            req,_=fixture(owner,transform=late); out=inspect_fixture(req)
            self.assertEqual(out.status,Readiness.INSUFFICIENT)
            self.assertIn('RECEIPT_LATE',out.boundary.symbols[0].causal.reasons)

    def test_strict_unknown_asof_claim_refused_before_connection(self):
        with temporary_fixture() as owner:
            req,_=fixture(owner,scope(mode=AvailabilityMode.REQUIRE_VERIFIED_ASOF))
            with patch('sqlite3.connect',side_effect=AssertionError('No asof evidence')):
                self.assertEqual(inspect_fixture(req).reasons,('SNAPSHOT_MISMATCH',))

    def test_deterministic_row_hash_across_distinct_owned_files(self):
        with temporary_fixture() as a, temporary_fixture() as b:
            left,_=fixture(a);right,_=fixture(b)
            self.assertNotEqual(left.fixture.fixture_id,right.fixture.fixture_id)
            self.assertEqual(inspect_fixture(left).rows_sha256,inspect_fixture(right).rows_sha256)

    def test_no_payload_or_capability_escalation(self):
        with temporary_fixture() as owner:
            req,_=fixture(owner);out=inspect_fixture(req)
            forbidden=(Candle,ObservedCandle,SyntheticSeries,sqlite3.Connection,FixtureToken,SQLiteFixtureRequest)
            def inspect(value):
                self.assertNotIsInstance(value,forbidden)
                self.assertFalse(callable(value))
                if is_dataclass(value):
                    for f in fields(value):inspect(getattr(value,f.name))
                elif type(value) is tuple:
                    for child in value:inspect(child)
            inspect(out)
            with self.assertRaises(TypeError):bool(out)
            self.assertEqual(inspect_fixture(out).reasons,('UNAPPROVED_SCOPE',))
            with self.assertRaises(FrozenInstanceError):req.evidence='REAL_HISTORY'
            with self.assertRaises(ValueError):replace(out,boundary=req)

    def test_mutable_request_and_success_result_not_authorization(self):
        with temporary_fixture() as owner:
            req,_=fixture(owner)
            with self.assertRaises(ValueError):replace(req,sources=list(req.sources))
            with self.assertRaises(ValueError):replace(req,fixture=result())
            with patch('sqlite3.connect',side_effect=AssertionError('Not authorization')):
                self.assertEqual(inspect_fixture(result()).reasons,('UNAPPROVED_SCOPE',))


if __name__ == '__main__':
    unittest.main()
