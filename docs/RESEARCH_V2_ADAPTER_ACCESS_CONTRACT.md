# V2 metadata-only adapter access contract

Date: 2026-10-13. **IMPLEMENTED / SYNTHETICALLY TESTED. Real Adapter NOT IMPLEMENTED. RISK NOT CLEARED.**

## Purpose and boundaries

`src/demo_futures/research_v2/adapter_access_contract.py` validates declarations about a proposed snapshot, without finding, opening, connecting to or hashing that snapshot. It imports compatible source-contract semantics; it contains no SQLite, filesystem, network or financial adapter. This is a separate metadata interface, not a change to existing V2 or V1 behavior.

Only BTCUSDT/ETHUSDT, 5m, within the half-open UTC target `[2026-05-03T00:00:00Z,2026-08-31T00:00:00Z)` are admitted. Target endpoints can bound metadata context; the existing SQLite fixture contract still requires strict-interior bounds and retains its 4,096-row resource cap. Passing this broader metadata check cannot relax those independent restrictions.

## Implemented interfaces

- `AdapterAccessSpec`: exact immutable primitive scope, source/revision/snapshot identities, symbols, interval, UTC millisecond bounds, projection, approval reference, prefix-basis reference, availability mode and expected per-symbol scoped digest declarations.
- `PinnedSnapshotManifest`: repeats the bound scope explicitly, adds exact schema/version, digest declarations, provenance assertion/reference/basis triples, approval basis, retrieval time and original availability/receipt metadata.
- `validate_adapter_access(spec, manifest)`: structured `AdapterDiagnostics` with existing `Readiness` and ordered rejection vocabulary. `SUFFICIENT` means internal invented metadata consistency only. `bool(diagnostics)` raises; outputs contain no rows, paths, SQL handles or permissions.

Constructors reject mutable containers, foreign scalar types, callbacks and capability objects. Constructors check shape; the validator checks semantic consistency and rechecks shape, including missing or tampered fields. Frozen slotted dataclasses reduce accidental mutation; Python objects are not security capabilities or an OS sandbox.

The schema identifier is exactly `V2_SYNTHETIC_CANDLE_METADATA`, version 1, with the existing nine-column `source_contracts.PROJECTION`. This declares a metadata schema; it does not assert a physical database schema or create a storage adapter. Hash algorithm must be `sha256`, scope `SYNTHETIC_ROWS_ONLY`, lowercase 64-hex digests, exactly one record per requested symbol in canonical BTC/ETH order. Expected and manifest declarations must match. Digests are not recomputed or authenticated.

All intervals are half-open. Declarations require:

```text
context_start = prefix_start < prefix_end = start < end
end <= horizon_end = context_end
prefix: [prefix_start,start)
decision window: [start,end)
declared horizon: [end,horizon_end)
```

Every bound is a nonnegative integer UTC millisecond timestamp on the 5m grid. The single declared decision receipt boundary is an hourly candle close inside the decision window. The whole context, prefix and horizon must stay within the target; protected V1 overlap is rejected independently. No ATR prefix start, prefix length or financial-label horizon is selected here. Even a one-bar prefix may be internally consistent metadata while unusable for features. The 200-bar floor is not sufficient proof of actual prefix initialization.

Provenance requires `SOURCE_IDENTITY`, `APPROVED_SYNTHETIC_SCOPE` and `PINNED_SNAPSHOT` references. Only `SYNTHETIC_ASSERTION` is supported as internally declared evidence; `UNKNOWN` or missing evidence is `INSUFFICIENT`. Unsupported claims, contradictory bindings and malformed identifiers are `INVALID`. An approval identifier and synthetic assertion do not verify a real approval ledger or grant access.

Retrieval timestamps are preserved. `EXPLORATORY_CLOSED_BAR_APPROXIMATION` with original availability `UNKNOWN` can pass metadata consistency; it cannot establish historical decision-time availability. `REQUIRE_VERIFIED_ASOF` remains available and returns `INSUFFICIENT` for unknown original receipts. Unsupported verified claims are rejected; supported but late synthetic receipts stay `INSUFFICIENT`. Even exact invented receipt assertions remain unauthenticated historically. No receipt values are manufactured.

## Invented usage example

This example constructs metadata only; the arbitrary prefix/horizon are not scientific conventions.

```python
from demo_futures.research_v2.adapter_access_contract import (
    AdapterAccessSpec, PinnedSnapshotManifest, PROVENANCE_ASSERTIONS,
    SCHEMA_ID, validate_adapter_access,
)
from demo_futures.research_v2.source_contracts import TARGET_START, PROJECTION

hour = 3_600_000
common = dict(
    scope_id="invented-scope", source_id="invented-source", revision="r1",
    snapshot_id="invented-snapshot", symbols=("BTCUSDT", "ETHUSDT"), interval="5m",
    start=TARGET_START + 18 * hour, end=TARGET_START + 20 * hour,
    context_start=TARGET_START, context_end=TARGET_START + 24 * hour,
    prefix_start=TARGET_START, prefix_end=TARGET_START + 18 * hour,
    horizon_end=TARGET_START + 24 * hour, decision_time=TARGET_START + 19 * hour - 1,
    projection=PROJECTION, approval_ref="invented-task-reference",
    prefix_basis_ref="invented-prefix-choice",
)
hashes = (("BTCUSDT", "a" * 64), ("ETHUSDT", "b" * 64))  # Invented, not computed.
spec = AdapterAccessSpec(**common, mode="EXPLORATORY_CLOSED_BAR_APPROXIMATION",
                         expected_scoped_sha256=hashes)
manifest = PinnedSnapshotManifest(
    **common, schema_id=SCHEMA_ID, schema_version=1, scoped_sha256=hashes,
    provenance_refs=tuple((a, "invented-" + a, "SYNTHETIC_ASSERTION")
                          for a in PROVENANCE_ASSERTIONS),
    approval_basis="SYNTHETIC_ASSERTION", retrieved_at=TARGET_START + 25 * hour,
    original_availability="UNKNOWN",
)
diagnostics = validate_adapter_access(spec, manifest)
print(diagnostics.status, diagnostics.reasons)  # Diagnostics only; never authorization.
```

## Verification performed

Guarded normal-sandbox run 01: **164 passed**, 0 failures/errors/skips. Code review then added missing-slot refusal and second-protected-period checks. Final run 02: **166 passed**, 0 failures/errors/skips: 55 new tests (44 metadata, 11 integration), plus 111 existing regressions (40 loader boundary, 43 source/funding/quality contracts, 4 configuration, 11 features, 2 safety, 11 indicators). No initial test failures. Both receipts remain local.

New integration uses invented identifiers, digests, references and empty quality contexts only. It does not create SQLite fixtures or market rows. Existing regression fixtures use invented observations to verify frozen causality, gaps and ATR behavior; no historical research is executed. SQLite integration tests inspect pure pre-connection rejection, fixed SQL declarations and authorizer callbacks without executing SQL or obtaining a lease. Physical SQLite/lifecycle tests were not selected.

Tests cover malformed UTC/type inputs, duplicates, inactive symbols, both protected periods, context/prefix/horizon escapes, schemas/projections/revisions/hashes, unknown and contradictory evidence, late receipts, mutable/foreign objects, deterministic diagnostics and attempted downstream authority. Successful diagnostics cannot replace source/quality evidence, a boundary request or a SQLite fixture request. UNKNOWN funding remains `INSUFFICIENT`; absent quality context does not become eligible.

Runner: `scripts/verify_v2_adapter_access_contract.py`; guarded against network, workers, SQLite connections, fixture creation/removal, secrets, saved markets, fitted artifacts and prior outcomes. Only a prepared versioned evidence directory accepts output. No blocked runtime events in either run. Scoped code/receipt hashes are evidence of file identity, not market authenticity.

Local review evidence: `reports/research-v2/V2-ADAPTER-ACCESS-CONTRACT-20261013T005428Z/`. Reports remain ignored and unpublished. The earlier unpublished `PROJECT_STATUS.md` insertion remains verbatim and outside this task's publication scope.

## Proposed, unresolved and blocked

**PROPOSED:** independently authorized real snapshot/access binding and evidence-aware source adapter, after review of this metadata contract. No adapter interface is activated automatically.

**UNVERIFIED:** real snapshot contents/schema/hash/authenticity, provenance ledger, original historical availability, independent funding completeness, real ATR prefix initialization, liquidity/fills and physical filesystem/page isolation. Runtime guard and frozen metadata are defense in depth, not OS-wide security proof. Real symlink/race behavior was not tested.

**BLOCKED / NOT IMPLEMENTED:** Real Historical Loader/Adapter, real data assembly, saved-market features/labels, financial consumption, model fitting/evaluation and trading activation. Metadata `SUFFICIENT` never creates research or financial readiness. Five historical funding-reserve findings remain adverse; financial rules, V1 locked periods, inactive DATA ONLY symbols and F/C/A/Q PENDING remain unchanged. AI, strategy and economic performance were not changed or evaluated. Stop for independent review; no phase advancement.
