# Research V2 — temporary SQLite access contract

2026-10-12. **IMPLEMENTED / TESTED: invented fixtures only.**
Real Historical Loader: **NOT IMPLEMENTED / BLOCKED**. **RISK NOT CLEARED**.

## What exists

`src/demo_futures/research_v2/sqlite_fixture_contract.py` adds immutable
`SQLiteFixtureRequest`, `FixtureSnapshot`, `FixtureToken` and `AccessDiagnostics`.
`inspect_fixture()` returns validation diagnostics only. It returns no candle
rows, dataset, SQL handle, feature values, financial labels, fitted object or
permission to perform another operation. Implicit truth testing is refused.

Test provisioning uses `temporary_fixture()` to create an empty file inside a
fresh system temporary directory with an explicit, identity-bound lifecycle.
There is no `TemporaryDirectory` finalizer, recursive deletion, permission reset,
retry or existing-directory adoption. The active owner token must be the exact
process-minted object, the file must be sealed, and filesystem identity must
match. There is no public existing-path adoption or database discovery interface.
Fixture creation is separate from read validation; successful diagnostics cannot
create an owner or activate a loader.

## Scope and SQLite defenses

Before connecting, the immutable request is checked against the existing inert
boundary and source contracts. Only BTCUSDT/ETHUSDT, 5m, synthetic evidence and
explicit source/scope/revision identities are accepted. This fixture contract
uses **strict interior** bounds: `2026-05-03T00:00:00Z < start < end <
2026-08-31T00:00:00Z`. Bounds are half-open and aligned to the 5m grid. The
additional 4,096-row cap is an engineering resource limit, not a scientific or
financial threshold. V1 protected periods and unsupported symbols are rejected.

The reader uses `mode=ro`, `query_only`, disabled extensions, an explicit snapshot
transaction and a deny-by-default SQLite authorizer. A separate exact SQL gate
binds the symbol tuple, interval, open/close time predicates, projection and row
limit. The authorizer restricts tables/columns/actions; it cannot validate a
WHERE clause by itself. No arbitrary SQL or connection is exposed by the public
diagnostic interface. Writes, ATTACH, extension loading, unexpected schema,
unscoped reads and altered query parameters are refused.

Only the declared schema/version, fixed projection and one matching identity
record are accepted. Canonical provenance binds the request and supplied source
metadata. SHA-256 covers the requested projection of selected rows, scope and
version; it never hashes the database file or protected decoy rows. A matching
digest proves internal fixture consistency, not historical authenticity.

## Ordering, causality and evidence

An explicit ordinal preserves supplied per-symbol observation order; timestamps
must already form the complete declared contiguous grid. There is no timestamp
sorting, gap repair, filtering, interpolation or post-gap ATR reseeding. The full
declared prefix reaches the existing unchanged boundary/quality validators.
Tests cover the exact 199/200-bar eligibility boundary and preserved anomaly flags.

Supplied receipt timestamps remain unchanged. Approximation-mode metadata keeps
original availability UNKNOWN and cannot bypass `ObservedCandle` causality.
Strict-mode unsupported availability claims are refused before connection.
Even internally valid synthetic receipt claims remain unauthenticated.

Fixtures contain no funding records or funding table. Successful access diagnostics
can be `SUFFICIENT` while the nested boundary remains `INSUFFICIENT` because
funding coverage is unproven. Neither status authorizes historical dataset
assembly, financial labels, training or execution.

## Verification and limits

The original `tests/test_v2_sqlite_fixtures.py` contained 29 focused tests. The guarded
`scripts/verify_v2_sqlite_fixtures.py` also selects 111 existing offline
boundary/contract/configuration/feature/safety/indicator regressions. Final run:
**Historical initial milestone: 140 passed; 0 failures, errors or skips**. All 36 directories created by that
run were removed. The initial sandbox run had 111 passes and 29 temporary-file
permission errors before any SQLite connection. Its empty-directory cleanup also
failed; later removal of those first-run directories has not been verified.
The same guarded tests then passed with reviewed filesystem permission; no guard
or calculation was weakened.

Local receipts and source identities:
`reports/research-v2/V2-SQLITE-FIXTURE-CONTRACT-20261012T192528Z/`.
The runner accepts only a separately prepared versioned evidence directory under
`reports/research-v2/`; it does not access existing databases.

Protected-date, symbol and interval decoys are invented. They prove row-level
query exclusion, **not physical-page isolation**: SQLite may read pages containing
other rows. Symlink/reparse rejection tests use synthetic filesystem metadata,
not real OS links. File-identity checks before/after a read do not certify safety
against a hostile concurrent filesystem swap. Python-private helpers, frozen
dataclasses and process registries are contracts, not an OS security sandbox.
Actual historical schemas, real funding completeness, original receipts,
liquidity/fills, scientific validity and financial performance are untested.

## Lifecycle remediation — 2026-10-13

**IMPLEMENTED / TESTED within the ordinary sandbox:** configured temporary-root
metadata is read without `tempfile.gettempdir()` write probes or fallback to
another environment. A fresh UUID name is attempted once. Windows uses ordinary
directory creation to inherit the parent sandbox access; no ACL is edited.
POSIX retains private creation mode. This is compatibility evidence for the
tested environment, not proof of every Windows ACL configuration or the exact
cause of older failures.

Leases are revoked before cleanup, including incomplete creation. Seal, audited
connection and reader failures expire access; known identity uncertainty also
blocks cleanup. Teardown accepts only the recorded exact fixture file and root,
checks identities, refuses unexpected entries and uses unlink/rmdir only.
If ownership cannot be established, paths are retained and failure is reported.
No finalizer later overrides that refusal. Ordinary immutable request/hash
rejections retain their prior validation behavior.

Primary and cleanup exceptions are preserved as separate members of an ordered
exception group when both occur; a sole failure remains the original exception.
Read/close diagnostic groups contain only safe category names, never exception
messages or handles. KeyboardInterrupt/SystemExit groups propagate after cleanup
instead of becoming successful or ordinary validation results.

One bounded creation/seal/removal preflight passed: one real new fixture root
removed, zero active leases and zero SQL connections. Both subsequent selected
runs passed **161/161**, zero failures/errors/skips: 50 fixture tests (21 newly
added) and 111 unchanged regressions. The second run followed addition of final
global lease-count evidence, not a failure or permission retry. Each suite made
37 real root-creation attempts and 11 virtual audit registrations; all real roots
were removed. Final active leases: zero. Controlled virtual permission/link/
identity tests create no actual filesystem paths. Earlier leftovers remain
untouched and their cleanup remains unverified.

Evidence: `reports/research-v2/V2-SQLITE-REMEDIATION-20261012T232509Z/report.md`
and matching preflight/test receipts. Source hashes cover allowed code only.
No real database, protected outcome, historical data or financial research was
accessed. Existing scoped SQL, read-only defenses, provenance, protected periods,
funding/causality rules and diagnostics-only authority remain unchanged.

Known limitations remain: mocked links do not certify real OS link handling;
pre/post identity checks cannot eliminate hostile concurrent swaps; row-level
SQLite predicates do not prove physical-page isolation. Parent ACL inheritance
is not a new confidentiality guarantee against other host processes. Historical
Loader readiness, five adverse reserve findings and RISK NOT CLEARED unchanged.

## Proposed, unresolved and blocked

A real-data adapter, historical source access, evidence-aware funding/receipt
bridge and financial research remain separately approvable future work. This
module does not activate the existing Historical Loader boundary. V1 artifacts,
strategy/cost/risk rules, five reserve findings and protected outcomes are
unchanged. BTC/ETH only; other symbols remain inactive DATA ONLY. F/C/A/Q dates
remain PENDING. Review this fixture contract before any further engineering
approval; no data access, fitting, simulation or phase advancement is implied.
