"""Read-only access diagnostics for process-owned, newly minted SQLite fixtures only."""
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import stat
import tempfile
import uuid

from ..data import Candle
from .config import STEP, SYMBOLS
from .contracts import ContractResult, Readiness
from .features import ObservedCandle, SyntheticSeries
from .loader_boundary import BoundaryDiagnostics, BoundaryRequest, _plain_input, assess_boundary, validate_request
from .source_contracts import PROJECTION, TARGET_START, TARGET_END, SourceExpectation, SourceMetadata, assess_source

VERSION = 1
MAX_ROWS = 4096  # A fixture resource bound, never a research/risk threshold.
ACCESS_PROJECTION = ("symbol", "interval", "ordinal") + PROJECTION + ("available_at",)
FIXTURE_SCHEMA = (
    "CREATE TABLE fixture_identity (fixture_id TEXT NOT NULL, schema_version INTEGER NOT NULL, revision TEXT NOT NULL, projection_json TEXT NOT NULL, provenance_json TEXT NOT NULL)",
    "CREATE TABLE fixture_candles (symbol TEXT NOT NULL, interval TEXT NOT NULL, ordinal INTEGER NOT NULL, open_time INTEGER NOT NULL, open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL, volume REAL NOT NULL, close_time INTEGER NOT NULL, quote_volume REAL NOT NULL, trades INTEGER NOT NULL, available_at INTEGER NOT NULL)",
    "CREATE INDEX fixture_scope ON fixture_candles (symbol, interval, open_time)",
)
_PROJECT = Path(__file__).resolve().parents[3]
_FIXTURES = {}
_REASONS = ("UNAPPROVED_SCOPE", "FIXTURE_NOT_OWNED", "FIXTURE_PATH_UNSAFE",
            "FIXTURE_IDENTITY_MISMATCH", "SCHEMA_MISMATCH", "SNAPSHOT_MISMATCH",
            "SCOPED_HASH_INVALID", "QUERY_DENIED", "INVALID_ROWS", "CANDLE_GAP",
            "SOURCE_OR_CAUSAL_INSUFFICIENT")


@dataclass(frozen=True)
class FixtureToken:
    fixture_id: str
    relative_name: str = "fixture.sqlite"

    def __post_init__(self):
        if type(self.fixture_id) is not str or type(self.relative_name) is not str:
            raise ValueError("Scalar fixture identity only")


@dataclass(frozen=True)
class FixtureSnapshot:
    provenance_sha256: str
    rows_sha256: str
    schema_version: int = VERSION
    projection: tuple[str, ...] = ACCESS_PROJECTION

    def __post_init__(self):
        if (type(self.provenance_sha256) is not str or type(self.rows_sha256) is not str
                or type(self.schema_version) is not int or type(self.projection) is not tuple
                or any(type(p) is not str for p in self.projection)):
            raise ValueError("Immutable snapshot metadata only")


@dataclass(frozen=True)
class SQLiteFixtureRequest:
    scope: BoundaryRequest
    fixture: FixtureToken
    snapshot: FixtureSnapshot
    sources: tuple[SourceMetadata, ...]
    evidence: str = "SYNTHETIC_ONLY"

    def __post_init__(self):
        if (type(self.scope) is not BoundaryRequest or type(self.fixture) is not FixtureToken
                or type(self.snapshot) is not FixtureSnapshot or type(self.sources) is not tuple
                or any(type(s) is not SourceMetadata for s in self.sources)
                or type(self.evidence) is not str):
            raise ValueError("Immutable typed synthetic fixture request required")


@dataclass(frozen=True)
class AccessDiagnostics:
    status: Readiness
    reasons: tuple[str, ...] = ()
    row_count: int = 0
    rows_sha256: str | None = None
    boundary: BoundaryDiagnostics | None = None
    evidence: str = field(default="SYNTHETIC_ONLY", init=False)
    historical_evidence: str = field(default="UNAUTHENTICATED / NOT VERIFIED", init=False)
    authority: str = field(default="DIAGNOSTICS_ONLY", init=False)
    risk_clearance: str = field(default="NOT CLEARED", init=False)

    def __post_init__(self):
        if (type(self.status) is not Readiness or type(self.reasons) is not tuple
                or any(r not in _REASONS for r in self.reasons)
                or type(self.row_count) is not int or self.row_count < 0
                or (self.rows_sha256 is not None and not _hex(self.rows_sha256))
                or (self.boundary is not None and type(self.boundary) is not BoundaryDiagnostics)
                or ((self.status == Readiness.SUFFICIENT) != (not self.reasons))):
            raise ValueError("Immutable access diagnostics only")
        object.__setattr__(self, "reasons", tuple(r for r in _REASONS if r in self.reasons))

    def __bool__(self):
        raise TypeError("Fixture consistency is not research or access authority")


class _Refused(Exception):
    def __init__(self, reason):
        self.reason = reason


def _hex(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _provenance(scope, sources):
    return _json({"version": VERSION, "scope": asdict(scope),
                  "sources": [asdict(s) for s in sorted(sources, key=lambda s: s.symbol)]})


def _rows_digest(scope, rows, projection=ACCESS_PROJECTION):
    """Hash only supplied/scoped row values, never a database file or omitted rows."""
    indices = tuple(ACCESS_PROJECTION.index(name) for name in projection)
    payload = {"version": VERSION, "scope": asdict(scope), "projection": projection,
               "rows": [tuple(row[i] for i in indices) for row in rows]}
    return hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()


def _file_key(path):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise _Refused("FIXTURE_PATH_UNSAFE")
    return info.st_dev, info.st_ino


def _check_path(lease):
    if (_file_key(lease["root"]) != lease["root_key"]
            or _file_key(lease["path"]) != lease["file_key"]):
        raise _Refused("FIXTURE_IDENTITY_MISMATCH")
    info = lease["path"].lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or lease["path"].resolve() != lease["path"]):
        raise _Refused("FIXTURE_PATH_UNSAFE")


class FixtureOwner:
    """Test provisioning only; a validation result can never mint this ownership."""
    def __init__(self, lease):
        self._lease = lease

    @property
    def token(self):
        return self._lease["token"]

    @property
    def path(self):
        return self._lease["path"]

    def seal(self):
        _check_path(self._lease)
        self._lease["sealed"] = True


@contextmanager
def temporary_fixture():
    """Mint one empty fixture under a fresh system temporary directory, not a path input."""
    temporary = tempfile.TemporaryDirectory(prefix="v2_sqlite_contract_")
    root = Path(temporary.name).absolute()
    token = FixtureToken(uuid.uuid4().hex)
    lease = {"root": root, "path": root / token.relative_name, "token": token,
             "root_key": _file_key(root), "file_key": None, "sealed": False}
    if root.is_relative_to(_PROJECT):
        temporary.cleanup()
        raise _Refused("FIXTURE_PATH_UNSAFE")
    _FIXTURES[token.fixture_id] = lease
    try:
        with lease["path"].open("xb"):
            pass
        lease["file_key"] = _file_key(lease["path"])
        yield FixtureOwner(lease)
    finally:
        # The only recursive cleanup target is the exact newly minted temp root.
        if _file_key(root) != lease["root_key"]:
            raise _Refused("FIXTURE_PATH_UNSAFE")
        temporary.cleanup()
        _FIXTURES.pop(token.fixture_id, None)


def _audited_connection(value):
    """Runner guard support: exact build path or exact sealed read-only URI only."""
    if type(value) is not str:
        return False
    return any((not l["sealed"] and value == str(l["path"])) or
               (l["sealed"] and value == l["path"].as_uri() + "?mode=ro")
               for l in _FIXTURES.values())


def _lease_for(token):
    if type(token) is not FixtureToken or type(token.fixture_id) is not str:
        raise _Refused("FIXTURE_NOT_OWNED")
    if token.relative_name != "fixture.sqlite":
        raise _Refused("FIXTURE_PATH_UNSAFE")
    lease = _FIXTURES.get(token.fixture_id)
    if lease is None or lease["token"] is not token or not lease["sealed"]:
        raise _Refused("FIXTURE_NOT_OWNED")
    _check_path(lease)
    return lease


_SCHEMA_QUERY = "SELECT name, type, sql FROM main.sqlite_schema ORDER BY name"
_META_QUERY = "SELECT fixture_id, schema_version, revision, projection_json, provenance_json FROM main.fixture_identity"


class _QueryGate:
    def __init__(self, scope):
        symbols = tuple(s for s in SYMBOLS if s in scope.symbols)
        slots = ",".join("?" for _ in symbols)
        sql = ("SELECT " + ",".join(ACCESS_PROJECTION) +
               " FROM main.fixture_candles INDEXED BY fixture_scope WHERE symbol IN (" + slots +
               ") AND interval=? AND open_time>=? AND open_time<? AND close_time>=? AND close_time<?"
               " ORDER BY symbol,ordinal LIMIT ?")
        self.queries = {"schema": (_SCHEMA_QUERY, ()), "metadata": (_META_QUERY, ()),
                        "rows": (sql, symbols + (scope.interval, scope.start, scope.end,
                                                 scope.start, scope.end, MAX_ROWS + 1))}
        self.phase = None

    def authorizer(self, action, arg1, arg2, database, trigger):
        if trigger is not None:
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_TRANSACTION:
            return sqlite3.SQLITE_OK if self.phase == "transaction" and arg1 in ("BEGIN", "ROLLBACK") else sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_SELECT and self.phase in self.queries:
            return sqlite3.SQLITE_OK
        columns = {"schema": {"sqlite_master": ("name", "type", "sql")},
                   "metadata": {"fixture_identity": ("fixture_id", "schema_version", "revision", "projection_json", "provenance_json")},
                   "rows": {"fixture_candles": ACCESS_PROJECTION}}
        if (action == sqlite3.SQLITE_READ and database == "main"
                and arg2 in columns.get(self.phase, {}).get(arg1, ())):
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    def execute(self, connection, phase, sql, parameters):
        if self.queries.get(phase) != (sql, parameters):
            raise _Refused("QUERY_DENIED")
        self.phase = phase
        return connection.execute(sql, parameters).fetchmany(MAX_ROWS + 1)


@contextmanager
def _reader(lease, scope):
    _check_path(lease)
    con = sqlite3.connect(lease["path"].as_uri() + "?mode=ro", uri=True,
                          timeout=1.0, isolation_level=None, cached_statements=0)
    try:
        con.execute("PRAGMA query_only=ON")
        con.execute("PRAGMA trusted_schema=OFF")
        if con.execute("PRAGMA query_only").fetchone() != (1,):
            raise _Refused("QUERY_DENIED")
        con.enable_load_extension(False)
        gate = _QueryGate(scope)
        con.set_authorizer(gate.authorizer)
        gate.phase = "transaction"
        con.execute("BEGIN")
        _check_path(lease)
        yield con, gate
        _check_path(lease)
    finally:
        con.close()


def _validate_request(request):
    if type(request) is not SQLiteFixtureRequest or request.evidence != "SYNTHETIC_ONLY":
        raise _Refused("UNAPPROVED_SCOPE")
    scope = request.scope
    if (validate_request(scope).status != Readiness.SUFFICIENT
            or not TARGET_START < scope.start < scope.end < TARGET_END
            or (scope.end - scope.start) // STEP * len(scope.symbols) > MAX_ROWS):
        raise _Refused("UNAPPROVED_SCOPE")
    snapshot = request.snapshot
    if (type(snapshot.schema_version) is not int or snapshot.schema_version != VERSION
            or type(snapshot.projection) is not tuple or snapshot.projection != ACCESS_PROJECTION
            or not _hex(snapshot.rows_sha256) or not _hex(snapshot.provenance_sha256)):
        raise _Refused("SNAPSHOT_MISMATCH")
    if (type(request.sources) is not tuple
            or not all(type(s) is SourceMetadata and _plain_input(s) for s in request.sources)
            or tuple(s.symbol for s in request.sources) != tuple(s for s in SYMBOLS if s in scope.symbols)):
        raise _Refused("SNAPSHOT_MISMATCH")
    expected = SourceExpectation(scope.scope_id, scope.source_id, scope.revision, scope.start, scope.end)
    for source in request.sources:
        if (assess_source(source, expected).status != Readiness.SUFFICIENT
                or source.mode != scope.mode or source.decision_time != scope.decision_time):
            raise _Refused("SNAPSHOT_MISMATCH")
    provenance = _provenance(scope, request.sources)
    if hashlib.sha256(provenance.encode()).hexdigest() != snapshot.provenance_sha256:
        raise _Refused("SNAPSHOT_MISMATCH")
    return provenance


def inspect_fixture(request):
    """Connect only after authorization, fixture ownership and snapshot metadata checks."""
    try:
        provenance = _validate_request(request)
        lease = _lease_for(request.fixture)
        scope = request.scope
        with _reader(lease, scope) as (con, gate):
            schema = gate.execute(con, "schema", *gate.queries["schema"])
            expected = {"fixture_identity": ("table", FIXTURE_SCHEMA[0]),
                        "fixture_candles": ("table", FIXTURE_SCHEMA[1]),
                        "fixture_scope": ("index", FIXTURE_SCHEMA[2])}
            if (any(any(type(v) is not str for v in row) for row in schema)
                    or {name: (kind, " ".join(sql.split())) for name, kind, sql in schema} != expected):
                raise _Refused("SCHEMA_MISMATCH")
            metadata = gate.execute(con, "metadata", *gate.queries["metadata"])
            wanted = (request.fixture.fixture_id, VERSION, scope.revision,
                      _json(ACCESS_PROJECTION), provenance)
            if metadata != [wanted]:
                raise _Refused("SNAPSHOT_MISMATCH")
            rows = gate.execute(con, "rows", *gate.queries["rows"])
            if len(rows) > MAX_ROWS:
                raise _Refused("INVALID_ROWS")
            digest = _rows_digest(scope, rows)
            if digest != request.snapshot.rows_sha256:
                raise _Refused("SCOPED_HASH_INVALID")
            series = []
            for source in request.sources:
                selected = [r for r in rows if r[0] == source.symbol]
                if _rows_digest(scope, selected, PROJECTION) != source.scoped_hash.digest:
                    raise _Refused("SCOPED_HASH_INVALID")
                if [r[2] for r in selected] != list(range(len(selected))):
                    raise _Refused("INVALID_ROWS")
                observations = tuple(ObservedCandle(Candle(*r[3:-1]), r[-1]) for r in selected)
                series.append(SyntheticSeries(source.symbol, observations, scope.source_id))
            boundary = assess_boundary(scope, sources=request.sources, series=tuple(series), funding=())
            checks = [r for d in boundary.symbols for r in (d.source, d.structure, d.causal)]
            if any(r.status == Readiness.INVALID for r in checks):
                return AccessDiagnostics(Readiness.INVALID, ("INVALID_ROWS",), len(rows), digest, boundary)
            if len(rows) != (scope.end - scope.start) // STEP * len(scope.symbols):
                return AccessDiagnostics(Readiness.INSUFFICIENT, ("CANDLE_GAP",), len(rows), digest, boundary)
            if any(r.status != Readiness.SUFFICIENT for r in checks):
                return AccessDiagnostics(Readiness.INSUFFICIENT, ("SOURCE_OR_CAUSAL_INSUFFICIENT",), len(rows), digest, boundary)
            return AccessDiagnostics(Readiness.SUFFICIENT, (), len(rows), digest, boundary)
    except _Refused as exc:
        return AccessDiagnostics(Readiness.INVALID, (exc.reason,))
    except sqlite3.DatabaseError:
        return AccessDiagnostics(Readiness.INVALID, ("QUERY_DENIED",))
    except (ValueError, TypeError, AttributeError, ArithmeticError, OSError):
        return AccessDiagnostics(Readiness.INVALID, ("INVALID_ROWS",))
