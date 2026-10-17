"""Independent v1 wire oracle and adversarial invented-2010 M6 fixtures only."""
from dataclasses import replace
from decimal import Decimal as D, DefaultContext, getcontext, localcontext
from hashlib import sha256
import unittest
from unittest.mock import patch

from demo_futures.risk_remediation import inventory_content_commitment as m6
from demo_futures.risk_remediation import budget_inventory_contract as m3
from demo_futures.risk_remediation import snapshot_lifecycle_contract as m4
from demo_futures.research_v2.contracts import EvidenceIdentity, Readiness
from demo_futures.research_v2.funding_contracts import FundingClaim, CoverageState
from test_risk_inventory_lifecycle_binding import binding, with_lifecycle
from test_risk_snapshot_lifecycle_contract import ledger, event, with_events
from test_risk_funding_budget import BASE


# Independent, manually enumerated schema oracle. No production registry access.
# Keys are module tail + class name to distinguish M3/M4 Completeness.
RECORD_SPEC = """
contracts.EvidenceIdentity|V1.EvidenceIdentity|identity source_id revision assertion basis
risk.PositionPlan|V1.PositionPlan|quantity entry_price stop_price target_price budget planned_loss margin
funding_contracts.SettlementObservation|V1.SettlementObservation|timestamp rate mark_price timing_evidence mark_evidence
funding_contracts.ScheduleEvidence|V1.ScheduleEvidence|symbol start end identity expected_settlements complete
funding_contracts.FundingClaim|V1.FundingClaim|symbol start end source_id revision state observations schedule evidence
funding_budget.FundingStressScenario|V1.FundingStressScenario|scenario_id available_at claim
funding_budget.SyntheticFundingStressEnvelope|V1.SyntheticFundingStressEnvelope|symbol interval side decision_time as_of available_at expires_at holding_start holding_end closure_end source_id version entry_price entry_notional evidence_identity scenarios evidence
plan_budget_contract.PlanBudgetBinding|V1.PlanBudgetBinding|symbol interval side source_id version decision_time as_of holding_start holding_end closure_end quantity entry_price entry_notional nonfunding_loss embedded_reserve evidence_identity
budget_inventory_contract.ResourceBudget|V1.M3.ResourceBudget|max_positions max_scenarios max_funding_items max_decimal_digits max_text_chars max_integer_bits
budget_inventory_contract.InventoryInput|V1.M3.InventoryInput|position_id owner_id source_id version snapshot_id value
budget_inventory_contract.CompletenessAssertion|V1.M3.CompletenessAssertion|owner_id source_id version snapshot_id snapshot_time complete identity
budget_inventory_contract.JointScenarioAssertion|V1.M3.JointScenarioAssertion|source_id version snapshot_id kind description identity
budget_inventory_contract.InventoryDeclaration|V1.M3.InventoryDeclaration|owner_id source_id version snapshot_id snapshot_time evaluation_time available_at expires_at required_position_ids plans envelopes bindings completeness completeness_assertion joint_assertion resources
snapshot_lifecycle_contract.SnapshotRef|V1.M4.SnapshotRef|owner_id source_id version snapshot_id revision
snapshot_lifecycle_contract.SnapshotDeclaration|V1.M4.SnapshotDeclaration|ref valid_from expires_at observed_at available_at identity
snapshot_lifecycle_contract.LifecycleEvent|V1.M4.LifecycleEvent|event_id ref kind issued_at available_at effective_at replacement identity
snapshot_lifecycle_contract.LifecycleEvidence|V1.M4.LifecycleEvidence|ref completeness observed_at available_at expires_at event_ids identity
snapshot_lifecycle_contract.LifecycleResources|V1.M4.LifecycleResources|max_snapshots max_events max_references max_text_chars max_integer_bits
snapshot_lifecycle_contract.LifecycleDeclaration|V1.M4.LifecycleDeclaration|owner_id source_id version evaluation_time snapshots events evidence resources
inventory_lifecycle_binding.RevisionAssociation|V1.M5.RevisionAssociation|owner_id source_id version snapshot_id revision snapshot_time evaluation_time identity provenance
inventory_lifecycle_binding.BindingResources|V1.M5.BindingResources|inventory_ceiling lifecycle_ceiling max_text_chars max_integer_bits
inventory_lifecycle_binding.BindingDeclaration|V1.M5.BindingDeclaration|inventory lifecycle association resources
"""
REFERENCE_RECORDS = {line.split("|")[0]: (line.split("|")[1], line.split("|")[2].split())
    for line in RECORD_SPEC.strip().splitlines()}
REFERENCE_ENUMS = {
    "funding_contracts.CoverageState": "V1.CoverageState",
    "budget_inventory_contract.Completeness": "V1.M3.Completeness",
    "budget_inventory_contract.JointKind": "V1.M3.JointKind",
    "snapshot_lifecycle_contract.Completeness": "V1.M4.Completeness",
    "snapshot_lifecycle_contract.EventKind": "V1.M4.EventKind",
}
REFERENCE_DOMAIN = bytes.fromhex("465554555245535f41495f4c4142004d360042494e44494e475f434f4e54454e540056310053484132353600")


def type_key(value):
    return type(value).__module__.split(".")[-1] + "." + type(value).__name__


def reference(value, normalize=False):
    """Simple recursive TEST oracle: separate grammar, field table and ordering."""
    kind = type(value)
    if value is None:
        tag, body = b"N", b""
    elif kind is bool:
        tag, body = b"B", bytes([1 if value else 0])
    elif kind is int:
        magnitude = abs(value)
        digits = []
        while magnitude:
            digits.insert(0, magnitude % 256)
            magnitude //= 256
        tag, body = b"I", bytes([1 if value < 0 else 0] + digits)
    elif kind is str:
        tag, body = b"S", b"".join(bytes([(ord(c) >> 24) & 255, (ord(c) >> 16) & 255,
            (ord(c) >> 8) & 255, ord(c) & 255]) for c in value)
    elif kind is D:
        sign, digits, exponent = value.as_tuple()
        tag = b"D"
        body = bytes([sign]) + reference(exponent) + len(digits).to_bytes(8, "big") + bytes(digits)
    elif kind is tuple:
        tag, body = b"T", len(value).to_bytes(8, "big") + b"".join(reference(v, normalize) for v in value)
    elif type_key(value) in REFERENCE_ENUMS:
        tag, body = b"E", reference(REFERENCE_ENUMS[type_key(value)]) + reference(value.value)
    else:
        schema, names = REFERENCE_RECORDS[type_key(value)]
        rows = []
        for field_id, name in enumerate(names, 1):
            child = getattr(value, name)
            if normalize:
                key = type_key(value)
                if key == "budget_inventory_contract.InventoryDeclaration":
                    if name == "required_position_ids":
                        child = tuple(sorted(child))
                    elif name in ("plans", "envelopes", "bindings"):
                        child = tuple(sorted(child, key=lambda r: r.position_id))
                elif key == "funding_budget.SyntheticFundingStressEnvelope" and name == "scenarios":
                    child = tuple(sorted(child, key=lambda r: r.scenario_id))
                elif key == "snapshot_lifecycle_contract.LifecycleDeclaration" and name in ("snapshots", "evidence"):
                    child = tuple(sorted(child, key=lambda r: (r.ref.owner_id, r.ref.source_id,
                        r.ref.version, r.ref.snapshot_id, r.ref.revision)))
            rows.append(field_id.to_bytes(2, "big") + reference(child, normalize))
        tag, body = b"R", reference(schema) + len(names).to_bytes(8, "big") + b"".join(rows)
    return tag + len(body).to_bytes(8, "big") + body


# Fixed byte strings authored directly from the grammar, independent of encoder.
PRIMITIVES = (
    (None, "4e0000000000000000"),
    (False, "42000000000000000100"),
    (True, "42000000000000000101"),
    (0, "49000000000000000100"),
    (1, "4900000000000000020001"),
    (-1, "4900000000000000020101"),
    (255, "49000000000000000200ff"),
    (256, "490000000000000003000100"),
    (-256, "490000000000000003010100"),
    ("", "530000000000000000"),
    ("A\ud800\U0001f600", "53000000000000000c000000410000d8000001f600"),
    (D("-0.00"), "440000000000000015014900000000000000020102000000000000000100"),
    (D("1.20"), "4400000000000000170049000000000000000201020000000000000003010200"),
    ((), "5400000000000000080000000000000000"),
    ((None, ()), "54000000000000002200000000000000024e00000000000000005400000000000000080000000000000000"),
)
# Full expected values are filled from the independent reference-only calculation,
# then frozen as literals; no production call computes expected vector identities.
FULL_GOLDENS = {
    0: (7639, "75fa847ed3713d7890885aa20ddcbff4b5546777e1989d9015299aab624aad44"),
    1: (13894, "6ab4ae23a5c6d8df0f697001aa3c5513de181659302851abd88917be374b625a"),
    2: (20143, "12380f5a3eac61a42bcd10e9a0c5a39a6bcc4f434042f1908f0082c55fca30ad"),
}


def limits(**changes):
    return replace(m6.EncodingResources(100000, 64, 1000000, 4000000, 100000, 128, 128, 10000000), **changes)


def plan(value, spec=None, resource=None, prefix=0):
    meter = m6._Meter(resource if resource is not None else limits(), prefix)
    if spec is None:
        spec = type(value)
    return m6._capture(value, spec, meter), meter


def wire(value, spec=None, resource=None, normalize=False):
    node, _ = plan(value, spec, resource)
    return m6._serialize(node, normalize=normalize)


def records(value):
    if type(value) is tuple:
        for child in value:
            yield from records(child)
    elif type_key(value) in REFERENCE_RECORDS:
        yield value
        for name in REFERENCE_RECORDS[type_key(value)][1]:
            yield from records(getattr(value, name))


class GoldenTests(unittest.TestCase):
    def test_primitive_exact_bytes_and_digests(self):
        for value, hexadecimal in PRIMITIVES:
            spec = m6._Sequence((type(None), tuple)) if type(value) is tuple else type(value)
            # Only the nested tuple vector needs an explicit nested schema.
            if value == (None, ()):
                inner, _ = plan((), m6._Sequence(int))
                none, _ = plan(None)
                node = m6._Node(b"T", value, (none, inner), 9 + 8 + none.size + inner.size)
                actual = m6._serialize(node)
            else:
                actual = wire(value, m6._Sequence(int) if type(value) is tuple else spec)
            with self.subTest(hex=hexadecimal):
                expected = bytes.fromhex(hexadecimal)
                self.assertEqual(reference(value), expected)
                self.assertEqual(actual, expected)
                self.assertEqual(sha256(actual).hexdigest(), sha256(expected).hexdigest())

    def test_every_record_schema_has_independent_exact_bytes(self):
        raw = binding()
        fixture_records = list(records(raw)) + list(records(event(raw.lifecycle)))
        seen = set()
        for record in fixture_records:
            key = type_key(record)
            with self.subTest(schema=key):
                self.assertEqual(wire(record), reference(record))
            seen.add(key)
        self.assertEqual(seen, set(REFERENCE_RECORDS))
        self.assertEqual(len(seen), 22)

    def test_all_enum_values_and_type_domains(self):
        encoded = set()
        for kind in (CoverageState, m3.Completeness, m3.JointKind, m4.Completeness, m4.EventKind):
            for member in kind:
                actual = wire(member)
                self.assertEqual(actual, reference(member))
                self.assertNotEqual(actual, wire(member.value))
                self.assertNotIn(actual, encoded)
                encoded.add(actual)

    def test_full_payload_bytes_fixed_sizes_and_sha256(self):
        self.assertEqual(m6.DOMAIN, REFERENCE_DOMAIN)
        self.assertEqual(set(FULL_GOLDENS), {0, 1, 2})
        for count, (size, digest) in FULL_GOLDENS.items():
            raw = binding(count)
            expected = REFERENCE_DOMAIN + reference(raw, normalize=True)
            node, meter = plan(raw, prefix=len(REFERENCE_DOMAIN))
            actual = m6._serialize(node, m6.DOMAIN, normalize=True)
            out = m6.commit_content(raw, limits())
            self.assertEqual(actual, expected)
            self.assertEqual((len(expected), sha256(expected).hexdigest()), (size, digest))
            self.assertEqual((out.manifest.byte_length, out.manifest.digest), (size, digest))
            self.assertEqual(meter.bytes, size)

    def test_integer_and_decimal_representation_boundaries(self):
        for v in (-(1 << 127), (1 << 128) - 1, 0):
            self.assertEqual(wire(v), reference(v))
        for text in ("0", "-0", "0E+99", "-0E-99", "1.000", "1E+127", "1E-127"):
            value = D(text)
            self.assertEqual(wire(value), reference(value))
        self.assertNotEqual(wire(D("0")), wire(D("-0")))
        self.assertNotEqual(wire(D("1.0")), wire(D("1.00")))
        self.assertNotEqual(wire("\u00e9"), wire("e\u0301"))


class CaptureTests(unittest.TestCase):
    def reject(self, raw, reason=None, resource=None, **kwargs):
        out = m6.commit_content(raw, resource if resource is not None else limits(), **kwargs)
        self.assertIsNot(out.status, Readiness.SUFFICIENT)
        self.assertIsNone(out.manifest)
        self.assertIsNone(out.association)
        if reason is not None:
            self.assertEqual(out.reason, reason)
        return out

    def test_owned_same_capture_recomputed_once(self):
        raw = binding()
        real = m6.assess_binding
        seen = []
        def assess(captured):
            self.assertIsNot(captured, raw)
            originals = list(records(raw))
            for copy in records(captured):
                self.assertFalse(any(copy is old for old in originals))
            seen.append(captured)
            return real(captured)
        with patch.object(m6, "assess_binding", side_effect=assess):
            out = m6.commit_content(raw, limits())
        self.assertEqual(len(seen), 1)
        self.assertIs(out.association, seen[0].association)
        self.assertEqual(out.status, Readiness.SUFFICIENT)

    def test_original_mutation_after_capture_does_not_change_owned_hash(self):
        raw = binding()
        expected = m6.commit_content(raw, limits()).manifest.digest
        real = m6.assess_binding
        def mutate(captured):
            object.__setattr__(raw.association, "revision", 99)
            return real(captured)
        with patch.object(m6, "assess_binding", side_effect=mutate):
            self.assertEqual(m6.commit_content(raw, limits()).manifest.digest, expected)

    def test_detectable_field_replacement_during_capture_rejected(self):
        raw = binding()
        original = m6._capture
        changed = False
        def intercept(value, expected, meter, depth=0):
            nonlocal changed
            node = original(value, expected, meter, depth)
            if value is raw.association and not changed:
                object.__setattr__(value, "revision", 99)
                changed = True
            return node
        with patch.object(m6, "_capture", side_effect=intercept):
            self.reject(raw, "CAPTURE_CHANGED")

    def test_foreign_fields_rejected_before_hooks_or_m5(self):
        class Meta(type):
            def __eq__(self, other):
                raise AssertionError("metaclass comparison")
            def __hash__(self):
                raise AssertionError("metaclass hash")
        class Hostile(metaclass=Meta):
            def __eq__(self, other):
                raise AssertionError("comparison")
            def __lt__(self, other):
                raise AssertionError("ordering")
            def __str__(self):
                raise AssertionError("conversion")
            def __bool__(self):
                raise AssertionError("truth")
        for raw_record in records(binding()):
            for name in REFERENCE_RECORDS[type_key(raw_record)][1]:
                raw = binding()
                target = next(r for r in records(raw) if type(r) is type(raw_record))
                object.__setattr__(target, name, Hostile())
                with self.subTest(record=type_key(target), field=name), patch.object(m6, "assess_binding", side_effect=AssertionError("early M5")):
                    self.reject(raw, "INVALID_SCHEMA")

    def test_subclasses_missing_extra_and_fixed_marker(self):
        class Extra(EvidenceIdentity):
            pass
        raw = binding()
        object.__setattr__(raw.association, "identity", Extra("a", "b", "c", "d"))
        self.reject(raw, "INVALID_SCHEMA")
        for action in ("missing", "extra", "marker"):
            raw = binding()
            proof = raw.association.identity
            if action == "missing":
                object.__delattr__(proof, "basis")
            elif action == "extra":
                object.__setattr__(proof, "unknown", 1)
            else:
                object.__setattr__(raw.inventory.envelopes[0].value, "evidence", "FORGED")
            self.reject(raw, "INVALID_SCHEMA")

    def test_nonfinite_and_recursive_invalid_values(self):
        for text in ("NaN", "sNaN", "Infinity", "-Infinity"):
            raw = binding()
            object.__setattr__(raw.inventory.plans[0].value, "budget", D(text))
            self.reject(raw, "INVALID_NUMBER")
        raw = binding()
        object.__setattr__(raw.inventory, "plans", (raw.inventory,))
        self.reject(raw, "INVALID_SCHEMA")

    def test_all_material_leaf_mutations_change_bytes(self):
        # Exhaustive raw leaf paths in a complete declaration, before semantic
        # validation. Invalid mutations must not become successful commitments.
        raw = binding()
        baseline = reference(raw)
        count = 0
        def visit(obj, path=()):
            if type(obj) is tuple:
                for i, child in enumerate(obj):
                    yield from visit(child, path + (i,))
            elif type_key(obj) in REFERENCE_RECORDS:
                for name in REFERENCE_RECORDS[type_key(obj)][1]:
                    yield from visit(getattr(obj, name), path + (name,))
            else:
                yield path, obj
        for path, old in visit(raw):
            fresh = binding()
            target = fresh
            for key in path[:-1]:
                target = target[key] if type(key) is int else getattr(target, key)
            if type(old) is str:
                new = old + "x"
            elif type(old) is int:
                new = old + 1
            elif type(old) is bool:
                new = not old
            elif type(old) is D:
                parts = old.as_tuple()
                new = D((parts.sign, parts.digits + (0,), parts.exponent - 1))
            elif type_key(old) in REFERENCE_ENUMS:
                new = next(member for member in type(old) if member is not old)
            elif old is None:
                continue
            else:
                self.fail("Uncovered material leaf")
            if type(path[-1]) is int:
                continue  # tuple scalar changes covered by required-ID tests
            object.__setattr__(target, path[-1], new)
            with self.subTest(path=path):
                expected = reference(fresh)
                self.assertNotEqual(expected, baseline)
                # Fixed markers intentionally reject at shape capture.
                if type(target) is m6.SyntheticFundingStressEnvelope and path[-1] == "evidence":
                    self.reject(fresh, "INVALID_SCHEMA")
                else:
                    self.assertEqual(wire(fresh), expected)
                    self.assertNotEqual(sha256(expected).digest(), sha256(baseline).digest())
            count += 1
        self.assertGreater(count, 200)

    def test_resource_limits_exact_boundaries(self):
        raw = binding()
        _, meter = plan(raw, prefix=len(m6.DOMAIN))
        exact = limits(max_nodes=meter.nodes, max_depth=64, max_string_codepoints=meter.chars,
            max_string_bytes=meter.string_bytes, max_decimal_digits=meter.digits, max_canonical_bytes=meter.bytes)
        self.assertEqual(m6.commit_content(raw, exact).status, Readiness.SUFFICIENT)
        for name in ("max_nodes", "max_string_codepoints", "max_string_bytes", "max_decimal_digits", "max_canonical_bytes"):
            with self.subTest(limit=name), patch.object(m6, "assess_binding", side_effect=AssertionError("early M5")):
                self.reject(raw, "RESOURCE_BUDGET_EXCEEDED", replace(exact, **{name: getattr(exact, name) - 1}))
        for changes in ({"max_depth": 0}, {"max_integer_bits": 1}, {"max_exponent_bits": 0}):
            self.reject(raw, "RESOURCE_BUDGET_EXCEEDED", limits(**changes))
        # Discover exact schema depth by boundary, not an invented global cap.
        sufficient = [n for n in range(20) if m6.commit_content(raw, limits(max_depth=n)).status is Readiness.SUFFICIENT]
        self.assertTrue(sufficient)
        self.reject(raw, "RESOURCE_BUDGET_EXCEEDED", limits(max_depth=min(sufficient) - 1))

    def test_invalid_resource_configuration(self):
        for name in m6.EncodingResources.__dataclass_fields__:
            for bad in (True, -1, 1 << 64, "100"):
                self.reject(binding(), "INVALID_SCHEMA", replace(limits(), **{name: bad}))
        self.reject(binding(), "INVALID_SCHEMA", object())

    def test_existing_child_ceilings_not_overridden(self):
        raw = binding()
        raw = replace(raw, resources=replace(raw.resources, inventory_ceiling=replace(raw.resources.inventory_ceiling, max_scenarios=0)))
        with patch.object(m6, "_capture", side_effect=AssertionError("early capture")):
            self.reject(raw, "RESOURCE_BUDGET_EXCEEDED")

    def test_child_budget_shapes_and_shallow_limits_before_capture(self):
        for name in ("max_positions", "max_scenarios", "max_funding_items", "max_decimal_digits", "max_text_chars", "max_integer_bits"):
            raw = binding()
            object.__setattr__(raw.inventory.resources, name, object())
            with self.subTest(field=name), patch.object(m6, "_capture", side_effect=AssertionError("early capture")):
                self.reject(raw, "INVALID_SCHEMA")
        raw = binding()
        raw = replace(raw, inventory=replace(raw.inventory, required_position_ids=raw.inventory.required_position_ids * 2))
        with patch.object(m6, "_capture", side_effect=AssertionError("early capture")):
            self.reject(raw, "RESOURCE_BUDGET_EXCEEDED")

    def test_enum_value_and_name_tampering_rejected(self):
        member = m3.Completeness.COMPLETE
        old_value, old_name = member._value_, member._name_
        try:
            for name, bad in (("_value_", object()), ("_value_", "INCOMPLETE"), ("_name_", "OTHER")):
                object.__setattr__(member, name, bad)
                self.reject(binding(), "INVALID_SCHEMA")
                object.__setattr__(member, "_value_", old_value)
                object.__setattr__(member, "_name_", old_name)
        finally:
            object.__setattr__(member, "_value_", old_value)
            object.__setattr__(member, "_name_", old_name)

    def test_detectable_shared_enum_mutation_during_assessment_rejected(self):
        member = m3.Completeness.COMPLETE
        original = member._name_
        assess = m6.assess_binding
        def mutate(captured):
            out = assess(captured)
            object.__setattr__(member, "_name_", "TAMPERED")
            return out
        try:
            with patch.object(m6, "assess_binding", side_effect=mutate):
                self.reject(binding(), "CAPTURE_CHANGED")
        finally:
            object.__setattr__(member, "_name_", original)

    def test_versions_and_diagnostic_input_rejected(self):
        for kwargs in ({"schema": "M6_BINDING_CONTENT_V2"}, {"algorithm": "SHA512"}, {"schema": ""}):
            self.reject(binding(), "UNSUPPORTED_VERSION", **kwargs)
        self.reject(binding(), "INVALID_SCHEMA", schema=object())
        self.reject(m6.assess_binding(binding()), "INVALID_SCHEMA")
        self.assertNotEqual(sha256(m6.DOMAIN + reference(binding())).digest(), sha256(b"OTHER" + reference(binding())).digest())

    def test_decimal_context_independence(self):
        raw = binding()
        expected = m6.commit_content(raw, limits())
        saved = DefaultContext.copy()
        try:
            DefaultContext.prec = 1
            for signal in DefaultContext.traps:
                DefaultContext.traps[signal] = True
            with localcontext() as ctx:
                ctx.prec = 1
                for signal in ctx.traps:
                    ctx.traps[signal] = True
                before = ctx.copy()
                self.assertEqual(m6.commit_content(raw, limits()), expected)
                self.assertEqual(dict(ctx.flags), dict(before.flags))
                self.assertEqual(ctx.prec, 1)
        finally:
            DefaultContext.prec = saved.prec
            DefaultContext.traps.update(saved.traps)


class SemanticTests(unittest.TestCase):
    reject = CaptureTests.reject

    def test_unordered_inventory_and_alternatives_normalize(self):
        raw = binding(2)
        expected = m6.commit_content(raw, limits()).manifest
        i = raw.inventory
        envelopes = tuple(replace(row, value=replace(row.value, scenarios=tuple(reversed(row.value.scenarios)))) for row in reversed(i.envelopes))
        shuffled = replace(raw, inventory=replace(i, required_position_ids=tuple(reversed(i.required_position_ids)),
            plans=tuple(reversed(i.plans)), envelopes=envelopes, bindings=tuple(reversed(i.bindings))))
        self.assertEqual(m6.commit_content(shuffled, limits()).manifest, expected)
        self.assertNotEqual(reference(shuffled), reference(raw))

    def test_unordered_lifecycle_snapshots_evidence_normalize(self):
        raw = binding(0)
        other = ledger(2)
        first = raw.lifecycle
        second_ref = replace(other.snapshots[1].ref, snapshot_id="snapshot-b")
        second = replace(other.snapshots[1], ref=second_ref, observed_at=BASE, available_at=BASE)
        evidence = replace(other.evidence[1], ref=second_ref)
        life = replace(first, snapshots=first.snapshots + (second,), evidence=first.evidence + (evidence,), resources=other.resources)
        raw = with_lifecycle(raw, life)
        expected = m6.commit_content(raw, limits())
        self.assertEqual(expected.status, Readiness.SUFFICIENT)
        shuffled = with_lifecycle(raw, replace(life, snapshots=tuple(reversed(life.snapshots)), evidence=tuple(reversed(life.evidence))))
        self.assertEqual(m6.commit_content(shuffled, limits()).manifest, expected.manifest)

    def test_duplicate_positions_scenarios_and_evidence_rejected(self):
        raw = binding()
        i = raw.inventory
        self.reject(replace(raw, inventory=replace(i, required_position_ids=(i.required_position_ids[0],) * 2)), "BINDING_REJECTED")
        row = i.envelopes[0]
        env = replace(row.value, scenarios=(row.value.scenarios[0],) * 2)
        self.reject(replace(raw, inventory=replace(i, envelopes=(replace(row, value=env),) + i.envelopes[1:])), "BINDING_REJECTED")
        self.reject(replace(raw, association=replace(raw.association, provenance=raw.association.identity)), "BINDING_REJECTED")

    def test_funding_sequence_preserved_invalid_reorder_rejected(self):
        raw = binding()
        claim = raw.inventory.envelopes[0].value.scenarios[0].claim
        observation = claim.observations[0]
        # Two distinct increasing obligations, exact supplied schedule.
        second = replace(observation, timestamp=observation.timestamp + 1)
        schedule = replace(claim.schedule, expected_settlements=(observation.timestamp, second.timestamp))
        ordered = replace(claim, observations=(observation, second), schedule=schedule)
        reversed_claim = replace(ordered, observations=(second, observation))
        self.assertNotEqual(wire(ordered), wire(reversed_claim))
        self.assertEqual(wire(reversed_claim, normalize=True), reference(reversed_claim))
        row = raw.inventory.envelopes[0]
        scenarios = (replace(row.value.scenarios[0], claim=reversed_claim),) + row.value.scenarios[1:]
        env = replace(row.value, scenarios=scenarios)
        invalid = replace(raw, inventory=replace(raw.inventory, envelopes=(replace(row, value=env),) + raw.inventory.envelopes[1:]))
        self.reject(invalid, "BINDING_REJECTED")
        backwards = replace(ordered, schedule=replace(schedule, expected_settlements=tuple(reversed(schedule.expected_settlements))))
        self.assertNotEqual(wire(ordered), wire(backwards))
        env = replace(row.value, scenarios=(replace(row.value.scenarios[0], claim=backwards),) + row.value.scenarios[1:])
        self.reject(replace(raw, inventory=replace(raw.inventory, envelopes=(replace(row, value=env),) + raw.inventory.envelopes[1:])), "BINDING_REJECTED")

    def test_valid_representation_scope_and_budget_changes_change_commitment(self):
        raw = binding()
        expected = m6.commit_content(raw, limits()).manifest.digest
        row = raw.inventory.plans[0]
        changed = replace(row, value=replace(row.value, budget=D("50.0")))
        changed_raw = replace(raw, inventory=replace(raw.inventory, plans=(changed,) + raw.inventory.plans[1:]))
        variants = [changed_raw, replace(raw, resources=replace(raw.resources, max_text_chars=10001))]
        # Consistent revision changes are valid M5 declarations, not substitution.
        ref = replace(raw.lifecycle.snapshots[0].ref, revision=1)
        life = replace(raw.lifecycle, snapshots=(replace(raw.lifecycle.snapshots[0], ref=ref),),
            evidence=(replace(raw.lifecycle.evidence[0], ref=ref),))
        variants.append(replace(raw, lifecycle=life, association=replace(raw.association, revision=1)))
        variants.append(replace(raw, association=replace(raw.association,
            provenance=replace(raw.association.provenance, identity="different-provenance"))))
        for variant in variants:
            out = m6.commit_content(variant, limits())
            self.assertEqual(out.status, Readiness.SUFFICIENT)
            self.assertNotEqual(out.manifest.digest, expected)
            self.assertEqual(out.manifest.digest, sha256(REFERENCE_DOMAIN + reference(variant, True)).hexdigest())

    def test_revoked_stale_cross_snapshot_and_missing_association(self):
        raw = binding()
        revoked = with_events(raw.lifecycle, (event(raw.lifecycle, issued_at=BASE, available_at=BASE),))
        out = self.reject(with_lifecycle(raw, revoked), "BINDING_REJECTED")
        self.assertEqual(out.status, Readiness.INSUFFICIENT)
        self.assertIn("M4_INSUFFICIENT", out.binding.reasons)
        stale = replace(raw.lifecycle, evidence=(replace(raw.lifecycle.evidence[0], expires_at=BASE),))
        self.reject(with_lifecycle(raw, stale), "BINDING_REJECTED")
        for changes in ({"snapshot_id": "different"}, {"revision": 1}, {"owner_id": "different"}, {"evaluation_time": BASE + 1}):
            self.reject(replace(raw, association=replace(raw.association, **changes)), "BINDING_REJECTED")
        out = self.reject(replace(raw, association=None), "BINDING_REJECTED")
        self.assertIsNotNone(out.binding.inventory)
        self.assertIsNotNone(out.binding.lifecycle)

    def test_lifecycle_event_and_reference_order_never_repaired(self):
        life = ledger(2)
        events = (event(life, index=0, event_id="b"), event(life, index=1, event_id="a"))
        invalid = with_events(life, events)
        raw = with_lifecycle(binding(0), invalid)
        out = self.reject(raw, "BINDING_REJECTED")
        self.assertIn("UNORDERED_EVENTS", out.binding.lifecycle.reasons)
        self.assertEqual(wire(invalid, normalize=True), reference(invalid, normalize=True))
        self.assertNotEqual(wire(events, m6._Sequence(m4.LifecycleEvent)), wire(tuple(reversed(events)), m6._Sequence(m4.LifecycleEvent)))

    def test_manifest_association_flags_and_forged_success(self):
        raw = binding()
        out = m6.commit_content(raw, limits())
        for name in ("owner_id", "source_id", "version", "snapshot_id", "revision", "snapshot_time", "evaluation_time"):
            old = getattr(out.manifest, name)
            bad = replace(out.manifest, **{name: old + 1 if type(old) is int else old + "x"})
            with self.subTest(field=name), self.assertRaises(ValueError):
                replace(out, manifest=bad)
        for changes in ({"digest": "f" * 63}, {"schema": "V2"}, {"algorithm": "SHA512"}, {"byte_length": True}):
            with self.assertRaises(ValueError):
                replace(out.manifest, **changes)
        for changes in ({"binding": None}, {"association": None}, {"manifest": None}, {"reason": "ADMIT"}):
            with self.assertRaises(ValueError):
                replace(out, **changes)
        forged = m6.assess_binding(raw)
        object.__setattr__(forged.inventory, "authority", "FORGED")
        with self.assertRaises(ValueError):
            replace(out, binding=forged)
        self.assertEqual((out.authority, out.evidence, out.aggregate_state, out.risk_clearance),
            ("SYNTHETIC_DIAGNOSTIC_ONLY", "SYNTHETIC_ONLY", "BLOCKED", "NOT CLEARED"))
        for value in (out, out.manifest, out.binding):
            with self.assertRaises(TypeError):
                bool(value)

    def test_commitment_has_no_io_or_execution_calls(self):
        # Guarded runner independently denies all disk/network/account access.
        # These traps cover accidental direct I/O during the public call itself.
        with patch("builtins.open", side_effect=AssertionError("I/O")):
            out = m6.commit_content(binding(), limits())
        self.assertEqual(out.status, Readiness.SUFFICIENT)
        self.assertFalse(hasattr(out, "orders"))
        self.assertFalse(hasattr(out, "aggregate_loss"))
