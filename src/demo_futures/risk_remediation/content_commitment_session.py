"""M7: consistency of a supplied synthetic assessment transcript, never authority.

M6 commits the entire raw M5 declaration, not inventory alone. Context includes
scope, snapshot/revision/time, evaluation, schema and algorithm. Same context
with conflicting commitments invalidates ALL members; otherwise later repeats
are insufficient. Later evaluations are separate contexts. Revision magnitude
does not imply supersession. No persistent state, complete history, trusted clock,
external ownership, financial aggregation, admission or execution is provided.

Preflight owns exact M7 metadata/limits; raw bindings are separately captured by
PUBLIC M6, once per observation. Only returned captured manifests participate in
reconciliation. No private M6 API is used. All semantic failures retain complete
bounded dependencies. Ordinary observable metadata replacement during preflight
is rejected; originals may change after capture without altering captured values.
There is no atomic cross-observation capture or malicious-interpreter guarantee.

Declared additive M6 limits are summed before calls, conservatively even for tiny
actual inputs. Each dimension is also capped per call. Metadata and integers have
separate limits. Auxiliary sorted indexes avoid pairwise payload comparisons and
preserve supplied order. Work is additive child work plus O(n log n) key comparisons
(bounded key/number widths); retained diagnostics use additive space. M6 temporary
buffers, Decimal.as_tuple allocation, previously allocated inputs, caller-large
limits and runtime overhead remain limitations, not OS or financial guarantees.
"""
from dataclasses import dataclass, field, replace

from ..research_v2.contracts import Readiness, valid_identity
from .inventory_lifecycle_binding import BindingDeclaration
from . import inventory_content_commitment as m6

INVALID = ("INVALID_SCHEMA", "INVALID_IDENTITY", "INVALID_TIME", "RESOURCE_BUDGET_EXCEEDED",
    "CAPTURE_CHANGED", "UNSUPPORTED_VERSION", "SCOPE_MISMATCH", "DUPLICATE_OBSERVATION_ID",
    "SEQUENCE_MISMATCH", "UNORDERED_OBSERVATIONS", "CLAIM_MISMATCH", "SNAPSHOT_ASSOCIATION_CONFLICT",
    "REVISION_IDENTITY_CONFLICT", "CONTEXT_CONTENT_CONFLICT", "M6_INVALID")
MISSING = ("MISSING_CLAIM", "FUTURE_UNAVAILABLE", "STALE_CONTEXT", "M6_INSUFFICIENT", "CONTEXT_REPLAY")
REASONS = INVALID + MISSING
PREFLIGHT = INVALID[:5]
SCOPE = ("owner_id", "source_id", "version")
ENCODING_FIELDS = ("max_nodes", "max_depth", "max_string_codepoints", "max_string_bytes",
    "max_decimal_digits", "max_exponent_bits", "max_integer_bits", "max_canonical_bytes")
TOTAL_FIELDS = ("max_nodes", "max_string_codepoints", "max_string_bytes", "max_decimal_digits", "max_canonical_bytes")
MANIFEST_FIELDS = ("schema", "algorithm", "owner_id", "source_id", "version", "snapshot_id",
    "revision", "snapshot_time", "evaluation_time", "byte_length", "digest")
OBSERVATION_FIELDS = ("observation_id", "sequence", "available_at", "raw_binding", "encoding_resources", "claimed_manifest")
TRANSCRIPT_FIELDS = ("session_id",) + SCOPE + ("evaluation_time", "prior", "candidate", "resources")
RESOURCE_FIELDS = ("max_observations", "max_metadata_chars", "max_integer_bits", "per_observation_ceiling",
    "max_total_nodes", "max_total_string_codepoints", "max_total_string_bytes", "max_total_decimal_digits", "max_total_canonical_bytes")
LABELS = (("authority", "SYNTHETIC_DIAGNOSTIC_ONLY"), ("history_scope", "SUPPLIED_TRANSCRIPT_ONLY"),
    ("external_provenance", "NOT VERIFIED"), ("external_replay_authority", "NOT VERIFIED"),
    ("aggregate_state", "BLOCKED"), ("risk_clearance", "NOT CLEARED"), ("evidence", "SYNTHETIC_ONLY"))


def _types(obj, fields):
    for name, kinds in fields:
        if not any(type(getattr(obj, name)) is k for k in (kinds if type(kinds) is tuple else (kinds,))):
            raise ValueError("Exact immutable fields required")


@dataclass(frozen=True, slots=True)
class TranscriptResources:
    max_observations: int
    max_metadata_chars: int
    max_integer_bits: int
    per_observation_ceiling: m6.EncodingResources
    max_total_nodes: int
    max_total_string_codepoints: int
    max_total_string_bytes: int
    max_total_decimal_digits: int
    max_total_canonical_bytes: int

    def __post_init__(self):
        _types(self, tuple((n, m6.EncodingResources if n == "per_observation_ceiling" else int) for n in RESOURCE_FIELDS))
        if any(not 0 <= getattr(self, n) <= m6.U64_MAX for n in RESOURCE_FIELDS if n != "per_observation_ceiling"):
            raise ValueError("Explicit nonnegative U64 processing limits required")


@dataclass(frozen=True, slots=True)
class ObservationDeclaration:
    observation_id: str
    sequence: int
    available_at: int
    raw_binding: BindingDeclaration
    encoding_resources: m6.EncodingResources
    claimed_manifest: m6.CommitmentManifest | None

    def __post_init__(self):
        _types(self, (("observation_id", str), ("sequence", int), ("available_at", int),
            ("raw_binding", BindingDeclaration), ("encoding_resources", m6.EncodingResources),
            ("claimed_manifest", (m6.CommitmentManifest, type(None)))))


@dataclass(frozen=True, slots=True)
class TranscriptDeclaration:
    session_id: str
    owner_id: str
    source_id: str
    version: str
    evaluation_time: int
    prior: tuple[ObservationDeclaration, ...]
    candidate: ObservationDeclaration
    resources: TranscriptResources

    def __post_init__(self):
        _types(self, tuple((n, str) for n in ("session_id",) + SCOPE) + (("evaluation_time", int),
            ("prior", tuple), ("candidate", ObservationDeclaration), ("resources", TranscriptResources)))


def _ordered(reasons):
    return tuple(r for r in REASONS if r in reasons)


def _status(reasons):
    return Readiness.INVALID if any(r in INVALID for r in reasons) else Readiness.INSUFFICIENT if reasons else Readiness.SUFFICIENT


def _labels(value, definitions=LABELS):
    if any(type(getattr(value, name)) is not str or getattr(value, name) != expected for name, expected in definitions):
        raise ValueError("Fixed synthetic authority required")


def _reason_shape(status, reasons):
    if (type(status) is not Readiness or type(reasons) is not tuple or any(type(r) is not str for r in reasons)
            or reasons != _ordered(reasons) or status is not _status(reasons)):
        raise ValueError("Readiness must reconcile with ordered reasons")


def _validate_m6(value):
    if type(value) is not m6.CommitmentDiagnostic:
        raise ValueError("Exact recomputed dependency required")
    _labels(value, (("authority", "SYNTHETIC_DIAGNOSTIC_ONLY"), ("evidence", "SYNTHETIC_ONLY"),
        ("aggregate_state", "BLOCKED"), ("risk_clearance", "NOT CLEARED")))
    replace(value)  # Public constructor validation; never a raw-input substitute.


@dataclass(frozen=True, slots=True)
class ObservationDiagnostic:
    observation_id: str
    sequence: int
    status: Readiness
    reasons: tuple[str, ...]
    commitment: m6.CommitmentDiagnostic
    authority: str = field(default="SYNTHETIC_DIAGNOSTIC_ONLY", init=False)
    history_scope: str = field(default="SUPPLIED_TRANSCRIPT_ONLY", init=False)
    external_provenance: str = field(default="NOT VERIFIED", init=False)
    external_replay_authority: str = field(default="NOT VERIFIED", init=False)
    aggregate_state: str = field(default="BLOCKED", init=False)
    risk_clearance: str = field(default="NOT CLEARED", init=False)
    evidence: str = field(default="SYNTHETIC_ONLY", init=False)

    def __post_init__(self):
        _types(self, (("observation_id", str), ("sequence", int)))
        if not valid_identity(self.observation_id) or self.sequence < 0:
            raise ValueError("Valid captured observation identity required")
        _labels(self)
        _reason_shape(self.status, self.reasons)
        _validate_m6(self.commitment)
        expected = ("M6_INVALID",) if self.commitment.status is Readiness.INVALID else ("M6_INSUFFICIENT",) if self.commitment.status is Readiness.INSUFFICIENT else ()
        if tuple(r for r in self.reasons if r in ("M6_INVALID", "M6_INSUFFICIENT")) != expected:
            raise ValueError("Every child failure must be retained")

    def __bool__(self):
        raise TypeError("Transcript diagnostics never authorize admission")


@dataclass(frozen=True, slots=True)
class TranscriptDiagnostic:
    status: Readiness
    reasons: tuple[str, ...] = ()
    observations: tuple[ObservationDiagnostic, ...] = ()
    candidate_manifest: m6.CommitmentManifest | None = None
    authority: str = field(default="SYNTHETIC_DIAGNOSTIC_ONLY", init=False)
    history_scope: str = field(default="SUPPLIED_TRANSCRIPT_ONLY", init=False)
    external_provenance: str = field(default="NOT VERIFIED", init=False)
    external_replay_authority: str = field(default="NOT VERIFIED", init=False)
    aggregate_state: str = field(default="BLOCKED", init=False)
    risk_clearance: str = field(default="NOT CLEARED", init=False)
    evidence: str = field(default="SYNTHETIC_ONLY", init=False)

    def __post_init__(self):
        _labels(self)
        _reason_shape(self.status, self.reasons)
        if type(self.observations) is not tuple or any(type(row) is not ObservationDiagnostic for row in self.observations):
            raise ValueError("Exact ordered observations required")
        for row in self.observations:
            _labels(row)
            replace(row)
        derived = _relations(self.observations, [row.commitment.manifest for row in self.observations])
        relational = ("DUPLICATE_OBSERVATION_ID", "SEQUENCE_MISMATCH", "SNAPSHOT_ASSOCIATION_CONFLICT",
            "REVISION_IDENTITY_CONFLICT", "CONTEXT_CONTENT_CONFLICT", "CONTEXT_REPLAY")
        for row, required in zip(self.observations, derived):
            if (any(reason not in row.reasons for reason in required)
                    or tuple(r for r in relational if r in row.reasons) != tuple(r for r in relational if r in required)):
                raise ValueError("Cross-row reasons must reconcile with captured results")
        if not self.observations:
            if not self.reasons or any(r not in PREFLIGHT for r in self.reasons):
                raise ValueError("Only structural preflight may omit children")
        elif self.reasons != _ordered(tuple(r for row in self.observations for r in row.reasons)):
            raise ValueError("All row reasons must be retained")
        if self.status is Readiness.SUFFICIENT:
            if (type(self.candidate_manifest) is not m6.CommitmentManifest
                    or self.candidate_manifest is not self.observations[-1].commitment.manifest
                    or any(row.sequence != i for i, row in enumerate(self.observations))):
                raise ValueError("Complete sufficient prefix and captured candidate required")
            replace(self.candidate_manifest)
        elif self.candidate_manifest is not None:
            raise ValueError("Failed transcript has no candidate manifest")

    def __bool__(self):
        raise TypeError("Transcript consistency is not trading authority")


class _Rejected(ValueError):
    pass


def _reject(reason="INVALID_SCHEMA"):
    raise _Rejected(reason)


def _shape(value, kind, names):
    if type(value) is not kind or tuple(kind.__dataclass_fields__) != names:
        _reject()
    if hasattr(value, "__dict__"):
        keys = tuple(object.__getattribute__(value, "__dict__"))
        if any(type(k) is not str for k in keys) or set(keys) != set(names):
            _reject()
    return tuple(object.__getattribute__(value, n) for n in names)


def _encoding(value, observed):
    values = _shape(value, m6.EncodingResources, ENCODING_FIELDS)
    if any(type(v) is not int or v < 0 or v > m6.U64_MAX for v in values):
        _reject()
    observed.append((value, ENCODING_FIELDS, values))
    return m6.EncodingResources(*values)


class _Meter:
    def __init__(self, resources, observed):
        values = _shape(resources, TranscriptResources, RESOURCE_FIELDS)
        for name, value in zip(RESOURCE_FIELDS, values):
            if name != "per_observation_ceiling" and (type(value) is not int or not 0 <= value <= m6.U64_MAX):
                _reject()
        ceiling = _encoding(values[3], observed)
        self.resources = TranscriptResources(*values[:3], ceiling, *values[4:])
        self.chars = 0
        self.totals = [0] * len(TOTAL_FIELDS)
        observed.append((resources, RESOURCE_FIELDS, values))

    def text(self, value, *, identity=False):
        if type(value) is not str:
            _reject()
        self.chars += len(value)
        if self.chars > self.resources.max_metadata_chars:
            _reject("RESOURCE_BUDGET_EXCEEDED")
        if identity and not valid_identity(value):
            _reject("INVALID_IDENTITY")

    def integer(self, value, *, time=False, signed=False):
        if type(value) is not int:
            _reject()
        if value < 0 and not signed:
            _reject("INVALID_TIME" if time else "INVALID_SCHEMA")
        if value.bit_length() > self.resources.max_integer_bits:
            _reject("RESOURCE_BUDGET_EXCEEDED")

    def encoding(self, value, observed):
        owned = _encoding(value, observed)
        if any(getattr(owned, n) > getattr(self.resources.per_observation_ceiling, n) for n in ENCODING_FIELDS):
            _reject("RESOURCE_BUDGET_EXCEEDED")
        for i, name in enumerate(TOTAL_FIELDS):
            self.totals[i] += getattr(owned, name)
            if self.totals[i] > getattr(self.resources, name.replace("max_", "max_total_", 1)):
                _reject("RESOURCE_BUDGET_EXCEEDED")
        return owned


def _capture(declaration):
    observed = []
    values = _shape(declaration, TranscriptDeclaration, TRANSCRIPT_FIELDS)
    session, owner, source, version, cutoff, prior, candidate, resources = values
    meter = _Meter(resources, observed)
    if type(prior) is not tuple:
        _reject()
    if len(prior) + 1 > meter.resources.max_observations:
        _reject("RESOURCE_BUDGET_EXCEEDED")
    for value in (session, owner, source, version):
        meter.text(value, identity=True)
    meter.integer(cutoff, time=True)
    rows = []
    # No unbounded concatenation of caller tuples before the length gate.
    for index in range(len(prior) + 1):
        original = prior[index] if index < len(prior) else candidate
        fields = _shape(original, ObservationDeclaration, OBSERVATION_FIELDS)
        identity, sequence, available, raw, encoding, claim = fields
        meter.text(identity, identity=True)
        meter.integer(sequence)
        meter.integer(available, time=True)
        if type(raw) is not BindingDeclaration:
            _reject()
        owned_encoding = meter.encoding(encoding, observed)
        if claim is not None:
            parts = _shape(claim, m6.CommitmentManifest, MANIFEST_FIELDS)
            for name, value in zip(MANIFEST_FIELDS, parts):
                if name in ("revision", "snapshot_time", "evaluation_time", "byte_length"):
                    # A bounded wrong claim is a semantic mismatch, not a
                    # reason to lose safe raw dependency reassessment.
                    meter.integer(value, signed=True)
                else:
                    meter.text(value)
            owned_claim = object.__new__(m6.CommitmentManifest)
            for name, value in zip(MANIFEST_FIELDS, parts):
                object.__setattr__(owned_claim, name, value)
            observed.append((claim, MANIFEST_FIELDS, parts))
        else:
            owned_claim = None
        rows.append(ObservationDeclaration(identity, sequence, available, raw, owned_encoding, owned_claim))
        observed.append((original, OBSERVATION_FIELDS, fields))
    observed.append((declaration, TRANSCRIPT_FIELDS, values))
    for original, names, refs in observed:
        current = _shape(original, type(original), names)
        if any(a is not b for a, b in zip(current, refs)):
            _reject("CAPTURE_CHANGED")
    return TranscriptDeclaration(session, owner, source, version, cutoff, tuple(rows[:-1]), rows[-1], meter.resources)


def _groups(indices, key):
    ordered = sorted(((key(i), i) for i in indices), key=lambda row: row[0])
    group, previous = [], None
    for value, index in ordered:
        if group and value != previous:
            yield group
            group = []
        group.append(index)
        previous = value
    if group:
        yield group


def _association(manifest):
    return tuple(getattr(manifest, n) for n in SCOPE + ("snapshot_id", "revision", "snapshot_time"))


def _relations(rows, manifests):
    reasons = [set() for _ in rows]
    for i, row in enumerate(rows):
        if row.sequence != i:
            reasons[i].add("SEQUENCE_MISMATCH")
    good = [i for i, manifest in enumerate(manifests) if manifest is not None]
    for before, after in zip(good, good[1:]):
        if manifests[after].evaluation_time < manifests[before].evaluation_time:
            reasons[after].add("UNORDERED_OBSERVATIONS")
    for group in _groups(range(len(rows)), lambda i: rows[i].observation_id):
        if len(group) > 1:
            for i in group:
                reasons[i].add("DUPLICATE_OBSERVATION_ID")
    for group in _groups(good, lambda i: _association(manifests[i])[:4]):
        first = _association(manifests[group[0]])[4:]
        if any(_association(manifests[i])[4:] != first for i in group):
            for i in group:
                reasons[i].add("SNAPSHOT_ASSOCIATION_CONFLICT")
    for group in _groups(good, lambda i: _association(manifests[i])[:3] + (manifests[i].revision,)):
        if any(manifests[i].snapshot_id != manifests[group[0]].snapshot_id for i in group):
            for i in group:
                reasons[i].add("REVISION_IDENTITY_CONFLICT")
    for group in _groups(good, lambda i: _association(manifests[i]) +
            (manifests[i].evaluation_time, manifests[i].schema, manifests[i].algorithm)):
        first = (manifests[group[0]].byte_length, manifests[group[0]].digest)
        if any((manifests[i].byte_length, manifests[i].digest) != first for i in group):
            for i in group:
                reasons[i].add("CONTEXT_CONTENT_CONFLICT")
        else:
            for i in group[1:]:
                reasons[i].add("CONTEXT_REPLAY")
    return reasons


def assess_transcript(declaration):
    """Recompute supplied raw observations; no external replay or admission claim."""
    try:
        d = _capture(declaration)
    except _Rejected as error:
        return TranscriptDiagnostic(Readiness.INVALID, (error.args[0],))
    except (AttributeError, ValueError):
        return TranscriptDiagnostic(Readiness.INVALID, ("INVALID_SCHEMA",))
    rows = d.prior + (d.candidate,)
    results = tuple(m6.commit_content(row.raw_binding, row.encoding_resources) for row in rows)
    reasons = [set() for _ in rows]
    manifests = [result.manifest for result in results]
    for i, (row, result) in enumerate(zip(rows, results)):
        _validate_m6(result)
        if row.sequence != i:
            reasons[i].add("SEQUENCE_MISMATCH")
        if row.available_at > d.evaluation_time:
            reasons[i].add("FUTURE_UNAVAILABLE")
        if result.status is Readiness.INVALID:
            reasons[i].add("M6_INVALID")
        elif result.status is Readiness.INSUFFICIENT:
            reasons[i].add("M6_INSUFFICIENT")
        claim = row.claimed_manifest
        if claim is None:
            reasons[i].add("MISSING_CLAIM")
        elif claim.schema != m6.SCHEMA or claim.algorithm != m6.ALGORITHM:
            reasons[i].add("UNSUPPORTED_VERSION")
        else:
            try:
                replace(claim)
            except ValueError:
                reasons[i].add("CLAIM_MISMATCH")
            if result.manifest is not None and any(getattr(claim, n) != getattr(result.manifest, n) for n in MANIFEST_FIELDS):
                reasons[i].add("CLAIM_MISMATCH")
        manifest = result.manifest
        if manifest is not None:
            if tuple(getattr(manifest, n) for n in SCOPE) != tuple(getattr(d, n) for n in SCOPE):
                reasons[i].add("SCOPE_MISMATCH")
            if manifest.evaluation_time > row.available_at:
                reasons[i].add("INVALID_TIME")
            if manifest.evaluation_time > d.evaluation_time:
                reasons[i].add("FUTURE_UNAVAILABLE")
            if i == len(rows) - 1 and manifest.evaluation_time < d.evaluation_time:
                reasons[i].add("STALE_CONTEXT")
        if i and row.available_at < rows[i - 1].available_at:
            reasons[i].add("UNORDERED_OBSERVATIONS")
    for actual, derived in zip(reasons, _relations(rows, manifests)):
        actual.update(derived)
    output = tuple(ObservationDiagnostic(row.observation_id, row.sequence, _status(reasons[i]),
        _ordered(reasons[i]), results[i]) for i, row in enumerate(rows))
    combined = _ordered(tuple(r for row in output for r in row.reasons))
    status = _status(combined)
    return TranscriptDiagnostic(status, combined, output, results[-1].manifest if status is Readiness.SUFFICIENT else None)
