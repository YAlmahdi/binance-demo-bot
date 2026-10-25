# Project Control Dashboard — Data Integration & Refresh Contract

Status: **PROPOSED DESIGN ONLY — NOT IMPLEMENTED — NOT APPROVED FOR INTEGRATION**.
Design date: 2026-10-20 (Asia/Damascus). This document authorizes no executable workflow.

Publication clarification (2026-10-25): the mock-only prototype is implemented; the real-project integration and refresh described here remain PROPOSED and UNIMPLEMENTED. The repository is intentionally PUBLIC. This migration approval covers reviewed source/documentation publication only, not data access, evidence disclosure, a live dashboard, automatic refresh or research/execution integration. The original design-task restrictions and baseline observations below are historical context, not a current publication prohibition.

## 1. Scope, baseline and compatibility

The future dashboard explains bot development and evidence, through an offline, read-only display. The original design task delivered only this document, kept existing status/prototype files unchanged and prohibited publication for that task. No automatic refresh is enabled.

Local inspection found branch `main`, HEAD `0864a6665480f4a9498aaa143507aa010836aef0`, and the same cached `refs/remotes/origin/main`. These are local observations, **not independent remote verification**. The index had no staged changes; 54 existing modified/deleted/untracked file entries included status, policy, source/tests and the six prototype files. Their contents and attribution must not be bundled into future dashboard publication. Network operations were prohibited in that design task, so its remote-main SHA and visibility were UNVERIFIED. Git metadata is available in this task; the earlier review's missing metadata is historical context only.

Reviewed inputs: root `AGENTS.md`, local `docs/PROJECT_STATUS.md`, and `project_control/prototype/{index.html,styles.css,mock-data.js,app.js,verify.cjs,README.md}`. Status contains newer task sections and older summaries: for example, the old V2 phase row says proposed-only while newer sections document synthetic engineering. Do not resolve this by selecting the last line or newest-looking heading. Explicit scope and supersession evidence are required; unresolved overlaps are contradictions.

The current UI accepts **schemaVersion 3, mock: true only**; mock identifiers, fictional timestamps, one active milestone and a mock decision are enforced. Its README and verifier describe fixture behavior, not a production data interface. This proposal uses a distinct `contractVersion: "1.0"` envelope, never passed to the v3 renderer or silently substituted into `mock-data.js`. Integration will need a separately approved adapter, renderer validation and visible data-mode change. The five-section order and six health categories remain the presentation target. An idle or blocked real project need not have one active milestone.

## 2. Architecture and trust boundaries

```text
Explicit task approval + exact source allowlist + reviewed annotations
        |
Approved Sources (local, immutable capture)
        -> Validation (syntax, identity, authority, consistency, bounds)
        -> Structured Snapshot (inert JSON, immutable generation)
        -> Dashboard (read-only renderer, no source access)

Independent publication receipt -> permitted local evidence input only
Refresh attempt outcome -> generation manifest -> visible freshness warning
```

The future local transformer may read only approved documentation and permitted metadata. It may write only separately approved snapshot/attempt paths, never source documents or Git state. The browser reads a selected display bundle only: it cannot run Git, execute code from evidence, read arbitrary project files or initiate refresh. A local operator/task orchestrator is a separate trust boundary, with no permission inherited from displayed content.

Offline refresh cannot independently query GitHub. If separately authorized synchronization produces an independently verified receipt, refresh may consume its reviewed local projection. Otherwise publication is UNKNOWN or STALE. No API, hosting service, backend, database or remote font is needed for the display design. Local capture hashes detect byte changes; they do not establish authentic origin, correct science, complete history or authorization.

### Source authority hierarchy

| Priority / purpose | Permitted authority | Limits |
|---|---|---|
| 0 — boundaries | Explicit human task scope and applicable AGENTS restrictions | A document quotation or generated recommendation cannot grant approval; narrower restrictions prevail |
| 1 — project facts | Verified captured `docs/PROJECT_STATUS.md` sections | Retain exact source identity, scope and attribution; distinguish documented statements from independently reproduced evidence |
| 2 — milestone definitions | Exact separately approved roadmap/milestone documents | Proposal text defines proposed work only; no discovery crawl or implicit approval from a file's presence |
| 3 — source identity | Local HEAD, branch, index/worktree metadata; independent publication receipt | Git proves identities/state within its limits, not implementation quality or remote acceptance from cached refs |
| 4 — tests/task metadata | Explicitly permitted, reviewed test receipts and Codex task records | Reports are claims until checked against their tested source/environment; never automatic phase approval |
| Presentation | Human-authored Arabic annotations linked to fact IDs | No new metrics, verdicts, approval or inferred completion |

Hierarchy is domain-specific: status cannot override observed Git identity, and a test cannot override a safety prohibition. Conflicting authoritative records quarantine the affected claim; approval or security conflicts block the whole new generation. Status quoting a restricted report permits displaying its qualified statement only, not opening or hashing that report. Ignored reports, datasets, SQLite market databases, model artifacts and protected records are excluded by default and were not accessed for this design.

## 3. Proposed versioned display schema

The following is a field contract, not executable code or a completed JSON Schema. Unknown versions/keys, duplicate IDs, invalid references, unsupported enums and excessive nesting/size reject. All records have explicit typed fields; missing means `null` plus a reason where permitted, never an invented default success.

| Record | Required fields and meaning |
|---|---|
| Snapshot | `contractVersion`, `mode` (ILLUSTRATIVE or VERIFIED_LOCAL), `snapshotId`, `contentDigest`, `generatedAt`, `verifiedAt`, `validUntil`, `sourceSetDigest`, `policyVersion`, `project`, `git`, `sources[]`, `facts[]`, `health[]`, `milestones[]`, `current`, `latestTask`, `nextDecision`, `annotations[]`, `issues[]` |
| Project | `id`, English `name`, `environment: DEMO_ONLY`, `statusFactId`, `boundaryFactIds[]`; repository identity is configured/allowlisted, never derived from untrusted text |
| Source | `id`, `kind`, exact allowlisted relative `path` or sanitized local receipt ID, `locator` (section/line range/JSON pointer), SHA-256 `byteDigest`, `capturedAt`, `sourceEventAt` nullable, `commitSha` nullable, `worktreeState`, `verification`, `verifiedAt` nullable, `limitations[]` |
| Fact | `id`, `subjectId`, `predicate`, typed `value` nullable, `unit` nullable, `sourceRefs[]`, `verification`, `freshness`, `scope`, `observedAt` nullable, `verifiedAt` nullable, `validUntil` nullable, `limitations[]`, `conflictIds[]` |
| Health | Exactly one each: Engineering, AI/ML, Strategy, Financial Performance, Risk, GitHub/Publication; `category`, independent `stateFactId`, `builtFactIds[]`, `testedFactIds[]`, `missingFactIds[]`, `blockedFactIds[]`, `limitationFactIds[]`, `annotationIds[]` |
| Milestone / component / substep | Stable `id`, English `title`, explicit `order`, `kind`, `stateFactId`, `builtFactIds[]`, `testedFactIds[]`, `missingFactIds[]`, `blockedFactIds[]`, `nextFactIds[]`, `gateIds[]`, nested `components[]` / `substeps[]`, `annotationIds[]`; leaf records have no children |
| Gate | `id`, `type` (ENGINEERING, SCIENTIFIC, FINANCIAL, RISK, APPROVAL), `requirementFactId`, `stateFactId`, `evidenceFactIds[]`; no computed authorization |
| Current | `milestoneId` nullable, `selectionFactId`, `buildingFactIds[]`, `unresolvedFactIds[]`, `completionGateIds[]`, `limitations[]`; no unique verified active milestone means null, never choose by array order |
| Latest task | Nullable if unavailable; otherwise `id`, `title`, `statusFactId`, `completedAt` nullable, `changeFactIds[]`, `testFactIds[]`, `limitationFactIds[]`, impact fact IDs for the five nonpublication health dimensions, `sourceCommitShas[]`; one task's results never inherited by another |
| Next decision | Exactly one object: `id`, `title`, `status: PROPOSED`, `scope`, `basisFactIds[]`, `requiredApprovalRef` nullable, `annotationIds[]`; never an approve button or execution trigger |
| Annotation | `id`, `lang: ar`, `dir: rtl`, `text`, `factIds[]`, `authorRef`, `reviewState`, `reviewedSourceSetDigest`; human-authored explanation isolated from typed facts |
| Issue | `id`, `code`, `severity`, `affectedIds[]`, `sourceRefs[]`, `detectedAt`, `details`; preserve missing/stale/conflicting/unpublished conditions |
| Git | `localHeadSha`, `branch`, `captureAt`, `worktreeState`, `indexState`, approved-path content identities, `cachedRemoteSha` nullable, and separate `publication` record |
| Publication | `state`, `verifiedRemoteSha` nullable, `taskCommitSha` nullable, `verifiedAt` nullable, `receiptRef` nullable, `coveredPathDigests[]`, `limitations[]`; exclude credential-bearing remote URLs |

### State and validation semantics

- Evidence `verification`: VERIFIED (checked for the exact stated predicate), REPORTED (attributed statement), UNVERIFIED, MISSING, CONTRADICTORY. VERIFIED that status contains a sentence is not VERIFIED that its tests ran. Claims of executed tests require an approved matching receipt; otherwise retain REPORTED and historical attribution.
- Independent `freshness`: CURRENT, STALE, UNKNOWN. Published location and evidence quality are separate axes. A verified historical fact remains historical; it does not become a current result merely because a file was recently edited.
- Milestone states: PROPOSED, IMPLEMENTED, TESTED, COMPLETE, BLOCKED, UNKNOWN. COMPLETE requires evidence for its explicit engineering completion gates; approval/scientific/risk gates remain independent. No aggregate percentage or averaging across dimensions.
- Test fact values include outcome PASS/FAIL/SKIP/NOT_RUN, counts, command ID, tested source digest/commit plus dirty-path digests, environment identity, receipt reference and actual execution time. Unknown counts/times are null, never zero or generation time. No test is executed by refresh.
- Model facts separate implementation, fitting, evaluation and activation states. UNTRAINED cannot map to ACTIVE; fitted inactive development models cannot map to active or approved. Predictive and economic metrics require permitted exact receipts, units, sample sizes, period, costs, scope and limitations. Absent evidence displays Not Evaluated or Unverified, never a fabricated zero.
- All positive completion/test/performance claims and negative blockers require traceable fact/source references. Missing evidence itself has a diagnostic reference to the configured requirement and capture attempt; it is not proof a capability is absent. Unknown approval never becomes APPROVED.
- UTC timestamps use strict RFC 3339 `Z`, valid calendar dates and explicit precision. Unknown event/approval/F/C/A/Q times remain null. Date-only source dates stay date-only metadata, never fabricated midnight instants. Generation, capture, verification, event and publication times are distinct. SHA fields require full algorithm-tagged Git object IDs; source-byte digests use SHA-256 separately.
- Exactly one next-decision proposal is displayed. If sources offer several incompatible candidates or none is verified, the sole proposal is a human review of the ambiguity, referencing the issue. Never silently select or advance a phase. No unique current milestone or latest task yields an explicit Unknown field and issue, not fixture substitution.
- Annotations cannot change facts. Only reviewed annotations matching the source-set digest display as current explanations. On changed basis, omit the annotation or label it outdated; show the facts and a fixed neutral Arabic fallback. English headings/statuses/paths/SHAs stay LTR; Arabic context is RTL.

### Illustrative example records — not project evidence

These two valid JSON fragments illustrate record shapes only. They are not a complete snapshot, cannot pass full envelope validation, and must never be loaded as VERIFIED_LOCAL. Example IDs reference hypothetical records, not actual files or tests. Null values deliberately avoid invented times, metrics, approvals and Git SHAs.

```json
{
  "id": "illustrative-model-state",
  "subjectId": "illustrative-model",
  "predicate": "fittingState",
  "value": "UNTRAINED",
  "unit": null,
  "sourceRefs": ["illustrative-reviewed-source"],
  "verification": "REPORTED",
  "freshness": "UNKNOWN",
  "scope": "ILLUSTRATIVE ONLY; no real model inspected",
  "observedAt": null,
  "verifiedAt": null,
  "validUntil": null,
  "limitations": ["Not activation or predictive evidence"],
  "conflictIds": []
}
```

```json
{
  "id": "illustrative-explanation",
  "lang": "ar",
  "dir": "rtl",
  "text": "هذا مثال توضيحي: وجود واجهة للنموذج لا يعني أنه تدرّب أو أصبح جاهزًا للتشغيل.",
  "factIds": ["illustrative-model-state"],
  "authorRef": "illustrative-human-author",
  "reviewState": "DRAFT",
  "reviewedSourceSetDigest": null
}
```

DRAFT annotations are not eligible for current production display. VERIFIED_LOCAL describes local verification scope, not blanket verification of every fact in an envelope.

## 4. Source-to-field mapping

| Display field | Input / extraction rule | Failure behavior |
|---|---|---|
| Identity and boundaries | Configured project ID plus captured AGENTS/status sections | Identity mismatch or weaker safety restriction blocks promotion |
| Health | Scoped status claims + explicitly permitted exact evidence | Preserve each independent state; reported tests never become predictive/financial/risk PASS |
| Roadmap and gates | Approved document IDs/sections with explicit scope and supersession mapping | Unclear completion or contradiction quarantines claim; no invented steps/statuses |
| Current milestone | Explicit current selection supported by approved source | None/multiple -> Unknown and one review proposal |
| Latest verified Codex update | Approved task ID, actual permitted change receipts, matching tests and limitations | File modification date or Git log alone cannot establish latest completed task or authorship |
| Next decision | Explicit scoped recommendation; no approval inference | Conflict -> single review-of-conflict proposal, never execution |
| Last Verified Update | Actual coherent capture/validation receipt time | Not file mtime, event time, generatedAt or historical test date |
| Source SHA | Local captured HEAD plus source-set digest/dirty status | HEAD alone cannot identify uncommitted source bytes |
| Local / Published state | Local metadata plus independent authorized publication receipt | Cached origin/main, commit or attempted push never maps to PUSHED |
| Arabic explanations | Reviewed annotation fact bindings | Missing/outdated explanation uses neutral fallback; never generates facts |

Approved parsing uses a reviewed section/field map and exact bounded locators. Free-form Markdown, reordered sections and superseded prose require human reconciliation when mapping is ambiguous; keyword searches or an LLM summary cannot certify authority. The source registry is an allowlist, not a set of links to follow.

## 5. Safe refresh lifecycle and failure handling

All steps below describe a future implementation requiring separate approval. Explicit post-task trigger: only an authorized task-completion hook may request refresh after its final evidence/status handoff is settled, supplying task ID, exact permitted sources and expected HEAD/source digests. A completed Codex message, filesystem event or successful test alone is not a trigger authorization. No background watcher, timer, automatic retry, Git operation or approval action is enabled by this document.

Proposed bounds per attempt: 32 source files, 2 MiB per input, 16 MiB total input, 8 MiB snapshot, 10,000 total records, 64 milestones, nesting depth 8, 3,000 Unicode code points per prose field, 256 references per record, and 30 seconds total wall time. Exceeding any bound fails without truncation. These are engineering resource proposals, never financial or scientific thresholds. Limits/configuration are versioned; changing them requires review.

1. **IDLE -> CAPTURING:** obtain an exclusive local refresh lease, one writer and zero automatic retries. Reject active writer/expired lease ambiguity; no deleting another writer's lease. Resolve exact canonical paths under the approved root and reject traversal, symlinks/junctions/reparse escapes and disallowed types before opening. Never recursively scan/hash the repository, follow report links or query databases. Read local Git metadata only through fixed read-only operations, suppressing external diff/filter hooks and unsafe configuration execution.
2. **CAPTURING -> VALIDATING:** capture bytes and permitted identity metadata once; validate UTF-8, duplicate JSON keys, types, bounds, source scope and locators. Record HEAD/index/worktree state before and after, and recheck only approved source-byte identities. Dirty but stable sources are allowed as VERIFIED_LOCAL / UNCOMMITTED with their byte digests; dirty is not synonymous with invalid. A different HEAD, changed permitted source/index state, or producer still writing yields CONCURRENT_CHANGE and stops. Pre/post hashing alone cannot prove multi-file atomicity or defeat ABA changes: all cooperating source writers must honor a shared lease or supply an immutable coherent handoff. Without either, mark capture UNVERIFIED and do not promote a current verified snapshot.
3. **VALIDATING -> PREPARED:** validate references, scope, chronology, gates, publication coverage and annotations. Required identity/authority/security/structural conflicts reject the entire candidate. Missing optional task/test/publication evidence may produce null/REPORTED/UNKNOWN fields with issues; this is a degraded yet internally valid snapshot. Contradictory optional claims are quarantined, never arbitrarily chosen. Reconcile current/decision semantics before serialization.
4. **PREPARED -> COMMITTED:** serialize inert canonical UTF-8 JSON with deterministic key ordering, stable explicit record order, no nonfinite numbers or duplicate keys. Compute contentDigest/snapshotId from the semantic payload excluding those two self-referential fields and attempt-envelope clock values; identical captured sources, policy, annotations and evaluation clock produce identical payload bytes. Write a new immutable generation in the same filesystem, flush, reread and validate its digest/schema. No partially written generation becomes visible.
5. **COMMITTED -> CURRENT / DEGRADED:** atomically replace one small manifest selecting the immutable generation and recording last attempt outcome. Check expected previous manifest digest under the lease (compare-and-swap); reject competing replacement. Snapshot bytes and last-success metadata are never updated separately. Unsupported atomic replacement, interrupted writes or disk failure preserve the old selection and return FAILED. Release only the writer's own lease.
6. **Any failure -> FAILED / STALE:** preserve the last-known-good generation unchanged; record a separate bounded failure outcome via atomic manifest update when possible. A failed generation never overwrites or merges with known-good facts. With no valid prior generation, show Unavailable and diagnostics; never use mock fixtures as fallback. No source/status/Git recovery occurs.

| Display state | Required behavior |
|---|---|
| CURRENT | Valid generation, within approved freshness interval, no known changed source identity; verification scope visible |
| DEGRADED | Structurally valid capture, optional evidence missing/stale/reported; affected cards show qualifiers |
| REFRESHING | Prior generation remains explicitly historical while authorized capture runs |
| STALE | Expired validity, failed/changed source, interrupted attempt, or unknown currentness; persistent warning above all sections |
| UNAVAILABLE | No validated known-good generation; clear dynamic claims and show failure reason |

Freshness interval is an unresolved approval parameter. Until configured, currentness is UNKNOWN and no green/current badge is allowed. `validUntil` must not exceed any required evidence expiry. Clock rollback, unknown time or future verification timestamps invalidate currentness. Browser reload never renews evidence dates. A failed write may prevent even a failure banner update; therefore the viewer always shows verifiedAt, expiry, last recorded attempt and a warning that source changes/failed writes after capture may be undetected. There is no promise of live freshness without an authorized refresh channel.

For `file://`, the initial future transport proposal is a user-selected local JSON bundle loaded as inert data; no fetch or generated executable JavaScript wrapper. Include manifest, selected generation and last-attempt metadata in one bounded import, validate the whole bundle before rendering, and require user reload/reselection to view a new generation. Durable generation/manifest paths, Windows atomic-replacement guarantees and bundle export details must be approved and tested before implementation. Automatic post-task generation would still not imply automatic browser reload.

## 6. Publication and local evidence rules

Maintain independent local states CLEAN, UNCOMMITTED, LOCAL_COMMIT, UNKNOWN and publication states VERIFIED_PUBLISHED, UNPUBLISHED, UNKNOWN, STALE. Stable uncommitted facts can be locally verified; a published old version never covers changed local bytes. A local commit proves neither pushed state nor testing of that commit. Cached remote refs remain explicitly cached.

VERIFIED_PUBLISHED requires an authorized independent receipt binding repository identity, verified PUBLIC visibility, branch, full remote/task SHAs, verification time, exact covered paths/content identities and confirmation the remote contains that task commit. Refresh consumes only that receipt; it does not fetch, push or authenticate. Failed push and unconfirmed transport outcome retain their distinction; uncertainty stays UNKNOWN. UNPUBLISHED requires positive evidence of nonpublication for the relevant identity, not merely absence of a receipt. Receipt expiry or later local changes invalidate current publication coverage. Public upload of private project evidence is prohibited.

Every displayed fact retains its own location/provenance. A GitHub-published document containing a reported result does not transform it into independently verified performance. No staging, commit, push, branch change, reset, recovery, authentication or remote reconfiguration is part of refresh. Future normal publication remains governed by the repository policy and explicit task restrictions.

## 7. Security, scientific and rendering invariants

- No credentials/secret stores or secret environment reads, external APIs, Binance requests, market-data loading, fitting/training, predictions, backtesting, evaluation or order execution. No production mode, operational controls or automatic approval/phase advancement.
- No protected V1 reads or content hashes: selection-validation `[2026-08-31T00:00:00Z,2026-09-15T00:00:00Z)` and final `[2026-09-15T00:00:00Z,2026-10-09T06:50:00Z)`. Date metadata may be quoted from approved policy only.
- Preserve distinct V2/HYBRID exploration and strict prospective reference; historical exploration is not prospective confirmation. Actual F/C/A/Q remain PENDING, never backdated. BTCUSDT/ETHUSDT are the only active V2 research symbols. SOLUSDT/BNBUSDT/XRPUSDT stay inactive DATA ONLY with quality/funding review PENDING / BLOCKING BEFORE EXPANSION.
- Frozen strategy/cost/risk rules, five funding-reserve findings and **RISK NOT CLEARED** persist. Dashboard verification supplies no predictive, financial or safety clearance. Current status also reports external trust gaps / AUTHORITY SELECTION BLOCKED / M8 NOT READY; display those as attributed status, not independently validated external facts or an M8 implementation permission.
- Treat all source text as untrusted data: textContent only, no HTML/Markdown execution, scripts, event handlers, dynamic imports, unsafe URLs or source-supplied navigation. Preserve restrictive CSP and no network/persistence behavior in the renderer. Remove control/bidi spoofing in technical identifiers by rejecting disallowed characters; retain legitimate Arabic text and explicit RTL/LTR isolation.
- Do not import trading/research packages to extract status. Snapshot/receipt content must be sanitized and approved before local display; do not expose credentials, private account details, raw reports, database paths or dataset contents. Display evidence locators as text or fixed approved navigation only. References never grant access to excluded sources.

## 8. Future test plan and acceptance criteria

These are proposed tests, **NOT RUN by this documentation task**. Use synthetic isolated fixtures only, with no protected data, research pipeline, account/network access or package execution from source text.

| Area | Required acceptance evidence |
|---|---|
| Schema | Reject unknown version/fields, duplicate keys/IDs, dangling references, oversized/deep inputs, invalid dates/SHAs/nonfinite metrics; illustrative mode cannot enter verified display |
| Authority | Reported tests remain REPORTED; stale/superseded Markdown and contradictory approvals cannot certify current facts; no gate inferred from PASS/commit |
| Dimensions | Engineering PASS leaves AI/financial/risk independent; UNTRAINED never ACTIVE; missing metric stays null; no invented percentage/time/approval |
| Selection | Zero/multiple active milestones and ambiguous latest tasks show Unknown; exactly one scoped next proposal, no execution |
| Concurrency | Stable dirty sources supported; changing HEAD/index/source, lease collision, ABA/coherence uncertainty, CAS race and interrupted writer prevent promotion |
| Atomicity | Crash/disk-full before/after each commit boundary leaves either prior valid generation or complete new generation; corrupt newest snapshot falls back only to explicitly historical known-good |
| Freshness | Expired/missing receipt, failed refresh, clock rollback, unknown TTL and offline browser show persistent qualifiers; reload cannot reset verifiedAt |
| Publication | Cached origin/main, local commit, push attempt and old published bytes never yield current PUSHED; exact receipt/path coverage needed |
| Security | Path traversal/junction/symlink, oversized text, malicious Markdown/HTML/URLs, bidi identifiers and source instruction injection remain blocked/inert; forbidden reads/network/writes observed as zero |
| Determinism | Fixed captured bytes/config/clock produce identical canonical payload and digest; task, source and policy changes invalidate relevant annotations/receipts |
| UI compatibility | Separate adapter handles real versus mock mode; five sections/six dimensions, English LTR and Arabic RTL, nested disclosures and warnings remain readable; file import validates before rendering |

Release acceptance requires every mandatory gate to PASS with retained permitted receipts and exact source identities, independent design/security review, explicit file allowlist and separate implementation approval. A fail-closed refresh may PASS a negative test while the displayed project remains BLOCKED. No software test in this plan is predictive or financial validation.

## 9. Open questions and limitations

1. Which exact milestone sections, test receipts and task records may be read? Who verifies their authority, scope and supersession? None beyond this task's reviewed inputs is implicitly approved.
2. Who owns the reviewed structured mapping/Arabic annotations and provides a coherent immutable post-task handoff when multiple tasks edit status? Free-form historical status cannot be safely fully automated without this agreement.
3. What freshness interval, receipt expiry, local clock assumptions and source-capture coordination policy should be approved? No arbitrary dates or currentness are asserted meanwhile.
4. Which exact generation/manifest/bundle paths, retention limits, stale-warning behavior and manual file-import UX should implementation use? Static `file://` cannot detect all later source changes or refresh failures by itself.
5. What separately authorized process supplies independent PUBLIC-repository publication receipts without giving offline refresh network/credential access? Current cached remote SHA is insufficient.

This document does not independently reproduce status-reported engineering tests or external trust evidence. Existing prototype checks are historical; they are not evidence that this contract is implemented. Whole-repository byte preservation is not asserted: prohibited files are not opened/hashed, and unrelated concurrent writes may occur. Preservation verification is bounded to permitted reviewed files and Git metadata.

## 10. Minimal future implementation sequence — separate approval required

1. Review this contract and resolve exact source/mapping ownership, coherence, freshness and output-path questions. This is the single recommended next approval decision; it grants no implementation.
2. Only after a new explicit scope: implement bounded schema/validator and synthetic receipts/tests with a precise file allowlist; keep prototype mock mode unchanged.
3. Separately approve local source capture and atomic snapshot/manifest generation against the exact reviewed sources; test concurrency/failure handling without research data or network.
4. Separately approve the inert file-import adapter and UI mode/freshness changes, then focused offline/browser verification. Approve any post-task hook separately after the manual path is validated; no scheduler or hook exists now.

STOP after separately authorized work. This proposal itself authorizes no integration, automatic refresh, publication, research or new project phase. `docs/PROJECT_STATUS.md` intentionally remains untouched under this task's existing-file prohibition.
