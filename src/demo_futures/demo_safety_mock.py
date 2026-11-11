"""Offline safety exercise. Every event, account snapshot and intent is invented."""

import hashlib
import json
from dataclasses import dataclass, fields, replace
from datetime import date
from decimal import Context, Decimal, DecimalException, Inexact, InvalidOperation, Overflow, localcontext
from enum import Enum, auto

from .risk import BacktestConfig, DailyLossGuard


_RISK = BacktestConfig()


class Signal(Enum):
    CONNECT = auto()
    DISCONNECT = auto()
    RESTART = auto()
    STALE = auto()
    RECONCILE = auto()
    ENTRY = auto()
    PROTECT = auto()
    KILL = auto()


class IntentKind(Enum):
    RECONCILE = auto()
    ENTRY = auto()
    PROTECT = auto()
    CANCEL_ENTRY = auto()
    CLOSE_POSITION = auto()


class Outcome(Enum):
    OPEN = auto()
    FILLED = auto()
    REJECTED = auto()
    CANCELLED = auto()
    PROTECTED = auto()
    CLOSED = auto()


class ReviewStatus(Enum):
    RECONCILIATION_REQUIRED = auto()
    ACTION_UNRESOLVED = auto()
    REJECTED_SAFETY_ACTION = auto()
    EXPOSURE_PRESENT = auto()
    KILLED_FLAT = auto()
    HALTED_FLAT = auto()
    CLEAR = auto()


class RecoveryChoice(Enum):
    HOLD = auto()
    CANCEL_ENTRY = auto()
    CLOSE_POSITION = auto()
    RESUME = auto()


@dataclass(frozen=True)
class Intent:
    request: int
    kind: IntentKind
    target: int | None = None

    @property
    def reduce_only(self) -> bool:
        return self.kind in (IntentKind.PROTECT, IntentKind.CLOSE_POSITION)


@dataclass(frozen=True)
class Position:
    # Fixture positions retain their originating entry ID across a fill.
    entry_id: int
    protected: bool


@dataclass(frozen=True)
class ProtectiveOrder:
    order_id: int
    position_id: int


@dataclass(frozen=True)
class Resolution:
    request: int
    outcome: Outcome


@dataclass(frozen=True)
class ReconciliationRequest:
    fixture_id: str
    cutoff: int
    state_digest: str
    prior_version: int
    pending: Intent | None


@dataclass(frozen=True)
class Inventory:
    request: ReconciliationRequest
    observed_through: int
    account_version: int
    fresh: bool
    open_entries: tuple[int, ...] | None
    positions: tuple[Position, ...] | None
    protective_orders: tuple[ProtectiveOrder, ...] | None
    utc_day: date
    opening_equity: Decimal
    equity: Decimal
    resolution: Resolution | None = None


@dataclass(frozen=True)
class PartialAck:
    request: int


@dataclass(frozen=True)
class OperatorDecision:
    request: ReconciliationRequest
    account_version: int
    choice: RecoveryChoice
    target: int | None = None


@dataclass(frozen=True)
class Event:
    sequence: int
    payload: Signal | Inventory | PartialAck | OperatorDecision


@dataclass(frozen=True)
class JournalFault:
    after_sequence: int
    reason: str
    kill_requested: bool
    observed_sequence: int | None = None
    event_digest: str | None = None


@dataclass(frozen=True)
class Checkpoint:
    schema_version: int
    fixture_id: str
    record_count: int
    state_digest: str


@dataclass(frozen=True)
class Snapshot:
    checkpoint: Checkpoint
    journal: tuple[Event | JournalFault, ...]


@dataclass(frozen=True)
class State:
    """Invented restart snapshot, including latches and the event journal."""

    fixture_id: str = "demo-rehearsal"
    sequence: int = 0
    connected: bool = False
    trusted: bool = False
    inventory: Inventory | None = None
    reconciliation: ReconciliationRequest | None = None
    observed_version: int = 0
    pending: Intent | None = None
    day: date | None = None
    anchor: Decimal | None = None
    daily_halt: bool = False
    operator_hold: bool = False
    kill_latched: bool = False
    integrity_fault: bool = False
    rejected_safety_actions: frozenset[tuple[IntentKind, int]] = frozenset()
    journal: tuple[Event | JournalFault, ...] = ()

    @property
    def mode(self) -> str:
        if self.kill_latched:
            return "KILLED"
        if self.daily_halt:
            return "DAILY_HALT"
        if self.operator_hold or self.integrity_fault:
            return "OPERATOR_HOLD"
        if not self.connected:
            return "DISCONNECTED"
        if not self.trusted or self.pending is not None:
            return "RECONCILIATION_REQUIRED"
        return "ACTIVE"

    @property
    def emergency_flat_verified(self) -> bool:
        return (
            self.kill_latched and self.connected and self.trusted and not self.integrity_fault
            and self.pending is None
            and self.inventory is not None and self.inventory.open_entries == ()
            and self.inventory.positions == () and self.inventory.protective_orders == ()
        )

    @property
    def review_status(self) -> ReviewStatus:
        if self.pending is not None:
            return ReviewStatus.ACTION_UNRESOLVED
        if not self.trusted or self.integrity_fault:
            return ReviewStatus.RECONCILIATION_REQUIRED
        if self.emergency_flat_verified:
            return ReviewStatus.KILLED_FLAT
        if self.inventory.open_entries or self.inventory.positions:
            if self.rejected_safety_actions:
                return ReviewStatus.REJECTED_SAFETY_ACTION
            return ReviewStatus.EXPOSURE_PRESENT
        if self.operator_hold or self.daily_halt:
            return ReviewStatus.HALTED_FLAT
        return ReviewStatus.CLEAR


@dataclass(frozen=True)
class Step:
    state: State
    reason: str
    intent: Intent | None = None


def _uncertain(state: State, **changes) -> State:
    return replace(state, trusted=False, reconciliation=None, **changes)


def _identifier(value: int) -> bool:
    return type(value) is int and value > 0


def _digest_value(value) -> dict | str:
    if isinstance(value, Enum):
        return {"type": type(value).__name__, "name": value.name}
    if isinstance(value, (date, Decimal)):
        return {"type": type(value).__name__, "value": str(value)}
    if type(value) is frozenset:
        return {"type": "frozenset", "values": sorted(_digest(item) for item in value)}
    return {"type": type(value).__name__,
            **{field.name: getattr(value, field.name) for field in fields(value)}}


def _digest(value) -> str:
    encoded = json.dumps(value, default=_digest_value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def _valid_digest(value: str) -> bool:
    return type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _valid_request(request: ReconciliationRequest) -> bool:
    if type(request) is not ReconciliationRequest:
        return False
    pending = request.pending
    return (
        type(request.fixture_id) is str and bool(request.fixture_id)
        and _identifier(request.cutoff)
        and _valid_digest(request.state_digest)
        and type(request.prior_version) is int and request.prior_version >= 0
        and (pending is None or type(pending) is Intent and _identifier(pending.request)
             and type(pending.kind) is IntentKind and _identifier(pending.target))
    )


def _valid_payload(payload: Signal | Inventory | PartialAck | OperatorDecision) -> bool:
    # Validate before comparing duplicates, including non-finite Decimal values.
    if type(payload) is Signal:
        return True
    if type(payload) is PartialAck:
        return _identifier(payload.request)
    if type(payload) is OperatorDecision:
        return (
            _valid_request(payload.request) and _identifier(payload.account_version)
            and type(payload.choice) is RecoveryChoice
            and (payload.target is None or _identifier(payload.target))
        )
    if type(payload) is not Inventory:
        return False
    entries, positions, protection = payload.open_entries, payload.positions, payload.protective_orders
    resolution = payload.resolution
    return (
        _valid_request(payload.request) and type(payload.fresh) is bool
        and _identifier(payload.observed_through) and _identifier(payload.account_version)
        and type(payload.utc_day) is date
        and all(type(value) is Decimal and value.is_finite()
                for value in (payload.opening_equity, payload.equity))
        and (entries is None or type(entries) is tuple and all(map(_identifier, entries)))
        and (positions is None or type(positions) is tuple and all(
            type(position) is Position and _identifier(position.entry_id)
            and type(position.protected) is bool for position in positions
        ))
        and (protection is None or type(protection) is tuple and all(
            type(order) is ProtectiveOrder and _identifier(order.order_id)
            and _identifier(order.position_id) for order in protection
        ))
        and (resolution is None or type(resolution) is Resolution
             and _identifier(resolution.request) and type(resolution.outcome) is Outcome)
    )


def _resolution_matches(pending: Intent, resolution: Resolution, entries: set[int],
                        positions: dict[int, bool]) -> bool:
    if pending.request != resolution.request:
        return False
    target, outcome = pending.target, resolution.outcome
    if pending.kind is IntentKind.ENTRY:
        return (
            outcome is Outcome.OPEN and target in entries
            or outcome is Outcome.FILLED and target in positions
            or outcome in (Outcome.REJECTED, Outcome.CANCELLED)
            and target not in entries and target not in positions
        )
    if pending.kind is IntentKind.CANCEL_ENTRY:
        return (
            outcome is Outcome.CANCELLED and target not in entries and target not in positions
            or outcome is Outcome.FILLED and target in positions
            or outcome is Outcome.REJECTED and target in entries
        )
    if pending.kind is IntentKind.PROTECT:
        return (
            outcome is Outcome.PROTECTED and positions.get(target) is True
            or outcome is Outcome.REJECTED and positions.get(target) is False
        )
    return (
        outcome is Outcome.CLOSED and target not in entries and target not in positions
        or outcome is Outcome.REJECTED and target in positions
    )


def _known_exposure_accounted_for(state: State, entries: set[int],
                                  positions: dict[int, bool], resolution: Resolution | None) -> bool:
    prior = state.inventory
    if prior is None:
        return True
    missing_entries = set(prior.open_entries) - entries
    missing_positions = {position.entry_id for position in prior.positions} - positions.keys()
    if resolution is not None:
        # The caller has already matched the outcome, pending action and target inventory.
        if resolution.outcome in (Outcome.CANCELLED, Outcome.FILLED):
            missing_entries.discard(state.pending.target)
        if resolution.outcome is Outcome.CLOSED:
            missing_positions.discard(state.pending.target)
    return not missing_entries and not missing_positions


def _reconcile(state: State, view: Inventory) -> Step:
    if not state.connected or view.request != state.reconciliation or view.request.pending != state.pending:
        return Step(_uncertain(state), "UNBOUND_RECONCILIATION")
    if state.integrity_fault:
        return Step(_uncertain(state), "JOURNAL_REVIEW_REQUIRED")
    if view.observed_through != view.request.cutoff or view.account_version <= state.observed_version:
        return Step(_uncertain(state), "STALE_OR_CONFLICTING_OBSERVATION")
    # A bound observation version is single-use even when its contents are incomplete.
    state = replace(state, observed_version=view.account_version)
    if (not view.fresh or view.open_entries is None or view.positions is None
            or view.protective_orders is None):
        return Step(_uncertain(state), "INCOMPLETE_OR_STALE_INVENTORY")

    entries = set(view.open_entries)
    positions = {position.entry_id: position.protected for position in view.positions}
    protective_ids = {order.order_id for order in view.protective_orders}
    protected_positions = {order.position_id for order in view.protective_orders}
    if (len(entries) != len(view.open_entries) or len(positions) != len(view.positions)
            or entries.intersection(positions) or len(protective_ids) != len(view.protective_orders)
            or protective_ids.intersection(entries | positions.keys())
            or protected_positions != {target for target, protected in positions.items() if protected}):
        return Step(_uncertain(state, operator_hold=True), "CONFLICTING_INVENTORY")
    if ((state.day is not None and view.utc_day < state.day)
            or (view.utc_day == state.day and view.opening_equity != state.anchor)):
        return Step(_uncertain(state, operator_hold=True), "CONFLICTING_DAILY_ANCHOR")

    guard = DailyLossGuard(_RISK.daily_loss_fraction)
    guard.day, guard.anchor, guard.halted = state.day, state.anchor, state.daily_halt
    # Keep the existing rule exact and independent of a caller's Decimal context.
    precision = max(28, len(view.opening_equity.as_tuple().digits) + 2)
    try:
        with localcontext(Context(prec=precision, traps=[Inexact, InvalidOperation, Overflow])):
            guard.begin_day(view.utc_day, view.opening_equity)
            daily_halt = guard.check(view.equity)
    except DecimalException:
        return Step(_uncertain(state, operator_hold=True), "INVALID_DAILY_EQUITY")
    # Positive loss evidence can add a halt, while incomplete evidence cannot lift one.
    if daily_halt:
        state = replace(state, day=guard.day, anchor=guard.anchor, daily_halt=True, operator_hold=True)

    pending, resolution = state.pending, view.resolution
    if pending is not None and resolution is None:
        return Step(_uncertain(state), "ACTION_OUTCOME_UNKNOWN")
    if resolution is not None and (
        pending is None or not _resolution_matches(pending, resolution, entries, positions)
    ):
        return Step(_uncertain(state, operator_hold=True), "CONFLICTING_ACTION_RESOLUTION")
    if not _known_exposure_accounted_for(state, entries, positions, resolution):
        return Step(_uncertain(state, operator_hold=True), "UNCONFIRMED_EXPOSURE_CHANGE")

    rejected_exit = (pending is not None and pending.kind is not IntentKind.ENTRY
                     and resolution.outcome is Outcome.REJECTED)
    rejected_actions = state.rejected_safety_actions
    if rejected_exit:
        rejected_actions = rejected_actions | {(pending.kind, pending.target)}
    exposure_problem = (len(entries) + len(positions) > _RISK.max_positions
                        or False in positions.values())
    state = replace(state, trusted=True, inventory=view, reconciliation=None, pending=None,
                    day=guard.day, anchor=guard.anchor, daily_halt=daily_halt,
                    operator_hold=state.operator_hold or daily_halt or rejected_exit or exposure_problem,
                    rejected_safety_actions=rejected_actions)
    if rejected_exit:
        return Step(state, "SAFETY_ACTION_REJECTED_OPERATOR_REQUIRED")
    if state.emergency_flat_verified:
        return Step(state, "EMERGENCY_FLAT_VERIFIED")
    return Step(state, "RECONCILED")


def _action(state: State, sequence: int, kind: IntentKind, target: int) -> Step:
    if (kind, target) in state.rejected_safety_actions:
        return Step(state, "REJECTED_ACTION_REQUIRES_OPERATOR")
    intent = Intent(sequence, kind, target)
    return Step(_uncertain(state, pending=intent), "SIMULATED_INTENT", intent)


def _record_fault(state: State, fault: JournalFault) -> Step:
    if fault in state.journal:
        return Step(state, "DUPLICATE_IGNORED")
    return Step(_uncertain(state, integrity_fault=True, operator_hold=True,
                           kill_latched=state.kill_latched or fault.kill_requested,
                           journal=(*state.journal, fault)), fault.reason)


def _operator_decision(state: State, sequence: int, decision: OperatorDecision) -> Step:
    view = state.inventory
    if (view is None or decision.request != view.request
            or decision.account_version != view.account_version):
        return Step(state, "STALE_OPERATOR_REVIEW")
    choice, target = decision.choice, decision.target
    if choice is RecoveryChoice.HOLD and target is None:
        return Step(replace(state, operator_hold=True), "OPERATOR_HELD")
    if not state.connected or not state.trusted or state.pending is not None or state.integrity_fault:
        return Step(state, "TRUSTED_STATE_REQUIRED")
    if choice is RecoveryChoice.RESUME:
        if (target is not None or state.kill_latched or state.daily_halt
                or view.open_entries or view.positions or not state.operator_hold):
            return Step(state, "RESUME_BLOCKED")
        return Step(replace(state, operator_hold=False, rejected_safety_actions=frozenset()),
                    "OPERATOR_RESUMED")
    if state.kill_latched:
        if choice is RecoveryChoice.CANCEL_ENTRY and target in view.open_entries:
            return _action(state, sequence, IntentKind.CANCEL_ENTRY, target)
        if (choice is RecoveryChoice.CLOSE_POSITION and not view.open_entries
                and any(target == position.entry_id for position in view.positions)):
            return _action(state, sequence, IntentKind.CLOSE_POSITION, target)
    return Step(state, "RECOVERY_DECISION_BLOCKED")


def transition(state: State, event: Event) -> Step:
    """Apply one ordered fixture event with no side effects."""
    if type(event) is not Event:
        return _record_fault(state, JournalFault(state.sequence, "INVALID_EVENT", False))
    payload, sequence = event.payload, event.sequence
    if not _identifier(sequence) or not _valid_payload(payload):
        observed = sequence if _identifier(sequence) else None
        return _record_fault(state, JournalFault(state.sequence, "INVALID_EVENT",
                                                payload is Signal.KILL, observed))
    if sequence <= state.sequence:
        prior = next(record for record in reversed(state.journal)
                     if type(record) is Event and record.sequence == sequence)
        if _digest(event) == _digest(prior):
            return Step(state, "DUPLICATE_IGNORED")
    if sequence != state.sequence + 1:
        return _record_fault(state, JournalFault(state.sequence, "EVENT_SEQUENCE_CONFLICT",
                                                payload is Signal.KILL, sequence, _digest(event)))
    state = replace(state, sequence=sequence, journal=(*state.journal, event))

    if payload is Signal.KILL:
        return Step(_uncertain(state, kill_latched=True, operator_hold=True), "KILL_LATCHED")
    if payload in (Signal.DISCONNECT, Signal.RESTART):
        return Step(_uncertain(state, connected=False), payload.name)
    if payload is Signal.CONNECT:
        return Step(_uncertain(state, connected=True), "CONNECTED_RECONCILIATION_REQUIRED")
    if payload is Signal.STALE:
        return Step(_uncertain(state), "ACCOUNT_STALE")
    if payload is Signal.RECONCILE:
        if not state.connected:
            return Step(state, "DISCONNECTED")
        if state.reconciliation is not None:
            return Step(state, "RECONCILIATION_ALREADY_PENDING")
        intent = Intent(sequence, IntentKind.RECONCILE)
        request = ReconciliationRequest(state.fixture_id, sequence, checkpoint(state).state_digest,
                                        state.observed_version, state.pending)
        return Step(replace(state, trusted=False, reconciliation=request), "SIMULATED_INTENT", intent)
    if type(payload) is Inventory:
        return _reconcile(state, payload)
    if type(payload) is PartialAck:
        if state.pending is None or state.pending.request != payload.request:
            return Step(_uncertain(state, operator_hold=True), "UNBOUND_ACKNOWLEDGMENT")
        return Step(_uncertain(state), "PARTIAL_ACKNOWLEDGMENT")

    if type(payload) is OperatorDecision:
        return _operator_decision(state, sequence, payload)
    if (not state.connected or not state.trusted or state.pending is not None
            or state.integrity_fault):
        return Step(state, "TRUSTED_STATE_REQUIRED")
    view = state.inventory
    entries, positions = view.open_entries, view.positions
    if payload is Signal.ENTRY:
        if state.mode != "ACTIVE" or len(entries) + len(positions) >= _RISK.max_positions:
            return Step(state, "ENTRY_BLOCKED")
        return _action(state, sequence, IntentKind.ENTRY, sequence)
    if payload is Signal.PROTECT:
        unprotected = next((position for position in positions if not position.protected), None)
        if state.kill_latched or unprotected is None:
            return Step(state, "PROTECTION_BLOCKED")
        return _action(state, sequence, IntentKind.PROTECT, unprotected.entry_id)
    return Step(state, "INVALID_TRANSITION")


_SNAPSHOT_SCHEMA = 1


def checkpoint(state: State) -> Checkpoint:
    """Bind materialized state and journal for separate pinning by the fixture."""
    return Checkpoint(_SNAPSHOT_SCHEMA, state.fixture_id, len(state.journal),
                      _digest((_SNAPSHOT_SCHEMA, state)))


def create_snapshot(state: State) -> Snapshot:
    return Snapshot(checkpoint(state), state.journal)


def _valid_checkpoint(identity: Checkpoint) -> bool:
    return (
        type(identity) is Checkpoint
        and type(identity.schema_version) is int and identity.schema_version == _SNAPSHOT_SCHEMA
        and type(identity.fixture_id) is str and bool(identity.fixture_id)
        and type(identity.record_count) is int and identity.record_count >= 0
        and _valid_digest(identity.state_digest)
    )


def _valid_fault(record: JournalFault, sequence: int) -> bool:
    if (type(record.after_sequence) is not int or record.after_sequence != sequence
            or type(record.reason) is not str or type(record.kill_requested) is not bool):
        return False
    if record.reason == "INVALID_EVENT":
        return (record.event_digest is None
                and (record.observed_sequence is None or _identifier(record.observed_sequence)))
    return (record.reason == "EVENT_SEQUENCE_CONFLICT" and _identifier(record.observed_sequence)
            and record.observed_sequence != sequence + 1 and _valid_digest(record.event_digest))


def restore(snapshot: Snapshot, expected: Checkpoint) -> Step:
    """Recover from a pinned fixture checkpoint. Invalid snapshots raise ValueError."""
    if (type(snapshot) is not Snapshot or not _valid_checkpoint(expected)
            or not _valid_checkpoint(snapshot.checkpoint) or snapshot.checkpoint != expected
            or type(snapshot.journal) is not tuple
            or len(snapshot.journal) != expected.record_count):
        raise ValueError("Snapshot identity or schema mismatch")
    state = State(fixture_id=expected.fixture_id)
    for record in snapshot.journal:
        if type(record) is Event:
            if (not _identifier(record.sequence) or record.sequence != state.sequence + 1
                    or not _valid_payload(record.payload)):
                raise ValueError("Invalid event or discontinuous snapshot journal")
            state = transition(state, record).state
        elif (type(record) is JournalFault and _valid_fault(record, state.sequence)
              and record not in state.journal):
            state = _record_fault(state, record).state
        else:
            raise ValueError("Invalid fault record in snapshot journal")
    if checkpoint(state) != expected:
        raise ValueError("Snapshot content does not match the pinned checkpoint")
    # Replay is internal. Only the restart marker is returned and it emits no intent.
    return transition(state, Event(state.sequence + 1, Signal.RESTART))


def demonstration() -> tuple[Step, ...]:
    """Replay a confirmed emergency exit and an alternative rejected exit."""
    position = Position(5, False)
    steps = []
    state = State()

    def record(step: Step) -> None:
        nonlocal state
        steps.append(step)
        state = step.state

    def send(payload) -> None:
        record(transition(state, Event(state.sequence + 1, payload)))

    def observe(entries=(), positions=(), outcome=None) -> None:
        send(Signal.RECONCILE)
        request = state.reconciliation
        resolution = None if outcome is None else Resolution(request.pending.request, outcome)
        send(Inventory(request, request.cutoff, request.prior_version + 1, True, entries, positions,
                       (), date(2000, 1, 1), Decimal("100"), Decimal("98"), resolution))

    def decide(choice: RecoveryChoice, target: int | None = None) -> None:
        view = state.inventory
        send(OperatorDecision(view.request, view.account_version, choice, target))

    send(Signal.CONNECT)
    observe(entries=None)
    observe(entries=(4,), positions=(position,))
    send(Signal.KILL)
    observe(entries=(4,), positions=(position,))
    decide(RecoveryChoice.CANCEL_ENTRY, 4)
    observe(positions=(position,), outcome=Outcome.CANCELLED)
    decide(RecoveryChoice.CLOSE_POSITION, 5)
    # The fixture pins the expected identity independently of the supplied object.
    expected = checkpoint(state)
    record(restore(create_snapshot(state), expected))
    send(Signal.CONNECT)
    observe(positions=(position,))
    observe(positions=(position,), outcome=Outcome.CLOSED)
    unresolved = state
    observe(outcome=Outcome.CLOSED)
    decide(RecoveryChoice.RESUME)

    state = unresolved
    observe(positions=(position,), outcome=Outcome.REJECTED)
    decide(RecoveryChoice.HOLD)
    decide(RecoveryChoice.CLOSE_POSITION, 5)
    record(transition(state, Event(state.sequence + 2, Signal.STALE)))
    return tuple(steps)


def main() -> None:
    for step in demonstration():
        intent = "" if step.intent is None else f" {step.intent.kind.name}"
        print(f"{step.state.sequence:02d} {step.state.mode} {step.state.review_status.name} {step.reason}{intent}")
    print("CONFIRMED BRANCH: flat inventory verified, kill remains latched")
    print("UNRESOLVED BRANCH: emergency exit rejected, exposure retained, operator hold")
    print("RISK NOT CLEARED")


if __name__ == "__main__":
    main()
