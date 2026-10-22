"""Pure synthetic label association, never label production or training authority.

v1 requires one pair for every declared train/evaluation ID, in that order.
End-cutoff/causal exclusions remain in the original assembly coverage. This is
not a label-based population filter and does not certify a training population.
Source, producer, horizon and funding references are synthetic declarations.
Revision inventories must declare one unbranched root-to-current chain per row;
this proves consistency of the supplied chain, never historical completeness.

Encoding extends assembly's tagged ASCII JSON convention with bool [b,0|1]
and finite Decimal [d,sign,digit-string,exponent-string], preserving scale and
signed zero without rounding. Exact whitelisted dataclass fields are encoded in
declaration order. Content covers the assembly commitment, associations, revision
inventory, caller budgets and Decimal context (not transient flags).

Budgets count pairs, association/lineage and compared-feature nodes, text codepoints, numeric work characters
(Decimal digits plus absolute exponent plus one), encoded bytes and logical work.
Work counts nodes, caller Decimal precision, declared assembly work ceiling and
one comparison per pair per assembly row. These are explicit accounting units,
not wall-clock/OS memory limits. Feature reconstruction also obeys all existing
declaration.budgets ceilings; it is not counted again in association byte/node
counters. Input allocations are outside this contract.
Existing ActionOutcome/PairedOutcome checks run unchanged in an isolated copy of
the recorded caller Decimal context. Their acceptance is conditional consistency,
not a new ledger check or proof of which code/inputs produced an outcome.

Precedence: malformed/resource/contradictory evidence INVALID; otherwise missing
or excluded evidence INSUFFICIENT; otherwise SYNTHETIC_ASSOCIATION_CONSISTENT.
Reasons are sorted/deduplicated. Neither failed state retains a payload.
"""
from dataclasses import dataclass, field, fields
from decimal import Decimal, DecimalException, getcontext, localcontext
import hashlib
import json
import math

from ..backtest import Trade
from . import assembly
from .features import FeatureRow, SyntheticSeries
from .labels import ActionOutcome, PairedOutcome
from .opportunities import Opportunity
from .validation import DevelopmentWindow, IntervalRow, partition_reason


@dataclass(frozen=True)
class Budgets:
    pairs: int
    nodes: int
    text: int
    numeric_chars: int
    encoded_bytes: int
    work: int


@dataclass(frozen=True)
class Association:
    row_id: str
    stage: str
    window: DevelopmentWindow
    pair: PairedOutcome | None
    source_id: str | None
    fixture_id: str | None
    source_revision: str | None
    revision: str | None
    producer_id: str | None
    producer_revision: str | None
    horizon_end: int | None
    horizon_evidence: str | None
    funding_evidence: str | None
    evidence: str = "SYNTHETIC_DECLARATION"


@dataclass(frozen=True)
class Revision:
    row_id: str
    revision: str
    supersedes: str | None = None


@dataclass(frozen=True)
class Payload:
    canonical: bytes
    sha256: str
    assembly_sha256: str
    row_ids: tuple[str, ...]
    coverage: tuple
    usage: tuple[tuple[str, int], ...]
    declared_provenance: str = field(default="SYNTHETIC_DECLARATION_ONLY", init=False)
    external_provenance: str = field(default="UNVERIFIED", init=False)
    label_provenance: str = field(default="UNVERIFIED", init=False)
    external_completeness: str = field(default="UNVERIFIED", init=False)
    training_readiness: str = field(default="UNVERIFIED", init=False)
    training_authorization: str = field(default="NOT AUTHORIZED", init=False)
    financial_validity: str = field(default="NOT ESTABLISHED", init=False)


@dataclass(frozen=True)
class Result:
    status: str
    reasons: tuple[str, ...]
    payload: Payload | None = None

    def __post_init__(self):
        if (type(self.reasons) is not tuple or any(type(r) is not str for r in self.reasons)
                or self.reasons != tuple(sorted(set(self.reasons)))
                or self.status not in ("INVALID", "INSUFFICIENT", "SYNTHETIC_ASSOCIATION_CONSISTENT")
                or (self.status == "SYNTHETIC_ASSOCIATION_CONSISTENT") != (not self.reasons)
                or (self.status == "SYNTHETIC_ASSOCIATION_CONSISTENT") != (type(self.payload) is Payload)):
            raise ValueError("Only consistent synthetic association may retain a payload")
        if self.status != "SYNTHETIC_ASSOCIATION_CONSISTENT" and self.payload is not None:
            raise ValueError("Failed association cannot retain a payload")

    def __bool__(self):
        raise TypeError("Association grants no training or execution permission")


class _Reject(ValueError):
    pass


_RECORDS = (Budgets, Association, Revision, PairedOutcome, ActionOutcome,
            Opportunity, FeatureRow, Trade, DevelopmentWindow)


def validate_associations(declaration, feature_assembly, associations, revisions, budgets):
    """Recheck existing feature assembly; inspect supplied labels only. No simulator.

    Declaration is needed because an arbitrary constructed Result/hash is not
    validation evidence. Assembly is delegated once, after bounded preflight.
    """
    def rejected(invalid=(), missing=()):
        reasons = tuple(sorted(set(invalid) | set(missing)))
        return Result("INVALID" if invalid else "INSUFFICIENT", reasons)

    if type(budgets) is not Budgets or any(
            type(getattr(budgets, f.name, None)) is not int or getattr(budgets, f.name) < 0
            for f in fields(Budgets)):
        return rejected(("INVALID_BUDGET",))
    used = dict.fromkeys((f.name for f in fields(Budgets)), 0)

    def charge(name, count):
        used[name] += count
        if used[name] > getattr(budgets, name):
            raise _Reject("RESOURCE_" + name.upper())

    def capture(value, depth=0):
        if depth > 16:
            raise _Reject("INVALID_DEPTH")
        charge("nodes", 1); charge("work", 1)
        kind = type(value)
        if value is None:
            return None, ["n"]
        if kind is bool:
            return value, ["b", int(value)]
        if kind is str:
            charge("text", len(value)); return value, ["s", value]
        if kind in (int, float, Decimal):
            if kind is int:
                if value.bit_length() > budgets.numeric_chars * 4:
                    raise _Reject("RESOURCE_NUMERIC_CHARS")
                text = str(value); charge("numeric_chars", len(text))
                wire = ["i", text]
            elif kind is float:
                if not math.isfinite(value):
                    raise _Reject("INVALID_NUMBER")
                text = value.hex(); charge("numeric_chars", len(text)); wire = ["f", text]
            else:
                if not value.is_finite():
                    raise _Reject("INVALID_NUMBER")
                sign, digits, exponent = value.as_tuple()
                charge("numeric_chars", len(digits) + abs(exponent) + 1)
                wire = ["d", sign, "".join(map(str, digits)), str(exponent)]
            return value, wire
        if kind is tuple:
            if len(value) > budgets.nodes - used["nodes"]:
                raise _Reject("RESOURCE_NODES")
            pairs = tuple(capture(v, depth + 1) for v in value)
            return tuple(p[0] for p in pairs), ["t", [p[1] for p in pairs]]
        if kind in _RECORDS:
            pairs = tuple((f.name, capture(getattr(value, f.name), depth + 1)) for f in fields(kind))
            values = {name: pair[0] for name, pair in pairs}
            if kind is Trade and any(type(values[f.name]) is not
                    {"Decimal": Decimal, "int": int, "str": str}[f.type] for f in fields(Trade)):
                raise _Reject("INVALID_TRADE_SCHEMA")
            if kind is Opportunity and type(values["features"]) is not FeatureRow:
                raise _Reject("INVALID_OPPORTUNITY_SCHEMA")
            if kind is PairedOutcome and (type(values["opportunity"]) is not Opportunity or
                    any(v is not None and type(v) is not ActionOutcome for v in (values["long"], values["short"]))):
                raise _Reject("INVALID_PAIR_SCHEMA")
            if kind is PairedOutcome and any(values[name] is not None and values[name].side != side
                    for name, side in (("long", "LONG"), ("short", "SHORT"))):
                raise _Reject("WRONG_ACTION_SIDE")
            if kind is PairedOutcome and (values["long"] is None or values["short"] is None):
                # An explicitly absent action is missing evidence, not a usable pair.
                owned = object.__new__(PairedOutcome)
                for name, item in values.items(): object.__setattr__(owned, name, item)
            else:
                owned = kind(**values)
            return owned, ["r", kind.__name__, [[name, pair[1]] for name, pair in pairs]]
        raise _Reject("INVALID_TYPE")

    try:
        if (type(declaration) is not assembly.Declaration or type(feature_assembly) is not assembly.Result
                or type(associations) is not tuple or type(revisions) is not tuple):
            return rejected(("INVALID_SCHEMA",))
        if (type(feature_assembly.status) is not str or type(feature_assembly.reasons) is not tuple
                or any(type(r) is not str for r in feature_assembly.reasons)):
            return rejected(("INVALID_ASSEMBLY_PAYLOAD",))
        assembly.Result(feature_assembly.status, feature_assembly.reasons, feature_assembly.payload)
        if feature_assembly.status == "INVALID":
            return rejected(("FEATURE_ASSEMBLY_INVALID",))
        unavailable = feature_assembly.status != "FEATURE_ASSEMBLY_VALID"
        if not unavailable and type(feature_assembly.payload) is not assembly.Payload:
            return rejected(("INVALID_ASSEMBLY_PAYLOAD",))
        binding = feature_assembly.payload
        if not unavailable and (type(binding.canonical) is not bytes or type(binding.sha256) is not str
                or len(binding.sha256) != 64 or any(c not in "0123456789abcdef" for c in binding.sha256)):
            return rejected(("INVALID_ASSEMBLY_PAYLOAD",))
        charge("pairs", len(associations))
        # Preserve caller flags/traps; no replacement financial arithmetic policy.
        context = getcontext().copy()
        charge("work", context.prec)
        policy = (context.prec, context.rounding, context.Emin, context.Emax,
                  context.capitals, context.clamp,
                  tuple(sorted(signal.__name__ for signal, enabled in context.traps.items() if enabled)))
        with localcontext(context):
            rows, row_wire = capture(associations)
            lineage, lineage_wire = capture(revisions)
        _, budget_wire = capture(budgets)
        _, policy_wire = capture(policy)
        invalid, missing = [], []
        if any(type(a) is not Association for a in rows) or any(type(r) is not Revision for r in lineage):
            return rejected(("INVALID_SCHEMA",))
        if (type(declaration.train_ids) is not tuple or type(declaration.evaluation_ids) is not tuple
                or type(declaration.rows) is not tuple or type(declaration.sources) is not tuple):
            return rejected(("INVALID_DECLARATION",))
        if (len(declaration.train_ids) + len(declaration.evaluation_ids) > budgets.pairs
                or len(declaration.rows) > budgets.nodes):
            raise _Reject("RESOURCE_PAIRS")
        if len(declaration.sources) != 2:
            return rejected(("INVALID_DECLARATION",))
        expected = declaration.train_ids + declaration.evaluation_ids
        if (any(type(i) is not str for i in expected)
                or len(set(expected)) != len(expected)
                or type(declaration.window) is not DevelopmentWindow
                or any(type(getattr(declaration.window, n)) is not int
                       for n in ("train_start", "evaluation_start", "evaluation_end"))
                or type(declaration.window.evidence) is not str
                or any(type(r) is not FeatureRow or type(r.symbol) is not str
                       or type(r.decision_time) is not int
                       or type(r.status) is not str or type(r.reason) is not str
                       or (r.values is not None and (type(r.values) is not tuple
                           or any(type(v) not in (int, float) for v in r.values)))
                       or (r.atr14 is not None and type(r.atr14) not in (int, float))
                       for r in declaration.rows)
                or any(type(s) is not assembly.Source or type(s.series) is not SyntheticSeries
                       or any(type(v) is not str for v in
                              (s.identity, s.revision, s.series.symbol, s.series.fixture_id))
                       for s in declaration.sources)):
            return rejected(("INVALID_DECLARATION",))
        charge("work", len(rows) * (len(declaration.rows) + 1))
        if len(declaration.rows) > budgets.nodes or len(expected) > budgets.pairs:
            raise _Reject("RESOURCE_PAIRS")
        by_id = {r.row_id: r for r in declaration.rows}
        sources = {s.series.symbol: s for s in declaration.sources}
        if len(by_id) != len(declaration.rows) or len(sources) != len(declaration.sources):
            return rejected(("INVALID_DECLARATION",))
        ids = tuple(a.row_id for a in rows)
        if any(type(i) is not str or not i for i in ids):
            invalid.append("INVALID_ROW_ID")
        if len(set(ids)) != len(ids): invalid.append("DUPLICATE_ASSOCIATION")
        if set(ids) - set(expected): invalid.append("ORPHAN_ASSOCIATION")
        if set(expected) - set(ids): missing.append("MISSING_ASSOCIATION")
        if ids != tuple(i for i in expected if i in set(ids)):
            invalid.append("ASSOCIATION_ORDER")
        chains = {}
        for rev in lineage:
            if (any(type(v) is not str or not v for v in (rev.row_id, rev.revision))
                    or (rev.supersedes is not None and (type(rev.supersedes) is not str or not rev.supersedes))):
                invalid.append("INVALID_REVISION"); continue
            if rev.row_id not in expected: invalid.append("ORPHAN_REVISION")
            chain = chains.setdefault(rev.row_id, {})
            if rev.revision in chain: invalid.append("DUPLICATE_REVISION")
            chain[rev.revision] = rev.supersedes
        for identity, chain in chains.items():
            parents = [p for p in chain.values() if p is not None]
            if len(parents) != len(set(parents)): invalid.append("REVISION_FORK")
            if set(parents) - set(chain): missing.append("MISSING_PREDECESSOR")
            for start in chain:
                seen, cursor = set(), start
                while cursor in chain:
                    if cursor in seen:
                        invalid.append("REVISION_CYCLE"); break
                    seen.add(cursor); cursor = chain[cursor]
                    charge("work", 1)
            if len(set(chain) - set(parents)) != 1: invalid.append("REVISION_HEAD_CONFLICT")
        for a in rows:
            if a.row_id not in expected: continue
            row = by_id[a.row_id]; source = sources[row.symbol]
            if a.evidence != "SYNTHETIC_DECLARATION": invalid.append("UNAPPROVED_AUTHORITY")
            for name in ("source_id", "fixture_id", "source_revision", "revision", "producer_id",
                         "producer_revision", "horizon_evidence", "funding_evidence"):
                value = getattr(a, name)
                if value is None: missing.append("MISSING_" + name.upper())
                elif type(value) is not str or not value: invalid.append("INVALID_" + name.upper())
            for actual, wanted in ((a.source_id, source.identity), (a.fixture_id, source.series.fixture_id),
                                   (a.source_revision, source.revision)):
                if actual is not None and actual != wanted: invalid.append("SOURCE_BINDING_MISMATCH")
            stage = "train" if a.row_id in declaration.train_ids else "development_evaluation"
            if a.stage != stage or a.window != declaration.window: invalid.append("FOLD_BINDING_MISMATCH")
            interval = IntervalRow(row.symbol, row.decision_time, row.decision_time + 1 + assembly.HORIZON)
            if partition_reason(interval, a.window, stage) != "ACCEPT": invalid.append("PARTITION_CONFLICT")
            if a.horizon_end is None: missing.append("MISSING_HORIZON")
            elif type(a.horizon_end) is not int or a.horizon_end != interval.label_end:
                invalid.append("HORIZON_CONFLICT")
            chain = chains.get(a.row_id, {})
            if a.revision not in chain: missing.append("MISSING_REVISION")
            elif a.revision in chain.values(): invalid.append("SUPERSEDED_ASSOCIATION")
            if a.pair is None: missing.append("MISSING_PAIR"); continue
            if type(a.pair) is not PairedOutcome: invalid.append("INVALID_PAIR"); continue
            # Dataclass/number equality hides int/float and signed-zero changes.
            _, feature_wire = capture(row)
            _, paired_feature_wire = capture(a.pair.opportunity.features)
            if feature_wire != paired_feature_wire: invalid.append("FEATURE_CONTENT_MISMATCH")
            if a.pair.long is None or a.pair.short is None:
                missing.append("MISSING_ACTION"); continue
            if not a.pair.fit_eligible: missing.append("PAIR_NOT_VALID")
        # Contradictions dominate missing evidence. No usable partial subset.
        if invalid:
            return rejected(invalid, missing)
        if unavailable:
            return rejected(missing=missing + ["FEATURE_ASSEMBLY_UNAVAILABLE"])
        if type(declaration.budgets) is not assembly.Budgets:
            return rejected(("INVALID_DECLARATION",))
        if type(declaration.budgets.work) is not int or declaration.budgets.work < 0:
            return rejected(("INVALID_DECLARATION",))
        charge("work", declaration.budgets.work)
        _, binding_wire = capture(binding.sha256)
        wire = ["v2-label-association-1", binding_wire,
                row_wire, lineage_wire, budget_wire, policy_wire]
        chunks = []
        for chunk in json.JSONEncoder(ensure_ascii=True, separators=(",", ":"),
                                     sort_keys=True, allow_nan=False).iterencode(wire):
            encoded = chunk.encode("ascii"); charge("encoded_bytes", len(encoded)); chunks.append(encoded)
        canonical = b"".join(chunks)
        verified = assembly.assemble(declaration)
        if verified.status != "FEATURE_ASSEMBLY_VALID":
            return rejected(("ASSEMBLY_REVALIDATION_FAILED",) if verified.status == "INVALID" else (),
                            ("FEATURE_ASSEMBLY_INSUFFICIENT",) if verified.status != "INVALID" else ())
        if (verified.payload.canonical != binding.canonical or verified.payload.sha256 != binding.sha256):
            return rejected(("ASSEMBLY_CONTENT_MISMATCH",))
        if missing:
            return rejected(missing=missing)
        return Result("SYNTHETIC_ASSOCIATION_CONSISTENT", (), Payload(
            canonical, hashlib.sha256(canonical).hexdigest(), verified.payload.sha256,
            ids, verified.payload.coverage, tuple(used.items())))
    except _Reject as error:
        return rejected((str(error),))
    except (ValueError, TypeError, AttributeError, KeyError, OverflowError, PermissionError, DecimalException):
        return rejected(("INVALID_INPUT",))
