"""Pure normalization of invented protocol declarations."""

from dataclasses import dataclass
from decimal import Decimal
import json

from .demo_safety_mock import Inventory, State, Event, Signal, transition


@dataclass(frozen=True)
class Row:
    position_id: int
    symbol: str
    side: str
    quantity: Decimal


@dataclass(frozen=True)
class Page:
    inventory: Inventory
    mode: str
    number: int
    token: str | None
    next_token: str | None
    rows: tuple[Row, ...]


@dataclass(frozen=True)
class StreamEvent:
    sequence: int
    version: int
    order_id: int
    status: str
    filled: Decimal
    quantity: Decimal
    side: str


@dataclass(frozen=True)
class Result:
    verdict: str
    reason: str
    state: State


def normalize(state: State, pages: tuple[Page, ...], events: tuple[StreamEvent, ...],
              *, watermark: int, through: int, max_pages: int, max_rows: int) -> Result:
    """A full declared stream and bounded atomic snapshot are required together."""
    def blocked(reason):
        stale = transition(state, Event(state.sequence + 1, Signal.STALE)).state
        return Result("BLOCKED", reason, stale)

    if any(type(value) is not int or value < 0 for value in (watermark, through, max_pages, max_rows)):
        return blocked("INVALID_BUDGET_OR_CUTOFF")
    if type(pages) is not tuple or not pages or len(pages) > max_pages or type(events) is not tuple:
        return blocked("INCOMPLETE_OR_OVER_BUDGET")
    if through < watermark or len(events) != through - watermark or len(events) > max_rows:
        return blocked("STREAM_COVERAGE")
    if any(type(page) is not Page for page in pages):
        return blocked("INVALID_PAGE")
    first = pages[0]
    if type(first.inventory) is not Inventory or first.mode not in ("ONE_WAY", "HEDGE"):
        return blocked("INVALID_DECLARATION")
    if through != first.inventory.observed_through:
        return blocked("CUTOFF_MISMATCH")
    allowed_sides = ("BOTH",) if first.mode == "ONE_WAY" else ("LONG", "SHORT")
    token = None
    tokens = set()
    rows = []
    for number, page in enumerate(pages):
        if (type(page.number) is not int or page.number != number or page.token != token
                or page.mode != first.mode or page.inventory != first.inventory):
            return blocked("PAGE_BINDING_OR_ORDER")
        if type(page.rows) is not tuple or len(rows) + len(page.rows) > max_rows:
            return blocked("ROW_BUDGET")
        for row in page.rows:
            if (type(row) is not Row or type(row.position_id) is not int or row.position_id <= 0
                    or row.symbol not in ("BTCUSDT", "ETHUSDT")
                    or row.side not in allowed_sides or type(row.quantity) is not Decimal
                    or not row.quantity.is_finite() or row.quantity == 0
                    or first.mode == "HEDGE" and row.quantity < 0):
                return blocked("POSITION_SIDE_OR_QUANTITY")
        rows.extend(page.rows)
        token = page.next_token
        if token is None:
            if number != len(pages) - 1:
                return blocked("PAGES_AFTER_COMPLETION")
        elif type(token) is not str or not token or token in tokens or len(token) > 128:
            return blocked("INVALID_CONTINUATION")
        else:
            tokens.add(token)
    if token is not None:
        return blocked("PAGINATION_INTERRUPTED")
    identities = [(row.symbol, row.side) for row in rows]
    if (len(set(identities)) != len(identities)
            or len({row.position_id for row in rows}) != len(rows)
            or {row.position_id for row in rows} != {
                position.entry_id for position in first.inventory.positions or ()
            }):
        return blocked("POSITION_INVENTORY_CONFLICT")
    latest = {}
    for sequence, event in enumerate(events, watermark + 1):
        if (type(event) is not StreamEvent or type(event.sequence) is not int or event.sequence != sequence
                or type(event.version) is not int or event.version != first.inventory.account_version
                or type(event.order_id) is not int or event.order_id <= 0 or event.side not in allowed_sides
                or event.status not in ("ACK", "PARTIAL", "FILLED", "CANCELLED", "REJECTED", "CLOSED", "PROTECTED")
                or any(type(value) is not Decimal or not value.is_finite()
                       for value in (event.filled, event.quantity))):
            return blocked("EVENT_BINDING_OR_ORDER")
        if not 0 <= event.filled <= event.quantity or event.quantity <= 0:
            return blocked("INVALID_FILL")
        prior = latest.get(event.order_id)
        if prior is not None and (
            prior.side != event.side or prior.quantity != event.quantity or prior.filled > event.filled
            or prior.status in ("FILLED", "CANCELLED", "REJECTED") and prior != event
        ):
            return blocked("CONFLICTING_CONFIRMATION")
        latest[event.order_id] = event
        if event.status == "PARTIAL" or event.status == "CANCELLED" and event.filled > 0:
            return blocked("PARTIAL_EXPOSURE_UNRESOLVED")
        if event.status == "FILLED" and event.filled != event.quantity:
            return blocked("INCOMPLETE_FILL")
        if event.status == "FILLED" and event.order_id not in {row.position_id for row in rows}:
            return blocked("FILL_EXPOSURE_MISSING")
        if event.status in ("CLOSED", "PROTECTED") and (
            state.pending is None or event.order_id != state.pending.target
            or first.inventory.resolution is None
            or first.inventory.resolution.outcome.name != event.status
        ):
            return blocked("UNBOUND_SAFETY_CONFIRMATION")
        if event.status in ("ACK", "REJECTED") and event.filled != 0:
            return blocked("CONTRADICTORY_FILL")
    pending = state.pending
    resolution = first.inventory.resolution
    for evidence in latest.values():
        if (evidence.status == "ACK" and evidence.order_id not in (first.inventory.open_entries or ())
                or evidence.status in ("CANCELLED", "REJECTED")
                and evidence.order_id in (first.inventory.open_entries or ())):
            return blocked("ORDER_INVENTORY_CONFLICT")
    if pending is not None:
        evidence = latest.get(pending.target)
        if (evidence is None or resolution is None
                or ("OPEN" if evidence.status == "ACK" else evidence.status) != resolution.outcome.name):
            return blocked("PENDING_OUTCOME_UNPROVEN")
    step = transition(state, Event(state.sequence + 1, first.inventory))
    if not step.state.trusted:
        return blocked(step.reason)
    return Result("PASS", step.reason, step.state)


def main():
    from dataclasses import replace
    from datetime import date
    from .demo_safety_mock import Signal
    state = transition(State(), Event(1, Signal.CONNECT)).state
    state = transition(state, Event(2, Signal.RECONCILE)).state
    request = state.reconciliation
    view = Inventory(request, request.cutoff, 1, True, (), (), (),
                     date(2000, 1, 1), Decimal("100"), Decimal("100"))
    page = Page(view, "ONE_WAY", 0, None, None, ())
    cutoff = request.cutoff
    scenarios = {
        "complete": ((page,), (), cutoff),
        "duplicate_page": ((page, page), (), cutoff),
        "missing_page": ((replace(page, next_token="next"),), (), cutoff),
        "missing_event": ((page,), (), cutoff + 1),
        "cross_snapshot": ((replace(page, inventory=replace(view, request=replace(request, fixture_id="other"))),), (), cutoff),
    }
    output = {}
    for name, (pages, events, through) in scenarios.items():
        result = normalize(state, pages, events, watermark=cutoff, through=through, max_pages=2, max_rows=4)
        output[name] = {"verdict": result.verdict, "reason": result.reason}
    print(json.dumps(output, sort_keys=True))


if __name__ == "__main__":
    main()
