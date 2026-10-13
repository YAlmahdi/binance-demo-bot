"""Inert synthetic SQL declarations. No SQL execution, reader or source locator."""
from dataclasses import dataclass, field, fields

from .authorization_binding import AUTHORIZATION_REASONS, MAX_DECLARED_ROWS, validate_authorization
from .contracts import Readiness
from .config import STEP, SYMBOLS
from .source_contracts import PROJECTION, TARGET_START, TARGET_END
from .adapter_access_contract import SCHEMA_ID, SCHEMA_VERSION


SQL_SCHEMA = "main"
SQL_TABLE = "fixture_candles"
ORDER_BY = ("symbol", "ordinal")
PLAN_REASONS = AUTHORIZATION_REASONS + (
    "QUERY_SCHEMA_MISMATCH", "QUERY_PROJECTION_MISMATCH", "QUERY_ORDER_MISMATCH",
    "QUERY_RESOURCE_LIMIT", "QUERY_CONTENT_MISMATCH", "QUERY_PARAMETERS_INVALID",
)


@dataclass(frozen=True, slots=True)
class QueryPlanRequest:
    """Allowlist selectors and resource ceiling, never caller-supplied SQL/params."""
    max_rows: int
    schema: str = SQL_SCHEMA
    table: str = SQL_TABLE
    schema_id: str = SCHEMA_ID
    schema_version: int = SCHEMA_VERSION
    projection: tuple[str, ...] = PROJECTION
    order_by: tuple[str, ...] = ORDER_BY
    evidence: str = field(default="SYNTHETIC_ONLY", init=False)

    def __post_init__(self):
        if not _request_shape(self):
            raise ValueError("Immutable primitive plan selectors required")


def _request_shape(value):
    for f in fields(value):
        try:
            v = getattr(value, f.name)
        except AttributeError:
            return False
        if f.name in ("max_rows", "schema_version"):
            valid = type(v) is int
        elif f.name in ("projection", "order_by"):
            valid = type(v) is tuple and all(type(p) is str for p in v)
        else:
            valid = type(v) is str
        if not valid:
            return False
    return True


def _sql():
    # Every parameter set is explicitly single-symbol. Identifiers are constants.
    return ("SELECT " + ",".join(PROJECTION) + " FROM main.fixture_candles"
            " INDEXED BY fixture_scope WHERE symbol=?"
            " AND interval=? AND open_time>=? AND open_time<? AND close_time>=? AND close_time<?"
            " ORDER BY symbol,ordinal LIMIT ?")


@dataclass(frozen=True, slots=True)
class QueryPlanDiagnostics:
    status: Readiness
    reasons: tuple[str, ...] = ()
    sql: str | None = None
    parameters: tuple[tuple[str | int, ...], ...] = ()
    declared_bounds: tuple[int, ...] = ()
    expected_rows: int = 0
    evidence: str = field(default="SYNTHETIC_ONLY", init=False)
    authority: str = field(default="INERT_SQL_DECLARATION_ONLY", init=False)
    actual_authorization: str = field(default="NOT VERIFIED", init=False)
    risk_clearance: str = field(default="NOT CLEARED", init=False)

    def __post_init__(self):
        if (type(self.status) is not Readiness or type(self.reasons) is not tuple
                or any(type(r) is not str or r not in PLAN_REASONS for r in self.reasons)
                or self.reasons != tuple(r for r in PLAN_REASONS if r in self.reasons)
                or type(self.parameters) is not tuple
                or any(type(row) is not tuple or len(row) != 7
                       or any(type(v) not in (str, int) for v in row) for row in self.parameters)
                or type(self.declared_bounds) is not tuple
                or any(type(v) is not int for v in self.declared_bounds)
                or type(self.expected_rows) is not int
                or any(type(getattr(self, name)) is not str or getattr(self, name) != value for name, value in
                       (("evidence", "SYNTHETIC_ONLY"), ("authority", "INERT_SQL_DECLARATION_ONLY"),
                        ("actual_authorization", "NOT VERIFIED"), ("risk_clearance", "NOT CLEARED")))
                or ((self.status == Readiness.SUFFICIENT) != (not self.reasons))):
            raise ValueError("Ordered immutable query diagnostics only")
        if self.status == Readiness.SUFFICIENT:
            if (type(self.sql) is not str or self.sql != _sql()
                    or not 1 <= self.expected_rows <= MAX_DECLARED_ROWS
                    or len(self.declared_bounds) != 8 or not 1 <= len(self.parameters) <= 2):
                raise ValueError("Only bounded fixed SQL declarations supported")
        elif self.sql is not None or self.parameters or self.declared_bounds or self.expected_rows:
            raise ValueError("Rejected plans must contain no usable query")

    def __bool__(self):
        raise TypeError("An inert SQL plan never authorizes execution")


def _refused(status, reasons):
    ordered = tuple(r for r in PLAN_REASONS if r in reasons)
    return QueryPlanDiagnostics(status, ordered)


def build_query_plan(record, spec, manifest, request, *, evaluated_at):
    """Recheck approval/metadata; produce bounded per-symbol SQL declarations.

    No pagination or scope truncation. Strict-interior scope and admissible 4096
    rows mirror the separate fixture restrictions. One extra overflow sentinel
    per symbol is declared; it is not an increased total admission cap.
    """
    binding = validate_authorization(record, spec, manifest, evaluated_at=evaluated_at)
    if binding.status != Readiness.SUFFICIENT:
        return _refused(binding.status, binding.reasons)
    if type(request) is not QueryPlanRequest or not _request_shape(request):
        return _refused(Readiness.INVALID, ("INVALID_SCHEMA_OR_TIME",))
    invalid = []
    if request.evidence != "SYNTHETIC_ONLY":
        invalid.append("UNAPPROVED_SCOPE")
    if (request.schema != SQL_SCHEMA or request.table != SQL_TABLE
            or request.schema_id != manifest.schema_id or request.schema_version != manifest.schema_version):
        invalid.append("QUERY_SCHEMA_MISMATCH")
    if request.projection != PROJECTION:
        invalid.append("QUERY_PROJECTION_MISMATCH")
    if request.order_by != ORDER_BY:
        invalid.append("QUERY_ORDER_MISMATCH")
    if not TARGET_START < spec.context_start < spec.context_end < TARGET_END:
        invalid.append("UNAUTHORIZED_DATES")
    expected = (spec.context_end - spec.context_start) // STEP * len(spec.symbols)
    if not 1 <= expected <= request.max_rows <= record.max_rows <= MAX_DECLARED_ROWS:
        invalid.append("QUERY_RESOURCE_LIMIT")
    if invalid:
        return _refused(Readiness.INVALID, invalid)
    symbols = tuple(s for s in SYMBOLS if s in spec.symbols)
    per_symbol = (spec.context_end - spec.context_start) // STEP
    parameters = tuple((symbol, spec.interval, spec.context_start, spec.context_end,
                        spec.context_start, spec.context_end, per_symbol + 1) for symbol in symbols)
    bounds = (spec.context_start, spec.context_end, spec.prefix_start, spec.prefix_end,
              spec.start, spec.end, spec.horizon_end, spec.decision_time)
    return QueryPlanDiagnostics(Readiness.SUFFICIENT, sql=_sql(), parameters=parameters,
                                declared_bounds=bounds, expected_rows=expected)


def validate_query_plan(plan, record, spec, manifest, request, *, evaluated_at):
    """Recompute expected declarations; never trust a supplied successful plan."""
    expected = build_query_plan(record, spec, manifest, request, evaluated_at=evaluated_at)
    if expected.status != Readiness.SUFFICIENT:
        return expected
    if type(plan) is not QueryPlanDiagnostics:
        return _refused(Readiness.INVALID, ("QUERY_CONTENT_MISMATCH",))
    try:
        # Revalidate constructor invariants after any low-level field tampering.
        plan.__post_init__()
        same = plan == expected
    except (ValueError, TypeError, AttributeError):
        same = False
    if not same:
        return _refused(Readiness.INVALID, ("QUERY_CONTENT_MISMATCH",))
    return expected
