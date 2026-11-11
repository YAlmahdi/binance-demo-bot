# DEMO reconciliation and operator recovery rehearsal

## Invented protocol conformance command

Run `python -B -m demo_futures.demo_protocol_mock` with `PYTHONPATH=src`.
It emits deterministic JSON with a verdict and reason for complete, duplicate,
interrupted, missing-event and cross-snapshot fixtures.

The pure normalization boundary requires caller-declared finite page and row budgets,
an exact complete token chain, one bound inventory across all pages, unique position
identities and consistent declared ONE_WAY or HEDGE sides. Stream events must cover
every sequence from the declared watermark through the observation cutoff and share
the account version. Repeated acknowledgments at successive sequence numbers are
accepted. Missing fills and contradictory terminal confirmations block normalization.
Partial fills and cancellations with nonzero filled quantity remain BLOCKED.
Every blocked result records a STALE transition and retains pending actions and
safety latches. The boundary emits no action intentions.

Mode, quantity, freshness and watermarks are invented declarations. Actual exchange
schemas, pagination behavior, account authority and atomic snapshot/stream alignment
require independent verification before integration. This completes the planned
mock-conformance scope. Remaining work requires external authority, research access,
funding evidence and separately authorized operational integration.

This procedure exercises invented account and order evidence through the pure `demo_futures.demo_safety_mock` state machine. Its outputs are simulated intentions. Source authority, exchange acknowledgments and operating permissions require independent evidence before future integration.

## Run the rehearsal

From the repository root in PowerShell run

```powershell
$env:PYTHONPATH = 'src'
python -B -m demo_futures.demo_safety_mock
```

The trace includes an incomplete response, an emergency entry cancellation, a restart while closure is pending and a conflicting closure confirmation. One branch confirms a flat inventory while retaining the kill latch. The alternative branch retains exposure after an explicit rejection, accepts an operator HOLD, refuses another close attempt and records an out-of-order event.

## Reconcile a complete synthetic observation

1. Supply CONNECT and request RECONCILE. Read the typed `ReconciliationRequest` from the resulting state. It binds the fixture identity, exact journal cutoff, full state commitment, prior account-version watermark and pending action.
2. Supply one `Inventory` response echoing that exact request. Its `observed_through` must equal the requested cutoff. Its positive account version must exceed the persisted watermark. The `fresh` declaration is invented fixture evidence. A bound version is consumed even if its response is partial.
3. Provide complete tuples for open entries, positions and protective orders. Use empty tuples for an explicitly empty inventory. Missing tuples remain unresolved. IDs must be unique and consistent. Protective orders must name observed protected positions and agree with each position's protection status.
4. Supply the UTC day, daily opening equity and observed equity. The mock reuses the inclusive existing daily-loss rule and default shared-position cap. Same-day opening equity changes and backward days are refused. Partial evidence can add a daily halt and cannot release one.
5. Bind any pending outcome through `Resolution`. The request ID, outcome and resulting inventory must agree. Previously known entries or positions can disappear only through a matching explicit cancellation, fill or closure outcome. A response claiming CLOSED while retaining its target is conflicting.
6. Inspect `review_status`, `mode` and `reason`. A stale reply, missing outcome or conflicting observation leaves dependent actions blocked. Disconnects, restarts and partial acknowledgments invalidate outstanding reconciliation requests.

## Recover an invented restart snapshot

1. Pin `checkpoint(state)` separately in the fixture before supplying a snapshot. Retain that expected identity across the simulated interruption.
2. Supply `create_snapshot(state)` and the separately pinned checkpoint to `restore(snapshot, expected)`. Schema version 1 binds the fixture, record count and complete materialized state including the journal, pending action, account-version watermark and safety latches.
3. Restore replays the entire ordered journal internally, validates normalized fault records and verifies the resulting state commitment. Unsupported schemas, changed content, stale identities, gaps, duplicate journal entries and materialized state unsupported by its journal raise `ValueError`. A failed restore requires the operator to retain the halted session.
4. The returned restart step emits zero intentions, disconnects and invalidates current trust. Reconnect and obtain fresh complete evidence before considering recovery. Previously emitted events remain idempotent when replayed with their original identities.

A checkpoint provided by the same caller establishes declared internal consistency. Independent custody, authenticity, latest-checkpoint selection and protection against replacement require separate evidence. Snapshots are immutable in-memory values. Durable storage, serialization and operating-system recovery remain future integration work.

## Review and decide

| Review status | Required operator response |
|---|---|
| ACTION_UNRESOLVED | Retain the pending action and obtain its explicit outcome. |
| RECONCILIATION_REQUIRED | Obtain matching evidence. An integrity fault remains latched through restart. |
| REJECTED_SAFETY_ACTION | Retain exposure and the rejection. HOLD remains available. The same target and rejected safety action cannot be retried. |
| EXPOSURE_PRESENT | Account for open entries and protection before reducing exposure. |
| HALTED_FLAT | Review the cause and supply an explicit RESUME only after the daily latch permits it. |
| KILLED_FLAT | Retain the irreversible kill latch. |
| CLEAR | Fresh reconciliation is available, subject to the existing occupied-plus-pending cap. |

`OperatorDecision` echoes the accepted inventory's request and account version. HOLD can add an operator latch while an action is unresolved. Other decisions require connected, trusted state, a complete current inventory and zero pending actions or integrity faults.

After an explicit KILL, the operator may choose CANCEL_ENTRY for a known entry. Confirm the cancellation through another complete response before choosing CLOSE_POSITION for a known position. CLOSE_POSITION emits a reduce-only intention. Entry orders must be accounted for first. Protective order IDs cannot be targets of cancellation. A cancel/fill race requires an explicit FILLED outcome and the observed position before closure.

After a protective rejection, retain the operator hold and exposed position. The fixture can explicitly request KILL and rehearse emergency reduction after fresh reconciliation. A rejected emergency close preserves exposure. Empty subsequent inventories without a matching outcome cannot establish flatness. RESUME requires fresh flat evidence and an eligible daily state, and always refuses a kill latch.

## Blockers before exchange integration

- Independent account identity, observation timing and source authentication.
- A coherent complete account/order view, pagination coverage, order-version and event-stream ordering semantics.
- Verified protective-order, position-side, partial-fill and reduce-only mappings.
- Durable atomic checkpoint custody, crash consistency and authenticated operator decisions.
- Explicit authorization for any client adapter, account access or order operation.
- Independent operational and financial clearance.

AI, strategy and risk behavior UNCHANGED. Training NOT PERFORMED. Predictive and financial performance NOT EVALUATED. Five funding findings UNRESOLVED. Aggregate stress BLOCKED. M8 NOT READY. F/C/A/Q PENDING. RISK NOT CLEARED.
