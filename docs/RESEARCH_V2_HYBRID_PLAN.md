# Research V2 HYBRID calendar and data-contract addendum

Date: 2026-10-11. **PROPOSED / AWAITING REVIEW. Documentation only; no loader, preprocessing estimator, fit, collection or evaluation approval. Risk NOT CLEARED.**

Read with [original V2 proposal](RESEARCH_V2_PROPOSAL.md), [current status](PROJECT_STATUS.md), [V1 chronological boundaries](PHASE4A_RESEARCH_PROPOSAL.md), and [synthetic engineering evidence](../reports/research-v2/V2-ENGINEERING-SYNTHETIC-20261011T102835Z/report.md). The original V2 proposal is unchanged. Its older blanket implementation statements are superseded only by the recorded synthetic engineering milestone, not by this addendum.

HYBRID means research-informed historical exploration followed by genuinely prospective confirmation and a separately sealed final assessment. It sacrifices the strict reference design's prospective development evidence; it is not an equivalent 180-day experiment. BTCUSDT/ETHUSDT only. SOLUSDT/BNBUSDT/XRPUSDT remain inactive DATA ONLY, with quality/funding review **PENDING / BLOCKING BEFORE EXPANSION**.

## Authorized historical target and missing-prefix DATA ONLY — 2026-10-11

The user selected the exact historical exploratory TARGET **[2026-05-03T00:00:00Z,2026-08-31T00:00:00Z)**, 120 days / 34,560 expected 5m bars per symbol. This supersedes target-choice pending language below ONLY; scientific design/fold construction is not approved.

This task's authorized collection was limited to **[2026-05-03T00:00:00Z,2026-07-11T06:50:00Z)**: 19,954 expected bars per symbol. Result: COMPLETE candle grids; funding quality INSUFFICIENT; BTC 19954 candles/206 available funding events; ETH 19954/206. Evidence: ../reports/historical-candidate-data-only/BTCETH-PREFIX-DATA-ONLY-20261011T131112Z-5645c40e/report.md and audit.json; separate new-only artifact snapshot, no active research input changes.

The later [2026-07-11T06:50:00Z,2026-08-31T00:00:00Z) segment remains documented context ONLY: not opened, copied, regenerated or joined. A future logical 120-day dataset must pass a separately approved continuity, junction, quality, funding and provenance audit before use. New-prefix candle completion does not establish financial funding completeness or whole-target quality.

Historical folds/data loading for research/financial labels/training/fitting/backtesting/scoring remain NOT APPROVED. Old locked periods remain excluded; this retrospective inventory is never prospective evidence. Original V2 proposal, reference alternative, financial/sample/economic gates and prospective conditional date rules unchanged. SOL/BNB/XRP gate stays PENDING / BLOCKING BEFORE EXPANSION; risk NOT CLEARED.

## A. Historical-data eligibility

All intervals below are UTC, start-inclusive/end-exclusive. These are documentary facts, not freshly inspected datasets.

| Documented BTC/ETH period | Evidence classification and V2 access |
|---|---|
| [2026-07-11T06:50:00Z, 2026-10-09T06:50:00Z) | Existing 90-day snapshot, 25,920 5m candles and 268 funding records per symbol according to prior documents. Baseline research already inspected the full period; not independent confirmation. |
| [2026-07-11T06:50:00Z, 2026-08-31T00:00:00Z) | V1 development, previously used for engineering, fitting and diagnosis. Candidate exploratory-only V2 envelope, subject to separate loader/fitting approval; 14,606 bars and 151 funding records per symbol documented. |
| [2026-08-31T00:00:00Z, 2026-09-15T00:00:00Z) | V1 locked selection-validation: PROTECTED, excluded from V2 reads, labels, preprocessing, fitting and assessment. |
| [2026-09-15T00:00:00Z, 2026-10-09T06:50:00Z) | V1 ML-reserved final: PROTECTED, likewise excluded. Prior baseline inspection does not unlock these ML outcomes or make their market period fresh. |

Documented provenance references: data/research-90d.sqlite3; engineering snapshot/config/provenance/splits/manifests for engineering-65fb33dd258060c94ffd, described in PHASE4A_ENGINEERING.md. These references identify evidence; none of those payloads or database contents was opened here. Counts alone do not establish financial quality or funding completeness.

**Historical fitting calendar: PENDING.** The candidate envelope lasts 50 days 17 hours 10 minutes, shorter than even the original first V2 training window of 60 days. It cannot implement the original three 60/80/100-day expanding training folds with 20-day evaluations across 120 development days.

Missing prerequisites: an explicitly authorized immutable BTC/ETH snapshot identity and expected hash; permitted intervals and inspection/provenance ledger for any additional history; documented continuous coverage and funding-evidence availability; receipt/prefix conventions; and a preregistered historical fold calendar. Existing documentation identifies the development envelope, not a suitable longer authorized V2 snapshot. No unseen history is assumed available.

Recommendation: retain the envelope for a later approved loader/quality audit. To fit, separately establish suitable longer Demo historical development coverage excluding protected dates, or submit a distinct shorter exploratory pilot calendar for review. Do not copy V1's shorter folds implicitly, lower sample gates, slide boundaries or substitute production data. Newly downloaded past events remain historical, even if previously unopened.

## B. Proposed hybrid UTC calendar

The known envelope above is the only defensible historical boundary today. Historical train/evaluation subdivisions remain PENDING; no scientific success claim may depend on inventing them.

The following future calendar is **CONDITIONAL**, expressed exactly relative to events not yet authorized or recorded:

- F: actual UTC timestamp of the complete post-exploration freeze, including code/config, feature/scaler recipe, model artifact, cost/risk assumptions, gates, calendar and analysis plan. No parameter/model selection follows F.
- C: actual UTC timestamp at which separately approved prospective observation recording begins.
- A = next strictly later 5-minute UTC boundary after max(F,C). Register F/C/A before the first qualifying observation. A is the accumulation start, not a backdated historical date.
- Q = first UTC midnight strictly later than max(A + 16h40m, F + 4h). The 16h40m reserves 200 five-minute warm-up bars; it does not prove their receipt or quality.

| Stage | Exact proposed interval | Current status |
|---|---|---|
| Historical exploratory envelope | [2026-07-11T06:50:00Z, 2026-08-31T00:00:00Z) | Research-informed candidate only; loading/folds/fitting NOT approved |
| Prospective accumulation | Begins A; observation events and original receipts must follow the documented freeze/collection events | Actual F/C/A PENDING |
| Independent confirmation | [Q, Q + 30 UTC days) | CONDITIONAL; actual dates PENDING |
| Separate sealed final | [Q + 30 UTC days, Q + 60 UTC days) | CONDITIONAL; actual dates PENDING; no opening approval |

Register the resolved dates before confirmation starts. Counts/quality may later return INSUFFICIENT, but cannot move Q retrospectively. No absolute prospective date is asserted in this document. If recording or freeze cannot meet the registered calendar, preserve the failed attempt and request a new future calendar before replacement observations; no automatic rolling windows.

Only events after A, recorded prospectively with original receipt/version evidence, qualify. Subsequent historical retrieval cannot replace missing prospective receipts. Archive confirmation/final observations without exposing outcomes, derived features, labels, predictions or performance to model selection. The final can accumulate while confirmation is reviewed, but remains sealed. Collector quality checks must be preregistered, isolated from research selection and logged. Unavoidable inspection/revisions must be disclosed; affected evidence cannot be called untouched without qualification.

At hourly boundary T use the bar closing at T-1ms, enter no earlier than T, and reserve [T,T+4h) even for early exits. Training labels must end by evaluation start B minus another four hours: T+4h <= B-4h. This is an eight-hour entry-to-boundary separation, not merely four hours between decisions. Evaluation labels must end within their own window; use a common known four-hour end-of-window entry cutoff for every compared portfolio. Confirmation is never training for final: the model/statistics stay frozen, and full horizons prevent cross-window label overlap. Earlier prices may provide causal warm-up under approved access, not fitting outcomes.

Keep BTC/ETH and both action alternatives at each hourly timestamp in the same partition; never shuffle symbols/actions across folds. Earlier exploratory evaluation rows may enter a later expanding training fold only after maturity and the same buffer. This forward-only design has no future training side; adding two-sided validation needs a separate embargo design. Overlap within periods still requires joint four-hour group counts and paired UTC-day uncertainty.

**Strict reference retained:** 180 genuinely prospective days after a complete recipe/calendar freeze: development [A,A+120d), confirmation [A+120d,A+150d), final [A+150d,A+180d). Development train lengths 60/80/100d, followed respectively by 20d evaluations, remain the original alternative. Prospective warm-up and exclusions reduce eligible rows. A in that alternative is registered independently; switching designs requires approval.

**Differences:** HYBRID replaces prospective development with authorized historical exploration and uses the conditional Q calendar; no equivalence claim. Historical folds are unresolved. No sample/economic/risk gates are reduced: 1,000 paired training rows/300 per symbol; 300 evaluation rows/100 per symbol/60 joint nonoverlapping four-hour groups, also on the in-range subset. Predictive MAE/MSE, uncertainty, 50 trades/10 entry days, positive net versus cash/baseline, PF >=1.1, DD <=10%, positive doubled-cost net and top-three concentration rules remain as proposed originally. Inadequate counts mean INSUFFICIENT. Any shorter pilot or gate difference requires explicit approval before outcomes are inspected.

## C. Preprocessing contract

Proposed estimator convention, not implemented or fitted here. Use exactly the ordered nine V2 inputs: three log returns, return volatility, relative ATR/range/body/volume, then ETH flag. For each fold, S is precisely the finite, financially valid paired training row set after fixed partitioning, full-horizon maturity, purging and buffer. Pool BTC/ETH; each symbol-decision counts once, not once per action. Freeze row IDs/order/hash, feature schema, counts and UTC bounds.

For continuous feature j, with n = size(S):
- mean[j] = sum(x[i,j])/n.
- scale[j] = sqrt(sum((x[i,j]-mean[j])^2)/n): population standard deviation, not n-1.
- L[j] = min(x[i,j]); U[j] = max(x[i,j]).
- z[j] = (x[j]-mean[j])/scale[j]; ETH flag passes unchanged.

Specify deterministic row order and stable finite two-pass accumulation in the later estimator; reject overflow/nonfinite statistics. Empty/insufficient S is INSUFFICIENT, never a fallback scaler. For an exact constant L=U=c, store mean=c and scale=1, yielding training z=0; accept evaluation only at exactly c. Any differing raw value abstains. A zero computed variance with L<U is numerical FAIL, not a constant. Invalid/nonfinite admitted rows/statistics or a flag outside {0,1} fail closed; causal invalid rows are separately excluded and counted. No imputation, padding, tolerance, clipping, dropped features or evaluation-derived repair.

No development-evaluation/confirmation/final row contributes to statistics. In expanding exploration each new fold rebuilds from its own S. The later final model's eligible historical training set and cutoff must be separately preregistered and frozen; confirmation never updates them. This construction contract extends the existing supplied-statistics synthetic interface; it does not claim that an estimator exists.

Raw values strictly outside [L,U] abstain; equality is accepted. Audit total scheduled rows, causal exclusions, eligible denominator, per-feature breaches and jointly abstaining rows by fold/symbol and seven-day blocks anchored at evaluation start, including the last partial block. Future-label invalidity never shrinks the denominator. Greater than 25% overall, for either symbol, or within a symbol/block with >=50 eligible rows is INSUFFICIENT; smaller blocks are TOO_SMALL. Preserve in-range sample minima and separate all-valid versus in-range prediction diagnostics. New regimes limit training support; they are not automatic evidence of success/failure. No tuning bounds after outcomes.

## D. Real-data and funding contract

Future loader engineering is a separate approval:
1. Pin authorized Demo-only source, immutable snapshot/manifest/config hashes, permitted date predicates, symbol/interval/schema, public provenance and inspection ledger. Read-only/query-only access; mismatch aborts without repair. Keep locked periods outside queries and horizon/warm-up reads. Hash scope/access to a file also containing protected rows must be explicitly approved; a hash is not permission to interpret them.
2. Validate timestamp grid, strict ordering, duplicates, completed close times, finite OHLCV, price/volume consistency and contiguous prefixes. Preserve anomalous raw rows. No sorting/filling to conceal gaps. Use the frozen ATR seed over the declared prefix; never silently reseed after a gap. Real prefix initialization/recovery remains a loader-review decision.
3. Require all 48 completed outcome bars after next-open entry, not just bars up to an early exit. Require separately established funding coverage over that full reserved horizon. Outcome maturity is later than decision time; neither enters features.
4. Build a public settlement inventory from defensible schedule/event evidence and required rate/notional/mark inputs. Do not assume perpetual eight-hour cadence or fabricate absent settlements, timestamp repairs or mark prices. Funding context absent, uncertain gaps or missing required marks yield UNKNOWN/exclusion, not zero. A verified no-settlement interval still needs coverage evidence and an approved adapter convention; the current empty-context adapter remains fail-closed.
5. Retain signed funding: positive rates debit LONG and credit SHORT, negative rates reverse that. Preserve the frozen conservative uncertain-entry/exit timing rule (charge possible debits; credit only when exposure timing supports receipt), fees/slippage and rounding. Actual settlement cost is charged once; the sizing reserve is not a second charge. Required marks must be supported, not invented to satisfy the simulator.
6. Unknown funding invalidates exact paired labels/scoring with a reason and missingness/selection-bias report. At inference use only causal eligibility, never later label validity. Keep admitted trades if later inputs are unknown: preserve known costs and mark common-window economic comparison INSUFFICIENT when any compared exposure crosses unresolved funding. No ex-post deletion or window selection. Cash's zero cost cannot make uncertain trading results a PASS.

Historical event timestamps do not establish original availability. Retrieval receipts prove when the current copy arrived, not when a historical trader saw it. Without original as-of receipts, historical closed-candle features/fills are explicitly approximations. Prospective features require actual availability by T; data arriving after T cannot support a next-open-T decision. Receipt lateness causes abstention under the current interface. A different latency/entry convention requires separate review, not invented receipt timestamps or backdated availability.

The five known BTC funding-reserve findings remain uncapped negative outcomes: about 64.24–79.15 USDT losses versus a 50-USDT planned budget; funding 21.55–43.75 versus reserves 7.20–14.58. These are documentary prior findings, not newly reread trades. Complete reconciled overruns may be valid research labels but independently block risk clearance. Financial limits remain 0.5% planned risk, 2x leverage, 2% daily halt and one shared position; no Martingale. Isolated fresh-account labels do not establish shared-portfolio safety. Missing costs/counts produce INSUFFICIENT; arithmetic defects FAIL; sufficient adverse performance may FAIL. Risk remains NOT CLEARED regardless of prediction scores.

Unresolved: actual authorized snapshot/folds, independent settlement schedule/mark coverage, verified zero-settlement context, real prefix initialization and timely receipt/next-open feasibility. No real funding completeness is certified.

## E. Explicit approval gates

| Gate | Separate decision required | Still excluded |
|---|---|---|
| 1. Scientific design | Review this addendum, unresolved historical folds, scaler convention and conditional future calendar | No automatic data access or implementation |
| 2. Historical loader engineering | Exact BTC/ETH snapshot/access range, hash scope, funding/receipt/prefix contracts and offline tests | No fitting or protected reads |
| 3. Historical exploratory fitting/evaluation | Frozen historical folds, hard gates, training-only preprocessing, three-fit recipe/budget and reporting | No confirmation/final access; no tuning searches |
| 4. Prospective collection/freezing | Bounded public Demo collection, actual F/C/A/Q register, sealed archives and inspection controls | No implicit scoring/evaluation approval |
| 5a. Confirmation evaluation | One frozen evaluation after collection/engineering/development review | No refit or opening final |
| 5b. Final evaluation | Independent explicit opening approval after confirmation review | No deployment/execution authorization |

A recipe change after confirmation consumes that evidence and requires newly registered future confirmation/final dates. Do not reuse prior periods as fresh. Expansion quality/funding gate remains pending and cannot be cleared by this BTC/ETH proposal or synthetic tests.

## Documentation verification and next decision

Only this new plan and PROJECT_STATUS.md change. Lightweight checks cover documented dates/durations, disjoint protected intervals, conditional calendar arithmetic, original-proposal/source preservation, local document targets, retained status history and approval/risk wording. No software suite, data reads, labels, scaler/model fitting, simulations, network or credentials. Prior 70 synthetic test passes remain historical evidence only.

Next decision: review/approve or revise the HYBRID evidence classification, preprocessing/funding contracts and conditional calendar. Keep historical fitting dates PENDING until authorized suitable coverage and a specific fold calendar exist. Approving this document alone must not approve loader work, fitting or collection. Share this plan and PROJECT_STATUS.md for independent review. **STOP.**

## Superseding offline junction-audit evidence — 2026-10-12

This addendum supersedes ONLY older statements that the later development segment was unopened or whole-target candle coverage unaudited. Earlier plan/evidence is retained as history. Explicitly authorized offline quality audit completed over the selected [2026-05-03T00Z,2026-08-31T00Z) target; no collection, loader activation, scientific fold construction, features/labels/fitting or financial evaluation approval follows.

BTC/ETH each: 19,954 verified prefix + 14,606 date-scoped development candles = **34,560/34,560**, 69,120 total. Exact July 11 06:49:59.999 to 06:50 junction; common five-minute grid, zero missing/duplicates/unordered/invalid OHLCV. Logical in-memory join only; full combined market series not persisted. Basic structure PASS, realism concerns remain: 85 zero-volume/85 flat bars each; >5% ranges 5 BTC/36 ETH, max 9.2213%/12.0842%; raw observations unchanged.

Funding each: 206+151=357 events; no duplicates/overlaps, observed marks positive/present. June 14–15 24h and August 17 16h spacing gaps; 41 exact nominal-grid offsets (36 +1ms, one +2ms, four +4ms). Eight-hour comparison is diagnostic, not independent schedule proof. Unknown settlement coverage UNKNOWN/never zero; **independent funding completeness INSUFFICIENT**. Funding and historical receipt/mark/notional/realism limitations continue blocking financial labels/clearance. Five historical funding-reserve findings unchanged; risk NOT CLEARED.

Prefix 496 file hashes/122 public pages/244 receipts independently rechecked; Part B scoped row hashes verified, whole-file identity/old Demo receipts remain documentary. Retrieval/observed_at times are October, not historical as-of availability or prospective evidence. Exactly four fixed read-only symbol/5m-context/lower+upper date SELECTs end strictly before August 31; mode=ro/immutable/query_only, deny-default authorizer/guard. No adjacent protected candle, full database hash/integrity scan or sidecar write. SQLite semantic returned-row isolation is not a physical-page byte-isolation claim.

Evidence: ../reports/research-v2/V2-120D-JUNCTION-AUDIT-20261011T214115Z-8298663a/report.md, audit.json, query-plan.json, scoped-query-receipts.json, prefix-integrity.json, integrity.json, focused-tests.json. Final **40 focused offline tests passed**, initial fixture/replay errors retained and corrected in task-only helper/tests before actual DB reads. 85 existing content hashes/3,154 file metadata records unchanged; metadata is not fresh protected-payload proof. Only existing doc changes are this addendum and PROJECT_STATUS.md; original proposal/source/data/artifacts untouched.

Selected historical target remains research-informed, not prospective evidence. Historical folds/scaler/loader engineering or use, labels/fitting/evaluation still require separate approval. Old V1 locked selection-validation/final periods remain excluded. **F/C/A/Q actual dates PENDING and must not be backdated. BTC/ETH ONLY; SOL/BNB/XRP quality/funding review PENDING / BLOCKING BEFORE EXPANSION.** Next separately approvable step: review funding/realism and the fail-closed loader/receipt contract on paper, without automatically collecting data or building labels. **STOP.**

## Proposed fail-closed historical-loader clarifications — documentation only, 2026-10-12

Read the proposed contract review at ../reports/research-v2/V2-FUNDING-REALISM-LOADER-CONTRACT-20261011T220057Z-1f550805/report.md. It analyzes saved text evidence only. This addendum clarifies interfaces and pending decisions; it does not change the nine-input recipe, frozen simulator/cost/risk rules, existing eligibility, hard gates or chronology. No actual loader/financial targets/data access/engineering approval.

**Coverage vs readiness:** propose interval states KNOWN_EVENTS (independently complete/reconciled obligations and supported inputs), KNOWN_NO_SETTLEMENT (independent no-obligation evidence), or UNKNOWN with evidence/reasons. Aggregate financial readiness is INSUFFICIENT when required coverage remains unknown; malformed sources/arithmetic remain INVALID/FAIL. Empty enumeration, nominal eight-hour cadence or recorded marks do not prove independent completeness. Preserve exact rates/times; no rounding away jitter, zero-filling or invented settlements. Unknown full 48-bar coverage/required marks/timing excludes exact paired LONG/SHORT labels, never fabricates NO TRADE; later future validity must not gate causal admission. Keep full reconciled losses/risk flags; five reserve findings and risk NOT CLEARED unchanged.

**Verified empty coverage is not an active adapter bypass:** the existing synthetic adapter refuses empty context. Any later KNOWN_NO_SETTLEMENT support requires separate approval and evidence-aware tests. No zero-funding override or fabricated preceding settlement. Needed context must stay within authorized source dates.

**Availability bridge unresolved:** REQUIRE_VERIFIED_ASOF refuses absent/late original receipts. A separate EXPLORATORY_CLOSED_BAR_APPROXIMATION mode would require explicit design/adapter approval, preserve actual October receipts and original availability UNKNOWN, and disclose next-open/latency approximations. Neither is activated or silently selected. Never replace real receipt times with historical closes. Real prefix initialization/gap handling must preserve frozen ATR's contiguous-prefix seed, not automatic reseeding.

**Quality classification, no new filter:** basic invalid/gapped sources block dependent consumption; suspicious structurally valid observations remain preserved and flagged. Existing decision-bar zero-range/zero-volume and positive prior-volume checks are distinct from >5% descriptive range flags. Whether to retain flagged valid bars for limited exploration or hold financial research pending independent realism evidence remains an approval choice. No new thresholds, smoothed/repaired data or outcome-selected exclusions.

**Access/provenance proposed:** exact BTC/ETH-only [2026-05-03T00:00:00Z,2026-08-31T00:00:00Z) context, source identity/approved scoped hashes, source/event/actual receipt/availability basis, revision and inspection ledger, quality/funding evidence and deterministic reasons. Shared SQLite whole-file hashing/integrity or protected adjacent reads are not automatically permitted. Future access must be separately authorized and date/symbol/5m-context bounded; semantic row isolation is not physical-page isolation. No database/raw rows were opened here.

**Approval gate unchanged:** resolve evidence sufficiency, as-of mode, prefix initialization, verified-empty-context adapter and realism policy before proposing a historical fold calendar or loader engineering. No folds constructed, no sample/economic gates relaxed. Historical target is research-informed; strict prospective 180-day reference and HYBRID remain distinct. F/C/A/Q actual dates PENDING, no backdating; V1 locked selection-validation/final excluded. BTC/ETH only; SOL/BNB/XRP remain inactive DATA ONLY, quality/funding review PENDING / BLOCKING BEFORE EXPANSION. Risk NOT CLEARED. Next decision is review/approval or revision of this proposed contract, not implementation, collection or fitting. STOP.

