# Research V2 — inert synthetic loader boundary

2026-10-12. **IMPLEMENTED / TESTED: synthetic diagnostics only.**
Real Historical Loader: **NOT IMPLEMENTED / BLOCKED**. **RISK NOT CLEARED**.

## Implemented API and scope

`src/demo_futures/research_v2/loader_boundary.py` defines immutable
`BoundaryRequest`, `SymbolDiagnostics` and `BoundaryDiagnostics` objects,
`validate_request`, `required_coverage` and `assess_boundary`.

Requests declare a symbol tuple, 5m interval, exact half-open UTC context bounds,
hourly decision candle close, source/scope/revision identities and an explicit
availability mode. Only BTCUSDT/ETHUSDT within
`[2026-05-03T00:00:00Z, 2026-08-31T00:00:00Z)` are accepted. Wrong symbols,
duplicate symbols, unsupported types, malformed/grid-invalid dates, protected
overlap and non-synthetic evidence are rejected. No source is opened.

The full context interval, including the caller-declared prefix and any supplied
future context, produces one `CoverageRequirement(symbol, start, end)` per
requested symbol in fixed BTC/ETH order. Inventory is independent of funding
observations. This narrow API requires one complete cell per symbol. It refuses
partial cells, duplicate/overlapping cells, partitioned substitutes and undeclared
symbols; it does not merge intervals or infer an eight-hour settlement cadence.
It does not define financial charge rules, construct label horizons or assemble
research opportunities. Existing 48-bar financial rules remain unchanged.

## Integration and evidence boundaries

Only raw, typed invented source metadata, funding claims and `SyntheticSeries`
are accepted. Existing validators are called again; precomputed `ContractResult`
or `FundingAssessment` objects cannot replace those inputs. Source/scope/revision,
decision and mode must match the request. Funding must match its full bounds and
source/revision. The series fixture identity must match the declared synthetic
source identity; this is internal fixture binding, not historical authentication.

`SUFFICIENT` means internally consistent synthetic contracts only. Even explicit
no-settlement coverage and internally valid strict receipt assertions remain
unauthenticated. `historical_evidence` is always `UNAUTHENTICATED / NOT VERIFIED`;
`authority` is always `INERT_VALIDATION_ONLY`. There is no real-evidence adapter.
The original supplied availability/receipt values are preserved as synthetic
claims; a `VERIFIED` enum is not authenticated market evidence. Approximation
keeps UNKNOWN, rejects unsupported/late verified claims, and cannot bypass
`ObservedCandle` availability checks.

Results contain only validation reasons, coverage requirements and per-symbol
diagnostics/flags/receipt metadata. They contain no candles, event/rate/mark
payloads, feature values, file paths/handles, queries, financial labels,
datasets, callbacks or activation flags. Constructors refuse payload/mutable
members. Implicit truth testing raises `TypeError` to prevent treating the result
as permission. These ordinary Python types are **not an OS security sandbox**;
future callers must not convert diagnostics into access or research authority.

## Quality and prefix preservation

The first supplied candle must match the declared prefix start. A truncated
suffix is rejected before quality/ATR calculation; it cannot silently establish
a different seed. Full-context endpoints and in-scope timestamps are checked.
The existing quality/causality validator remains unchanged, including its exact
200-bar warm-up, full-prefix ATR seed, gap refusal and documentary >5% flags.
No repairs, filters, imputation, clipping or reseeding are added.

Whole-context validation and causal diagnostics remain separate. A future anomaly
can invalidate the whole-context diagnostic without changing the earlier causal
result. The aggregate diagnostic must never be used as an earlier opportunity
admission rule or a financial-label gate. No such consumer is implemented.

## Executed verification

`scripts/verify_v2_loader_boundary.py` uses the existing audit guard and recording
result class. A new runner was necessary because existing runners have fixed
suite selections that do not include boundary tests. It blocks network/database/
external workers, credential/protected paths and writes outside new evidence;
it reads project source instead of local bytecode caches.

Final run: **111 passed, 0 failures/errors/skips**: 40 new boundary tests,
43 existing contract tests, 4 V2 configuration, 11 V2 feature, 2 V2 safety and
11 indicator/strategy tests. Initial run: 109/109 passed; two adversarial tests
and diagnostic-constructor checks were then added after review. No failing runs.
Financial-label/portfolio suites and the full unrelated suite were not executed.
Zero blocked runtime network/database/worker events were recorded. No saved
market inputs were used. This is software evidence, not real funding proof.

Local evidence: `reports/research-v2/V2-LOADER-BOUNDARY-SYNTHETIC-20261012T183729Z/report.md`,
test receipts, source baseline, verification and manifest. Reports remain ignored.

## Proposed, unresolved and blocked

Independent historical evidence authentication, real receipts/approximation
bridges, source isolation, the real ATR prefix convention, no-settlement financial
adapter and funding/market-realism completeness remain unresolved and unapproved.
Real loader/SQL/data ingestion, financial labels on saved markets, fitting,
predictions, backtests and execution remain **BLOCKED / NOT IMPLEMENTED** here.
AI/strategy/financial performance: **NOT EVALUATED**. Five reserve findings and
frozen financial rules remain adverse/unchanged; F/C/A/Q PENDING. SOL/BNB/XRP
remain inactive DATA ONLY. This milestone grants no new phase or data access.
