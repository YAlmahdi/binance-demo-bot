# Research V2 synthetic contract hardening

2026-10-12. **IMPLEMENTED AND TESTED: inert synthetic validation only.**
Historical Loader: **NOT IMPLEMENTED / BLOCKED**. Risk: **NOT CLEARED**.

This milestone implements a narrow subset of the earlier documentary contract,
not the historical-loader API described there. The original proposal and HYBRID
plan retain their historical approval context. This guide records the newly
authorized software boundary; it grants no real-data access or research approval.

## Implemented interfaces

| Module under `src/demo_futures/research_v2/` | Implemented interface | Meaning |
|---|---|---|
| `contracts.py` | `ContractResult`, `Readiness`, `EvidenceIdentity` | Immutable, ordered rejection results and synthetic identity bindings |
| `funding_contracts.py` | `assess_funding(FundingClaim)` | Reconcile supplied exact event timestamps, signed Decimal rates, required marks and schedule assertions |
| `funding_contracts.py` | `aggregate_funding(assessments, required=...)` | Require an explicit complete inventory of declared symbol/interval assessments |
| `source_contracts.py` | `assess_source(SourceMetadata, SourceExpectation)` | Validate inert scope, date, source, revision, receipt and scoped-hash metadata |
| `quality_contracts.py` | `assess_candles(SyntheticSeries, decision_time)` | Preserve supplied synthetic observations/flags; report structure, causal eligibility and realism separately |

There is no file path, query, loader, hash computation over a market payload,
model, fit method, deployment pointer or trading entry point in these interfaces.
`ContractResult.authority` is always `INERT_VALIDATION_ONLY`.

## Funding coverage and readiness

Coverage has three values: `KNOWN_EVENTS`, `KNOWN_NO_SETTLEMENT`, `UNKNOWN`.
Readiness is independently `SUFFICIENT`, `INSUFFICIENT` or `INVALID`.
`SUFFICIENT` means internally sufficient **synthetic contract evidence only**.

Each non-unknown assertion requires a schedule with exact half-open interval,
symbol, completeness flag and a typed identity. Evidence binds a source ID,
revision, assertion purpose and `SYNTHETIC_ASSERTION` basis. Event timing/rate
and mark evidence have separate purposes. Missing evidence, expected events,
required marks or timing support cannot produce known coverage. Duplicates,
contradictory schedules, unsupported extra events and nonfinite values are invalid.

The expected timestamp tuple is supplied explicitly. No eight-hour cadence is
generated or inferred. Reported timestamps are not snapped, rates are not made
absolute, and original values are never rewritten. Coverage starts inclusively
and ends exclusively; these inventory boundaries are not financial charge rules.

The aggregate checks exact declared requirements, rejects duplicated assessments
and refuses omitted symbol/interval cells. It does not discover intervals,
merge a schedule, construct horizons or infer whole-dataset completeness.

An empty event enumeration without completeness evidence remains insufficient.
An internally valid, separately identified no-settlement assertion can validate
as `KNOWN_NO_SETTLEMENT`, but its result has no simulator context or override.
**The existing `labels.FundingCoverage` and `paired_outcome` are unchanged.**
Empty financial context still yields `FUNDING_CONTEXT_UNAVAILABLE`. An
evidence-aware financial adapter is **PROPOSED / NOT APPROVED**.

Synthetic identity checking cannot authenticate independent historical evidence,
prove its truth or verify a real rate/mark/schedule. Accepting real evidence and
establishing completeness remain separate scientific and access decisions.

## Availability and provenance

Only BTCUSDT/ETHUSDT, 5m, exact explicitly expected bounds within
`[2026-05-03T00:00:00Z, 2026-08-31T00:00:00Z)` are accepted. Overlap with locked
selection-validation `[2026-08-31,2026-09-15)` or final
`[2026-09-15,2026-10-09T06:50Z)` is rejected using constants alone. No market
source or protected payload is opened. Origins/routes are compared as metadata
strings to the public Demo candle source; no requests are made.

Source/scope identities, revisions, explicit evidence references, integer UTC
milliseconds and a supplied row-scoped SHA256 metadata object are required.
Hash metadata must match the exact source/revision/symbol/interval/bounds and
candle projection. Whole-database hash scope is refused. The digest is checked
for structure and binding, not recomputed or treated as permission or truth.

`REQUIRE_VERIFIED_ASOF` requires an original receipt at the decision boundary
with matching synthetic receipt evidence; unknown or late availability refuses
readiness. These are fictional receipt assertions, not verified historical facts.

`EXPLORATORY_CLOSED_BAR_APPROXIMATION` validates an explicitly identified
retrospective metadata interpretation. Actual retrieval fields are preserved;
original availability can remain `UNKNOWN`. Unsupported `VERIFIED` claims and
late verified-as-of claims are rejected even in approximation mode. A metadata
PASS never establishes original availability, next-open feasibility or permission
to read a source. `ObservedCandle` and its existing receipt checks are untouched.

The original availability of saved historical data remains UNKNOWN unless
independently established. No receipt was invented for any real observation.

## Candle quality and frozen prefix rules

Structure, causal eligibility and market realism are separate output channels.
Invalid OHLCV/types/grid or duplicates are invalid; discontinuities are
insufficient. Raw synthetic observations and source order are retained.

Zero-volume/flat bars and `(high-low)/close > 5%` receive documentary flags.
The >5% flag does **not** become an exclusion. Existing decision-bar zero
volume/range and positive prior-volume rules remain in the frozen feature code.
Future quality failures do not feed the earlier causal channel. No financial
validity or outcome-based entry filter is produced.

The causal channel delegates only to existing `feature_at` on the supplied
invented series. Tests establish 199-bar refusal versus exact 200-bar acceptance,
full contiguous-prefix ATR14 initialization and the frozen Wilder recurrence:
first true range is high-low; the first 14 ranges seed the mean; later ATR is
`(previous * 13 + true_range) / 14`. Even 200 valid bars after a gap do not
silently reseed the original supplied prefix. No gap repair or context fetching.

This verifies caller-declared synthetic prefix behavior, **not** the still
unresolved real historical prefix-start convention. Realism remains
`UNKNOWN / NOT CERTIFIED`: liquidity, spread, latency and executable fills are
not established by structurally valid candles.

## Tested, proposed and blocked

**TESTED:** focused validators and intentional rejections; unchanged V2 synthetic
foundation, frozen indicator/strategy fixtures and risk arithmetic. Final result:
113 passes, 0 failures/errors/skips; 43 new contract tests plus 70 regressions.
Exact IDs and all attempts are local verification evidence, not market data.

**PROPOSED / UNRESOLVED:** independent funding evidence acceptance, real receipt
and approximation bridge, no-settlement financial adapter, real prefix start,
realism policy, source isolation, historical folds and financial research.

**BLOCKED / UNIMPLEMENTED:** real historical loader/SQL/ingestion/dataset assembly,
real-data features/labels, fitting, scoring, financial evaluation and execution.
No new research was performed. Five historical reserve overruns remain adverse
prior evidence; strategy/cost/risk rules and RISK NOT CLEARED are unchanged.
F/C/A/Q remain PENDING. Expansion symbols remain inactive DATA ONLY.

Evidence: `reports/research-v2/V2-CONTRACT-HARDENING-20261012T013325Z/report.md`.
That directory is ignored and local only. The status and source/test/runner files
also remain unpublished because fresh Git remote verification failed (DNS).

Only after separate approval, verification can be repeated with the bundled
Python runtime and `-B scripts/verify_v2_contracts.py --report-directory` pointing
to a newly prepared versioned contract report folder. The runner blocks network,
database connections, credential/protected-file reads and fitted modules.
It is a task-scoped defense, not a general OS sandbox or research authorization.
