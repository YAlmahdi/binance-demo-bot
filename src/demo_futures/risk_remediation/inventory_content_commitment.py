"""M6 v1: bounded content commitment to captured synthetic M5 declarations.

Wire: DOMAIN + frame; frame = tag || u64be(payload length) || payload.
N: empty; B: 00/01; I: sign byte + shortest big-endian magnitude (zero=00);
D: sign + framed I(exponent) + u64 digit count + coefficient digit bytes;
S: Unicode code points, u32be each (surrogates preserved, no normalization);
E: framed S(enum schema ID) + framed S(value); T: u64 count + frames;
R: framed S(record ID) + u64 count + (u16 field ID + frame)*.
IDs below and field numbers (one-based declaration order) are frozen for v1.
Distinct tags, lengths, counts and IDs make parsing unique. No native endianness,
rounding, string conversion, repr or implicit coercion participates in encoding.

Only reviewed, acyclic raw schemas are accepted. Capture checks exact types and
all fields before M5; no derived diagnostic is a raw input. Python recursion is
bounded by that finite schema graph, not by arbitrary input nesting. Caller
budgets meter expanded occurrences (including repeated references), depth, text,
digits, integer/exponent bits and exact framed bytes before serialization. Fixed
schema-ID strings count toward text/byte budgets too. M5 child budgets remain
independently enforced. Capture/plan use O(nodes+digits), output O(bytes); sorting
uses O(n log n). Children repeat their existing bounded walks. Already allocated
inputs, Decimal.as_tuple's temporary allocation, large caller limits and Python
runtime memory are not OS guarantees. No universal production cap is implied.

Owned records are constructed only from checked immutable children. Observable
field replacement during capture is rejected, but hostile concurrent mutation or
monkeypatching in the same interpreter cannot be made atomic/authenticated here.
Validation and hashing use the SAME owned capture. Wire normalization happens
only after FULL M5 sufficiency, never repairs invalid ordering. There is no I/O,
clock, execution integration, replay state or admission authority. SHA-256 is a
content commitment under collision/preimage assumptions, not authenticity,
completeness, reserve adequacy, financial safety or external ownership evidence.
"""
from dataclasses import dataclass, field, replace
from decimal import Decimal
from hashlib import sha256
from sys import maxsize

from ..risk import PositionPlan
from ..research_v2.contracts import EvidenceIdentity, Readiness
from ..research_v2.funding_contracts import CoverageState, FundingClaim, ScheduleEvidence, SettlementObservation
from .funding_budget import FundingStressScenario, SyntheticFundingStressEnvelope
from .plan_budget_contract import PlanBudgetBinding
from . import budget_inventory_contract as m3
from . import snapshot_lifecycle_contract as m4
from .inventory_lifecycle_binding import (BindingDeclaration, BindingResources,
    RevisionAssociation, BindingDiagnostic, assess_binding, _validate_diagnostic)

SCHEMA = "M6_BINDING_CONTENT_V1"
ALGORITHM = "SHA256"
DOMAIN = b"FUTURES_AI_LAB\0M6\0BINDING_CONTENT\0V1\0SHA256\0"
U64_MAX = (1 << 64) - 1


@dataclass(frozen=True, slots=True)
class _Sequence:
    item: object


def _fields(names, kind):
    return tuple((name, kind) for name in names.split())


_PROOF = (EvidenceIdentity, type(None))
_RECORDS = {
    EvidenceIdentity: ("V1.EvidenceIdentity", _fields("identity source_id revision assertion basis", str)),
    PositionPlan: ("V1.PositionPlan", _fields("quantity entry_price stop_price target_price budget planned_loss margin", Decimal)),
    SettlementObservation: ("V1.SettlementObservation", (("timestamp", int), ("rate", Decimal),
        ("mark_price", (Decimal, type(None))), ("timing_evidence", _PROOF), ("mark_evidence", _PROOF))),
    ScheduleEvidence: ("V1.ScheduleEvidence", (("symbol", str), ("start", int), ("end", int),
        ("identity", _PROOF), ("expected_settlements", _Sequence(int)), ("complete", bool))),
    FundingClaim: ("V1.FundingClaim", (("symbol", str), ("start", int), ("end", int), ("source_id", str),
        ("revision", str), ("state", CoverageState), ("observations", _Sequence(SettlementObservation)),
        ("schedule", (ScheduleEvidence, type(None))), ("evidence", str))),
    FundingStressScenario: ("V1.FundingStressScenario", (("scenario_id", str), ("available_at", int), ("claim", FundingClaim))),
    SyntheticFundingStressEnvelope: ("V1.SyntheticFundingStressEnvelope", _fields("symbol interval side", str)
        + _fields("decision_time as_of available_at expires_at holding_start holding_end closure_end", int)
        + _fields("source_id version", str) + _fields("entry_price entry_notional", Decimal)
        + (("evidence_identity", _PROOF), ("scenarios", _Sequence(FundingStressScenario)), ("evidence", str))),
    PlanBudgetBinding: ("V1.PlanBudgetBinding", _fields("symbol interval side source_id version", str)
        + _fields("decision_time as_of holding_start holding_end closure_end", int)
        + _fields("quantity entry_price entry_notional nonfunding_loss embedded_reserve", Decimal) + (("evidence_identity", _PROOF),)),
    m3.ResourceBudget: ("V1.M3.ResourceBudget", _fields("max_positions max_scenarios max_funding_items max_decimal_digits max_text_chars max_integer_bits", int)),
    m3.InventoryInput: ("V1.M3.InventoryInput", _fields("position_id owner_id source_id version snapshot_id", str)
        + (("value", (PositionPlan, SyntheticFundingStressEnvelope, PlanBudgetBinding)),)),
    m3.CompletenessAssertion: ("V1.M3.CompletenessAssertion", _fields("owner_id source_id version snapshot_id", str)
        + (("snapshot_time", int), ("complete", bool), ("identity", _PROOF))),
    m3.JointScenarioAssertion: ("V1.M3.JointScenarioAssertion", _fields("source_id version snapshot_id", str)
        + (("kind", m3.JointKind), ("description", str), ("identity", _PROOF))),
    m3.InventoryDeclaration: ("V1.M3.InventoryDeclaration", _fields("owner_id source_id version snapshot_id", str)
        + _fields("snapshot_time evaluation_time available_at expires_at", int)
        + (("required_position_ids", _Sequence(str)), ("plans", _Sequence(m3.InventoryInput)),
            ("envelopes", _Sequence(m3.InventoryInput)), ("bindings", _Sequence(m3.InventoryInput)),
            ("completeness", m3.Completeness), ("completeness_assertion", (m3.CompletenessAssertion, type(None))),
            ("joint_assertion", (m3.JointScenarioAssertion, type(None))), ("resources", m3.ResourceBudget))),
    m4.SnapshotRef: ("V1.M4.SnapshotRef", _fields("owner_id source_id version snapshot_id", str) + (("revision", int),)),
    m4.SnapshotDeclaration: ("V1.M4.SnapshotDeclaration", (("ref", m4.SnapshotRef),)
        + _fields("valid_from expires_at observed_at available_at", int) + (("identity", _PROOF),)),
    m4.LifecycleEvent: ("V1.M4.LifecycleEvent", (("event_id", str), ("ref", m4.SnapshotRef), ("kind", m4.EventKind))
        + _fields("issued_at available_at effective_at", int) + (("replacement", (m4.SnapshotRef, type(None))), ("identity", _PROOF))),
    m4.LifecycleEvidence: ("V1.M4.LifecycleEvidence", (("ref", m4.SnapshotRef), ("completeness", m4.Completeness))
        + _fields("observed_at available_at expires_at", int) + (("event_ids", _Sequence(str)), ("identity", _PROOF))),
    m4.LifecycleResources: ("V1.M4.LifecycleResources", _fields("max_snapshots max_events max_references max_text_chars max_integer_bits", int)),
    m4.LifecycleDeclaration: ("V1.M4.LifecycleDeclaration", _fields("owner_id source_id version", str)
        + (("evaluation_time", int), ("snapshots", _Sequence(m4.SnapshotDeclaration)), ("events", _Sequence(m4.LifecycleEvent)),
            ("evidence", _Sequence(m4.LifecycleEvidence)), ("resources", m4.LifecycleResources))),
    RevisionAssociation: ("V1.M5.RevisionAssociation", _fields("owner_id source_id version snapshot_id", str)
        + _fields("revision snapshot_time evaluation_time", int) + (("identity", _PROOF), ("provenance", _PROOF))),
    BindingResources: ("V1.M5.BindingResources", (("inventory_ceiling", m3.ResourceBudget), ("lifecycle_ceiling", m4.LifecycleResources))
        + _fields("max_text_chars max_integer_bits", int)),
    BindingDeclaration: ("V1.M5.BindingDeclaration", (("inventory", m3.InventoryDeclaration), ("lifecycle", m4.LifecycleDeclaration),
        ("association", (RevisionAssociation, type(None))), ("resources", BindingResources))),
}
_ENUMS = {
    CoverageState: ("V1.CoverageState", ("KNOWN_EVENTS", "KNOWN_NO_SETTLEMENT", "UNKNOWN")),
    m3.Completeness: ("V1.M3.Completeness", ("COMPLETE", "INCOMPLETE", "UNKNOWN")),
    m3.JointKind: ("V1.M3.JointKind", ("NO_COMBINED_MODEL", "INDEPENDENCE_ASSERTION", "JOINT_MODEL_ASSERTION")),
    m4.Completeness: ("V1.M4.Completeness", ("COMPLETE", "INCOMPLETE", "UNKNOWN")),
    m4.EventKind: ("V1.M4.EventKind", ("REVOKE", "SUPERSEDE")),
}


@dataclass(frozen=True, slots=True)
class EncodingResources:
    max_nodes: int
    max_depth: int
    max_string_codepoints: int
    max_string_bytes: int
    max_decimal_digits: int
    max_exponent_bits: int
    max_integer_bits: int
    max_canonical_bytes: int


class _Rejected(ValueError):
    pass


def _reject(reason="INVALID_SCHEMA"):
    raise _Rejected(reason)


def _shape(obj, names):
    """Reject missing/extra fields without invoking foreign key comparisons."""
    kind = type(obj)
    if tuple(kind.__dataclass_fields__) != names:
        _reject()
    if hasattr(obj, "__dict__"):
        keys = tuple(object.__getattribute__(obj, "__dict__"))
        if any(type(k) is not str for k in keys) or set(keys) != set(names):
            _reject()
    return tuple(object.__getattribute__(obj, n) for n in names)


class _Meter:
    def __init__(self, limits, prefix):
        if type(limits) is not EncodingResources:
            _reject()
        names = tuple(EncodingResources.__dataclass_fields__)
        values = _shape(limits, names)
        if any(type(v) is not int or v < 0 or v > U64_MAX for v in values):
            _reject()
        self.limits = EncodingResources(*values)
        self.nodes = self.chars = self.string_bytes = self.digits = 0
        self.bytes = 0
        self.observed = []
        self.charge(prefix)

    def charge(self, size):
        self.bytes += size
        if self.bytes > self.limits.max_canonical_bytes or self.bytes > min(U64_MAX, maxsize):
            _reject("RESOURCE_BUDGET_EXCEEDED")

    def node(self, depth):
        self.nodes += 1
        if self.nodes > self.limits.max_nodes or depth > self.limits.max_depth:
            _reject("RESOURCE_BUDGET_EXCEEDED")
        self.charge(9)

    def string(self, value):
        self.chars += len(value)
        self.string_bytes += len(value) * 4
        if (self.chars > self.limits.max_string_codepoints
                or self.string_bytes > self.limits.max_string_bytes):
            _reject("RESOURCE_BUDGET_EXCEEDED")
        self.charge(len(value) * 4)

    def integer(self, value, maximum):
        if value.bit_length() > maximum:
            _reject("RESOURCE_BUDGET_EXCEEDED")
        self.charge(1 + (value.bit_length() + 7) // 8)


@dataclass(frozen=True, slots=True)
class _Node:
    tag: bytes
    value: object
    children: tuple
    size: int
    metadata: object = None


def _raw_fields(value, kind):
    if type(value) is not kind:
        _reject()
    names = tuple(n for n, _ in _RECORDS[kind][1])
    return dict(zip(names, _shape(value, names)))


def _child_preflight(payload):
    """Constant-sized budget/configuration and shallow collection gates first.

    Deep accounting remains bounded by M6 capture limits, then by unchanged
    M3/M4/M5 preflights. These gates never compare unchecked foreign objects.
    """
    root = _raw_fields(payload, BindingDeclaration)
    inventory = _raw_fields(root["inventory"], m3.InventoryDeclaration)
    lifecycle = _raw_fields(root["lifecycle"], m4.LifecycleDeclaration)
    binding = _raw_fields(root["resources"], BindingResources)
    for name in ("max_text_chars", "max_integer_bits"):
        value = binding[name]
        if type(value) is not int or value < 0:
            _reject()
    budgets = []
    for child, ceiling, kind in ((inventory["resources"], binding["inventory_ceiling"], m3.ResourceBudget),
            (lifecycle["resources"], binding["lifecycle_ceiling"], m4.LifecycleResources)):
        actual, maximum = _raw_fields(child, kind), _raw_fields(ceiling, kind)
        for name in actual:
            v, limit = actual[name], maximum[name]
            if type(v) is not int or type(limit) is not int or v < 0 or limit < 0:
                _reject()
            if v > limit:
                _reject("RESOURCE_BUDGET_EXCEEDED")
        budgets.append(actual)
    for obj, names, maximum in (
            (inventory, ("required_position_ids", "plans", "envelopes", "bindings"), budgets[0]["max_positions"]),
            (lifecycle, ("snapshots", "evidence"), budgets[1]["max_snapshots"]),
            (lifecycle, ("events",), budgets[1]["max_events"])):
        for name in names:
            if type(obj[name]) is not tuple:
                _reject()
            if len(obj[name]) > maximum:
                _reject("RESOURCE_BUDGET_EXCEEDED")


def _capture(value, expected, meter, depth=0):
    """The expected schema, not caller data, bounds recursive call depth."""
    kind = type(value)
    if type(expected) is _Sequence:
        if kind is not tuple:
            _reject()
    elif not any(kind is allowed for allowed in (expected if type(expected) is tuple else (expected,))):
        _reject()
    meter.node(depth)
    start = meter.bytes - 9
    children, metadata = (), None
    if kind is type(None):
        tag, owned = b"N", None
    elif kind is bool:
        tag, owned = b"B", value
        meter.charge(1)
    elif kind is int:
        tag, owned = b"I", value
        meter.integer(value, meter.limits.max_integer_bits)
    elif kind is str:
        tag, owned = b"S", value
        meter.string(value)
    elif kind is Decimal:
        if not value.is_finite():
            _reject("INVALID_NUMBER")
        # as_tuple is exact/context-free but its temporary allocation precedes
        # the coefficient bound; the same documented limitation exists in M3.
        parts = value.as_tuple()
        meter.digits += len(parts.digits)
        if meter.digits > meter.limits.max_decimal_digits:
            _reject("RESOURCE_BUDGET_EXCEEDED")
        if parts.exponent.bit_length() > meter.limits.max_exponent_bits:
            _reject("RESOURCE_BUDGET_EXCEEDED")
        meter.charge(9 + len(parts.digits))  # sign and digit count
        exponent = _capture(parts.exponent, int, meter, depth + 1)
        tag, owned, children, metadata = b"D", value, (exponent,), parts
    elif kind in _ENUMS:
        enum_id, allowed = _ENUMS[kind]
        literal = value.value
        name = value.name
        if (type(literal) is not str or type(name) is not str or literal not in allowed
                or literal != str.__str__(value) or name != literal
                or not any(value is member for member in kind)):
            _reject()
        children = (_capture(enum_id, str, meter, depth + 1), _capture(literal, str, meter, depth + 1))
        meter.observed.append((value, ("_value_", "_name_"), (literal, name)))
        tag, owned = b"E", value
    elif kind is tuple and type(expected) is _Sequence:
        count = len(value)
        if count > meter.limits.max_nodes - meter.nodes or count > U64_MAX:
            _reject("RESOURCE_BUDGET_EXCEEDED")
        meter.charge(8)
        children = tuple(_capture(v, expected.item, meter, depth + 1) for v in value)
        tag, owned = b"T", tuple(c.value for c in children)
    elif kind in _RECORDS:
        record_id, definitions = _RECORDS[kind]
        names = tuple(n for n, _ in definitions)
        originals = _shape(value, names)
        if kind is SyntheticFundingStressEnvelope:
            marker = originals[-1]
            if type(marker) is not str or marker != "SYNTHETIC_ONLY":
                _reject()
        meter.charge(8 + 2 * len(names))
        id_node = _capture(record_id, str, meter, depth + 1)
        fields = tuple(_capture(v, spec, meter, depth + 1) for v, (_, spec) in zip(originals, definitions))
        owned = object.__new__(kind)
        for name, child in zip(names, fields):
            object.__setattr__(owned, name, child.value)
        meter.observed.append((value, names, originals))
        tag, children, metadata = b"R", (id_node,) + fields, names
    else:
        _reject()
    return _Node(tag, owned, children, meter.bytes - start, metadata)


def _ref_key(node):
    r = node.value.ref
    return (r.owner_id, r.source_id, r.version, r.snapshot_id, r.revision)


def _ordered_children(node):
    if node.tag != b"R":
        return node.children
    result = list(node.children)
    for index, name in enumerate(node.metadata, 1):
        child = result[index]
        key = None
        kind = type(node.value)
        if kind is m3.InventoryDeclaration:
            if name == "required_position_ids":
                key = lambda n: n.value
            elif name in ("plans", "envelopes", "bindings"):
                key = lambda n: n.value.position_id
        elif kind is SyntheticFundingStressEnvelope and name == "scenarios":
            key = lambda n: n.value.scenario_id
        elif kind is m4.LifecycleDeclaration and name in ("snapshots", "evidence"):
            key = _ref_key
        if key is not None:
            result[index] = _Node(child.tag, child.value, tuple(sorted(child.children, key=key)), child.size, child.metadata)
    return tuple(result)


def _u64(value):
    return value.to_bytes(8, "big")


def _serialize(root, prefix=b"", *, normalize=False):
    """Exact-sized buffer; plan lengths have already passed caller limits."""
    out = bytearray(len(prefix) + root.size)
    cursor = 0

    def put(data):
        nonlocal cursor
        end = cursor + len(data)
        if end > len(out):
            raise ValueError("Encoding size invariant")
        out[cursor:end] = data
        cursor = end

    put(prefix)
    stack = [root]
    while stack:
        item = stack.pop()
        if type(item) is bytes:
            put(item)
            continue
        node = item
        tag, value = node.tag, node.value
        put(tag + _u64(node.size - 9))
        if tag == b"B":
            put(b"\x01" if value else b"\x00")
        elif tag == b"I":
            put(bytes((int(value < 0),)) + abs(value).to_bytes((value.bit_length() + 7) // 8, "big"))
        elif tag == b"S":
            for character in value:
                put(ord(character).to_bytes(4, "big"))
        elif tag == b"D":
            parts = node.metadata
            put(bytes((parts.sign,)))
            stack.extend((bytes(parts.digits), _u64(len(parts.digits)), node.children[0]))
        elif tag == b"T":
            put(_u64(len(node.children)))
            stack.extend(reversed(node.children))
        elif tag == b"E":
            stack.extend(reversed(node.children))
        elif tag == b"R":
            children = _ordered_children(node) if normalize else node.children
            for index in range(len(children) - 1, 0, -1):
                stack.extend((children[index], index.to_bytes(2, "big")))
            stack.extend((_u64(len(children) - 1), children[0]))
    if cursor != len(out):
        raise ValueError("Encoding size invariant")
    return bytes(out)


_ASSOCIATION_FIELDS = ("owner_id", "source_id", "version", "snapshot_id", "revision", "snapshot_time", "evaluation_time")


@dataclass(frozen=True, slots=True)
class CommitmentManifest:
    schema: str
    algorithm: str
    owner_id: str
    source_id: str
    version: str
    snapshot_id: str
    revision: int
    snapshot_time: int
    evaluation_time: int
    byte_length: int
    digest: str

    def __post_init__(self):
        text = (self.schema, self.algorithm, self.owner_id, self.source_id, self.version, self.snapshot_id, self.digest)
        numbers = (self.revision, self.snapshot_time, self.evaluation_time, self.byte_length)
        if (any(type(v) is not str for v in text) or any(type(v) is not int or v < 0 for v in numbers)
                or self.schema != SCHEMA or self.algorithm != ALGORITHM or self.byte_length <= len(DOMAIN)
                or self.byte_length > U64_MAX or len(self.digest) != 64
                or any(c not in "0123456789abcdef" for c in self.digest)):
            raise ValueError("Exact versioned content manifest required")

    def __bool__(self):
        raise TypeError("Content identity never grants authority")


@dataclass(frozen=True, slots=True)
class CommitmentDiagnostic:
    status: Readiness
    reason: str
    binding: BindingDiagnostic | None = None
    association: RevisionAssociation | None = None
    manifest: CommitmentManifest | None = None
    authority: str = field(default="SYNTHETIC_DIAGNOSTIC_ONLY", init=False)
    evidence: str = field(default="SYNTHETIC_ONLY", init=False)
    aggregate_state: str = field(default="BLOCKED", init=False)
    risk_clearance: str = field(default="NOT CLEARED", init=False)

    def __post_init__(self):
        if type(self.status) is not Readiness or type(self.reason) is not str:
            raise ValueError("Exact diagnostic fields required")
        if self.binding is not None:
            _validate_diagnostic(self.binding, BindingDiagnostic)
        if self.status is Readiness.SUFFICIENT:
            if (self.reason != "CONTENT_COMMITTED" or self.binding is None
                    or self.binding.status is not Readiness.SUFFICIENT
                    or type(self.association) is not RevisionAssociation or type(self.manifest) is not CommitmentManifest):
                raise ValueError("Success requires recomputed binding and manifest")
            replace(self.manifest)
            replace(self.association)
            for name in _ASSOCIATION_FIELDS:
                left, right = getattr(self.association, name), getattr(self.manifest, name)
                if type(left) is not type(right) or left != right:
                    raise ValueError("Manifest must match captured association")
        else:
            if self.manifest is not None or self.association is not None:
                raise ValueError("Failed commitment contains no manifest")
            if self.reason == "BINDING_REJECTED":
                if self.binding is None or self.binding.status is not self.status or self.status is Readiness.SUFFICIENT:
                    raise ValueError("Retain full failed M5 result")
            elif (self.reason not in ("INVALID_SCHEMA", "INVALID_NUMBER", "RESOURCE_BUDGET_EXCEEDED", "UNSUPPORTED_VERSION", "CAPTURE_CHANGED")
                    or self.status is not Readiness.INVALID or self.binding is not None):
                raise ValueError("Exact preflight rejection required")

    def __bool__(self):
        raise TypeError("Synthetic commitment never authorizes admission")


def commit_content(payload, resources, *, schema=SCHEMA, algorithm=ALGORITHM):
    """Return a diagnostic SHA-256 commitment, only after captured M5 sufficiency.

    No caller diagnostic is accepted. Public result dataclasses enforce structural
    consistency but are not signatures or unforgeable capability objects.
    """
    try:
        if type(schema) is not str or type(algorithm) is not str:
            _reject()
        if schema != SCHEMA or algorithm != ALGORITHM:
            _reject("UNSUPPORTED_VERSION")
        meter = _Meter(resources, len(DOMAIN))
        _child_preflight(payload)
        root = _capture(payload, BindingDeclaration, meter)
        for original, names, references in meter.observed:
            if type(original) in _RECORDS:
                current = _shape(original, names)
            else:
                current = tuple(object.__getattribute__(original, n) for n in names)
            if any(a is not b for a, b in zip(current, references)):
                _reject("CAPTURE_CHANGED")
        result = assess_binding(root.value)
        # Exact Enum members must retain singleton identity for M1-M5's `is`
        # semantics. They are shared trusted constants, unlike copied records.
        # Recheck their observable metadata across the assessment boundary.
        for original, names, references in meter.observed:
            if type(original) in _ENUMS and any(object.__getattribute__(original, n) is not reference
                    for n, reference in zip(names, references)):
                _reject("CAPTURE_CHANGED")
        if result.status is not Readiness.SUFFICIENT:
            return CommitmentDiagnostic(result.status, "BINDING_REJECTED", result)
        canonical = _serialize(root, DOMAIN, normalize=True)
        if len(canonical) != meter.bytes:
            raise ValueError("Encoding meter invariant")
        association = root.value.association
        manifest = CommitmentManifest(SCHEMA, ALGORITHM, *(getattr(association, n) for n in _ASSOCIATION_FIELDS),
            len(canonical), sha256(canonical).hexdigest())
        return CommitmentDiagnostic(Readiness.SUFFICIENT, "CONTENT_COMMITTED", result, association, manifest)
    except _Rejected as error:
        return CommitmentDiagnostic(Readiness.INVALID, error.args[0])
    except (AttributeError, ValueError):
        return CommitmentDiagnostic(Readiness.INVALID, "INVALID_SCHEMA")
