"""Offline safety exercise. Every event, account snapshot and intent is invented."""

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
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
    EMERGENCY_STEP = auto()
    OPERATOR_RESUME = auto()


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
class Resolution:
    request: int
    outcome: Outcome


@dataclass(frozen=True)
class Inventory:
    request: int
    fresh: bool
    open_entries: tuple[int, ...] | None
    positions: tuple[Position, ...] | None
    utc_day: date
    opening_equity: Decimal
    equity: Decimal
    resolution: Resolution | None = None


@dataclass(frozen=True)
class PartialAck:
    request: int


@dataclass(frozen=True)
class Event:
    sequence: int
    payload: Signal | Inventory | PartialAck


@dataclass(frozen=True)
class State:
    """Invented restart snapshot, including latches and the event journal."""

    connected: bool = False
    trusted: bool = False
    inventory: Inventory | None = None
    reconciliation: int | None = None
    pending: Intent | None = None
    day: date | None = None
    anchor: Decimal | None = None
    daily_halt: bool = False
    operator_hold: bool = False
    kill_latched: bool = False
    integrity_fault: bool = False
    rejected_safety_actions: frozenset[tuple[IntentKind, int]] = frozenset()
    journal: tuple[Event, ...] = ()

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
            and self.inventory.positions == ()
        )


@dataclass(frozen=True)
class Step:
    state: State
    reason: str
    intent: Intent | None = None


def _uncertain(state: State, **changes) -> State:
    return replace(state, trusted=False, reconciliation=None, **changes)


def _identifier(value: int) -> bool:
    return type(value) is int and value > 0


def _valid_payload(payload: Signal | Inventory | PartialAck) -> bool:
    # Validate before comparing duplicates, including non-finite Decimal values.
    if type(payload) is Signal:
        return True
    if type(payload) is PartialAck:
        return _identifier(payload.request)
    if type(payload) is not Inventory:
        return False
    entries, positions, resolution = payload.open_entries, payload.positions, payload.resolution
    return (
        _identifier(payload.request) and type(payload.fresh) is bool
        and type(payload.utc_day) is date
        and all(type(value) is Decimal and value.is_finite()
                for value in (payload.opening_equity, payload.equity))
        and (entries is None or type(entries) is tuple and all(map(_identifier, entries)))
        and (positions is None or type(positions) is tuple and all(
            type(position) is Position and _identifier(position.entry_id)
            and type(position.protected) is bool for position in positions
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


def _reconcile(state: State, view: Inventory) -> Step:
    if not state.connected or view.request != state.reconciliation:
        return Step(_uncertain(state), "UNBOUND_RECONCILIATION")
    if not view.fresh or view.open_entries is None or view.positions is None:
        return Step(_uncertain(state), "INCOMPLETE_OR_STALE_INVENTORY")

    entries = set(view.open_entries)
    positions = {position.entry_id: position.protected for position in view.positions}
    if (len(entries) != len(view.open_entries) or len(positions) != len(view.positions)
            or entries.intersection(positions)):
        return Step(_uncertain(state, operator_hold=True), "CONFLICTING_INVENTORY")
    if ((state.day is not None and view.utc_day < state.day)
            or (view.utc_day == state.day and view.opening_equity != state.anchor)):
        return Step(_uncertain(state, operator_hold=True), "CONFLICTING_DAILY_ANCHOR")

    guard = DailyLossGuard(_RISK.daily_loss_fraction)
    guard.day, guard.anchor, guard.halted = state.day, state.anchor, state.daily_halt
    guard.begin_day(view.utc_day, view.opening_equity)
    daily_halt = guard.check(view.equity)
    # Positive evidence of a loss latches even while an action remains unresolved.
    state = replace(state, day=guard.day, anchor=guard.anchor, daily_halt=daily_halt,
                    operator_hold=state.operator_hold or daily_halt)

    pending, resolution = state.pending, view.resolution
    if pending is not None and resolution is None:
        return Step(_uncertain(state), "ACTION_OUTCOME_UNKNOWN")
    if resolution is not None and (
        pending is None or not _resolution_matches(pending, resolution, entries, positions)
    ):
        return Step(_uncertain(state, operator_hold=True), "CONFLICTING_ACTION_RESOLUTION")

    rejected_exit = (pending is not None and pending.kind is not IntentKind.ENTRY
                     and resolution.outcome is Outcome.REJECTED)
    rejected_actions = state.rejected_safety_actions
    if rejected_exit:
        rejected_actions = rejected_actions | {(pending.kind, pending.target)}
    exposure_problem = (len(entries) + len(positions) > _RISK.max_positions
                        or False in positions.values())
    state = replace(state, trusted=True, inventory=view, reconciliation=None, pending=None,
                    operator_hold=state.operator_hold or rejected_exit or exposure_problem,
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


def transition(state: State, event: Event) -> Step:
    """Apply one ordered fixture event with no side effects."""
    payload, sequence = event.payload, event.sequence
    if not _identifier(sequence) or not _valid_payload(payload):
        return Step(_uncertain(state, integrity_fault=True,
                               kill_latched=state.kill_latched or payload is Signal.KILL),
                    "INVALID_EVENT")
    if sequence <= len(state.journal) and event == state.journal[sequence - 1]:
        return Step(state, "DUPLICATE_IGNORED")
    if sequence != len(state.journal) + 1:
        return Step(_uncertain(state, integrity_fault=True,
                               kill_latched=state.kill_latched or payload is Signal.KILL),
                    "EVENT_SEQUENCE_CONFLICT")
    state = replace(state, journal=(*state.journal, event))

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
        return Step(replace(state, trusted=False, reconciliation=sequence), "SIMULATED_INTENT", intent)
    if type(payload) is Inventory:
        return _reconcile(state, payload)
    if type(payload) is PartialAck:
        if state.pending is None or state.pending.request != payload.request:
            return Step(_uncertain(state, operator_hold=True), "UNBOUND_ACKNOWLEDGMENT")
        return Step(_uncertain(state), "PARTIAL_ACKNOWLEDGMENT")

    if (not state.connected or not state.trusted or state.pending is not None
            or state.integrity_fault):
        return Step(state, "TRUSTED_STATE_REQUIRED")
    view = state.inventory
    entries, positions = view.open_entries, view.positions
    if payload is Signal.OPERATOR_RESUME:
        if state.kill_latched or state.daily_halt or entries or positions:
            return Step(state, "RESUME_BLOCKED")
        return Step(replace(state, operator_hold=False, rejected_safety_actions=frozenset()),
                    "OPERATOR_RESUMED")
    if payload is Signal.ENTRY:
        if state.mode != "ACTIVE" or len(entries) + len(positions) >= _RISK.max_positions:
            return Step(state, "ENTRY_BLOCKED")
        return _action(state, sequence, IntentKind.ENTRY, sequence)
    if payload is Signal.PROTECT:
        unprotected = next((position for position in positions if not position.protected), None)
        if state.kill_latched or unprotected is None:
            return Step(state, "PROTECTION_BLOCKED")
        return _action(state, sequence, IntentKind.PROTECT, unprotected.entry_id)
    if payload is not Signal.EMERGENCY_STEP or not state.kill_latched:
        return Step(state, "EMERGENCY_STEP_BLOCKED")
    if entries:
        return _action(state, sequence, IntentKind.CANCEL_ENTRY, min(entries))
    if positions:
        return _action(state, sequence, IntentKind.CLOSE_POSITION,
                       min(position.entry_id for position in positions))
    return Step(state, "EMERGENCY_FLAT_VERIFIED")


def demonstration() -> tuple[Step, ...]:
    """Replay the fixed fixture, including an unresolved rejected emergency exit."""
    day = date(2000, 1, 1)

    def inventory(request, equity="100", positions=(), resolution=None):
        return Inventory(request, True, (), positions, day, Decimal("100"), Decimal(equity), resolution)

    events = (
        Signal.CONNECT, Signal.ENTRY, Signal.RECONCILE, inventory(3), Signal.ENTRY,
        PartialAck(5), Signal.DISCONNECT, Signal.RESTART, Signal.CONNECT,
        Signal.RECONCILE, inventory(10), Signal.RECONCILE,
        inventory(12, "98", (Position(5, False),), Resolution(5, Outcome.FILLED)),
        Signal.PROTECT, Signal.RECONCILE,
        inventory(15, "98", (Position(5, False),), Resolution(14, Outcome.REJECTED)),
        Signal.KILL, Signal.EMERGENCY_STEP, Signal.RECONCILE,
        inventory(19, "98", (Position(5, False),)), Signal.EMERGENCY_STEP,
        Signal.RECONCILE,
        inventory(22, "98", (Position(5, False),), Resolution(21, Outcome.REJECTED)),
        Signal.EMERGENCY_STEP, Signal.OPERATOR_RESUME,
    )
    steps = []
    state = State()
    for sequence, payload in enumerate(events, 1):
        step = transition(state, Event(sequence, payload))
        steps.append(step)
        state = step.state
    return tuple(steps)


def main() -> None:
    for step in demonstration():
        intent = "" if step.intent is None else f" {step.intent.kind.name}"
        print(f"{len(step.state.journal):02d} {step.state.mode} {step.reason}{intent}")
    print("UNRESOLVED: emergency exit rejected, position remains, operator intervention required")
    print("RISK NOT CLEARED")


if __name__ == "__main__":
    main()
