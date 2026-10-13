# V2 synthetic authorization binding and fixed query declarations

2026-10-13. **IMPLEMENTED / SYNTHETICALLY TESTED. Actual independent authorization NOT VERIFIED. Real Historical Reader/Loader NOT IMPLEMENTED. RISK NOT CLEARED.**

## Interfaces and boundaries

`authorization_binding.py` introduces immutable, slotted, primitive-only `SyntheticApprovalRecord`, `AuthorizationDiagnostics` and `validate_authorization(record, spec, manifest, evaluated_at=...)`. Inputs are declarations only; no actual approval ledger is consulted. A separate argument is not proof of independent origin or user permission. Existing metadata diagnostics alone cannot substitute for this record.

The record ID must match the spec/manifest approval references. Exact source/snapshot/scope/revision, BTC/ETH symbols, 5m interval, projection, mode, schema/version, scoped digest declarations, provenance references and prefix/decision/horizon bounds must match. Existing metadata validation is rerun, including target/protected checks. Only explicit `SYNTHETIC_ASSERTION` bases are supported; absent/UNKNOWN assertions remain insufficient, unsupported real-authorization claims are invalid. No hash is computed or authenticated by either new module.

Validity is `[issued_at,expires_at)` at an explicit nonnegative integer UTC-millisecond evaluation time. There is no wall-clock lookup or automatic default. Not-yet-valid, expired and revoked records are refused. Revocation is an invented supplied state with an explicit reference; it is not a live revocation service. Revoked-without-evidence and nonrevoked-with-revocation-reference contradictions are rejected. This validity window describes synthetic record assessment, not an execution lease or financial exposure guarantee.

`fixed_query_plan.py` introduces `QueryPlanRequest`, `QueryPlanDiagnostics`, `build_query_plan(...)` and `validate_query_plan(...)`. Each build revalidates the original record/spec/manifest/time. Revalidation of an externally supplied plan rebuilds the canonical declaration and compares all fields; a previously passing plan is not reusable after expiry/revocation or changed inputs.

Outputs are diagnostics, a fixed SQL string and immutable per-symbol parameter tuples. They expose no database locator, connection, cursor, execution method, records or capabilities. Implicit truth testing raises. Constructors check immutable shape; validation functions check semantics and revalidate tampered fields. Python objects/private helpers are not a security sandbox or real authorization mechanism.

## Fixed SQL and resource contract

Only `main.fixture_candles`, fixed index `fixture_scope`, existing nine-column `source_contracts.PROJECTION`, metadata schema `V2_SYNTHETIC_CANDLE_METADATA` version 1, and ordering `(symbol,ordinal)` are declared. These are allowlisted synthetic identifiers, not verified real storage schema. No caller SQL, identifiers, predicate fragments, parameters, wildcard projection or alternate order is accepted.

One immutable parameter set is generated for each approved symbol, in canonical BTC/ETH order. Each uses the same SQL:

```sql
SELECT open_time,open,high,low,close,volume,close_time,quote_volume,trades
FROM main.fixture_candles INDEXED BY fixture_scope
WHERE symbol=? AND interval=?
  AND open_time>=? AND open_time<? AND close_time>=? AND close_time<?
ORDER BY symbol,ordinal LIMIT ?
```

Parameters per symbol are `(symbol,"5m",context_start,context_end,context_start,context_end,per_symbol_expected_rows+1)`. Separately symbol-bound declarations avoid inferring row identity from a joint result that lacks a symbol column. No SQL executes, including against temporary fixtures; parameter sets are not sent to any transport.

The plan binds `(context_start,context_end,prefix_start,prefix_end,start,end,horizon_end,decision_time)` explicitly. Metadata target is `[2026-05-03T00:00Z,2026-08-31T00:00Z)`; planning additionally retains strict-interior context bounds. The entire declared grid across all requested symbols must fit `expected_rows <= request.max_rows <= record.max_rows <= 4096`. Larger contexts are refused, not paginated, split, truncated or repaired. Each symbol declares one extra overflow-detection row, so at most two sentinel rows accompany the combined admitted-row ceiling; these do not increase the 4,096-row admission cap. Existing SQLite fixture restrictions remain untouched.

This is not a data-completeness proof: no rows, ordinals, source uniqueness, physical schema or query performance are verified. A later separately approved reader must reject missing/extra/duplicate/unordered rows, preserve source observations and enforce its own security. SQL predicates do not prove physical-page isolation. The plan does not select an ATR prefix or require a newly invented financial horizon; matching declarations never establish feature/label eligibility.

## Invented usage

Construct a record explicitly from independently supplied *invented* metadata matching the spec/manifest, with its own ledger reference, validity window, revocation state and row ceiling. Never create a production approval record automatically by copying untrusted snapshot fields.

```python
from demo_futures.research_v2.authorization_binding import validate_authorization
from demo_futures.research_v2.fixed_query_plan import (
    QueryPlanRequest, build_query_plan, validate_query_plan,
)

# invented_record/spec/manifest and invented_now_ms are caller-supplied declarations.
binding = validate_authorization(invented_record, invented_spec, invented_manifest,
                                 evaluated_at=invented_now_ms)
request = QueryPlanRequest(max_rows=1024)
plan = build_query_plan(invented_record, invented_spec, invented_manifest, request,
                        evaluated_at=invented_now_ms)
checked = validate_query_plan(plan, invented_record, invented_spec, invented_manifest,
                              request, evaluated_at=invented_now_ms)
# Inspect status/reasons explicitly. There is intentionally no execute() operation.
```

Complete invented record/spec/manifest construction is in `tests/test_v2_authorization_binding.py:inputs`; it creates no sources or SQL fixtures. The example above is an interface illustration with deliberately undefined invented inputs, not a runnable source loader.

## Verification evidence

Normal-sandbox guarded run 01: **234 passed**, 0 failures/errors/skips (68 new +166 existing regressions). Review separated symbol parameter sets to preserve identity with the nine-column projection and added two checks. The intervening test-collection attempt stopped on one SyntaxError in a new test; **zero tests executed**. Corrected only the test's assignment syntax; no rule, guard or permission weakening. The startup failure is preserved separately.

Final run 02: **236 passed**, 0 failures/errors/skips: 36 authorization +34 query tests, and 166 existing synthetic regressions (55 adapter metadata/integration, 40 boundary, 43 contracts, 4 configuration, 11 features, 2 safety, 11 indicators). New tests use invented metadata and mock/callback checks only. Existing regression observations are synthetic. No actual SQL, SQLite fixtures/connections, saved markets, funding investigation, models, financial evaluation, Binance, credentials or orders. Runtime blocked events: zero in both executed suites. Physical SQLite/filesystem tests were not selected.

Coverage includes exact binding, missing/expired/revoked/unknown declarations, unsupported bases, schema/provenance/hash/revision drift, both protected intervals, prefix/horizon escapes, resource ceilings, SQL/projection/order/parameter tampering, mutable/foreign objects, replay, deterministic reasons and failure isolation. UNKNOWN funding and strict unknown availability remain unresolved. Diagnostic objects cannot become SQLite requests or financial evidence.

Guarded runner: `scripts/verify_v2_authorization_query.py`, reusing the existing metadata-only runtime guard. Receipts, exact test IDs and source identities remain ignored locally under `reports/research-v2/V2-AUTHORIZATION-QUERY-20261013T012946Z/`. All 97 starting tracked file identities matched during both passing runs; final preservation excludes only this task's authorized status update. Pre-existing Risk Remediation and SQLite-blocked status text stays byte-exact locally and is not authorized for publication here.

## Unverified, proposed and blocked

**NOT VERIFIED:** actual approval authenticity/ledger independence/revocation, snapshot contents/digests/provenance/physical schema, historical as-of receipts, independent funding coverage, real ATR prefix, real links/races and SQLite physical-page isolation. Synthetic assertions do not authenticate history or establish source eligibility.

**PROPOSED / NOT IMPLEMENTED:** a separately approved real snapshot binder, reader, source-schema mapping and receipt/approximation bridge. No real adapter, dataset assembly, feature/financial consumption, model fitting/evaluation or trading activation. No synthetic result permits these operations.

**STOP conditions:** failed binding, malformed/ambiguous evidence, altered query, expired/revoked record, scope/resource violation or requirement for real source access stops dependent planning with no SQL output. Future real-data and financial gates remain separate. Five funding-reserve overruns, frozen strategy/cost/risk rules, protected V1 periods, inactive expansion symbols, F/C/A/Q PENDING and RISK NOT CLEARED unchanged. AI/strategy/financial performance is not changed or evaluated.

One next decision: independent review of these synthetic contracts before any separately approved real-source engineering. No automatic follow-up.
