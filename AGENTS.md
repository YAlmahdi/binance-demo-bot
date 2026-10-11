# Futures AI Lab project instructions

Scope: this directory and its children. Use the latest verified `docs/PROJECT_STATUS.md` as the source of truth for implementation and approvals. Implemented components include Phase 1 Demo diagnostics/data, Phase 2 offline indicator research/backtesting, the saved development-only Phase 4A ML experiment, and a synthetic-only V2 engineering foundation. These do not establish a profitable model or authorize further work. No paper/Demo trading execution or model activation is enabled; the historical V2 loader and real-data V2 financial research remain unimplemented/unapproved. Backtests must remain offline and historical-only, without credential reads. Public Demo history collection is allowed only when explicitly requested, using the credential-free public_history client and its restricted GET routes. Do not use authenticated configuration/client code for research. Wait for explicit approval before advancing execution, data access, collection, ML fitting, evaluation or other project phases.

- Use Binance USD-M Futures Demo only. Never introduce production execution endpoints or a live mode. Preserve the client's phase-1 method/path allowlist.
- Before changing strategy, risk, ML or execution behavior, review existing code and report material safety issues. Do not advance phases merely because a skill exists.
- Never open `.env`, secret environment values, private keys or secret stores in agent tools. Never request, print, partially reveal or upload credentials. Use `.env.example` and dummy values. The local app can consume Demo credentials internally only for a user-requested diagnostic; this does not authorize trading.
- No trades or order API calls while creating/reviewing skills. No unsupervised online learning or ML promotion without untouched out-of-sample performance and risk validation.
- Keep training, evaluation, backtesting, paper simulation and Demo execution separate. Skills give instructions; they do not create a sandbox or enforce risk limits in runtime code.
- Preserve protected V1 selection-validation [2026-08-31T00:00:00Z,2026-09-15T00:00:00Z) and final [2026-09-15T00:00:00Z,2026-10-09T06:50:00Z) periods; no opening, hashing across protected contents, labels, predictions or outcome evaluation without explicit scoped approval.
- **RISK NOT CLEARED.** Preserve the five documented funding-reserve findings and frozen strategy/cost/risk rules. Software correctness, publication readiness and financial profitability are separate conclusions; passing tests or pushing code grants no financial clearance.
- BTCUSDT and ETHUSDT are the only current V2 research symbols. SOLUSDT, BNBUSDT and XRPUSDT remain inactive DATA ONLY; their quality/funding review is **PENDING / BLOCKING BEFORE EXPANSION**. No automatic symbol promotion or research expansion.
- Historical exploration is research-informed, not genuinely prospective confirmation. Preserve the distinct strict prospective reference and HYBRID design; actual F/C/A/Q dates remain PENDING and must not be backdated. No new fold calendar or research access is implied by Git synchronization.

Use the relevant project skill rather than all five for every task:

| Task | Skill file |
|---|---|
| Demo API and ingestion | `.agents/skills/binance-demo-api/SKILL.md` |
| Baseline signals and offline simulation | `.agents/skills/quant-backtesting/SKILL.md` |
| Feature causality, validation and model gates | `.agents/skills/ml-trading-research/SKILL.md` |
| Sizing, exposure, halts and kill switch | `.agents/skills/futures-risk-manager/SKILL.md` |
| Requested review / review before logic changes | `.agents/skills/trading-code-review/SKILL.md` |

Tests use Python's standard-library unittest. From this project root set `PYTHONPATH=src` and run `python -m unittest discover -s tests -v`. Network smoke tests require `RUN_DEMO_INTEGRATION=1`; do not enable them for documentation/skill-only edits.

## Standing project reporting policy

After every completed, failed, blocked, stopped, partial, or documentation-only development or research task:

1. Update `docs/PROJECT_STATUS.md` with the actual verified project state, changed files, test results, known limitations, and approved next steps, whenever an authorized and verified status change requires it.
2. Do not mark any feature completed unless its implementation and relevant tests exist.
3. Include a concise final summary describing what was changed and tested.
4. List any new reports or design documents the user should share for independent review.
5. Clearly distinguish implemented, tested, proposed, and unimplemented features.
6. Preserve all existing safety and approval restrictions.
7. Never include API keys, secrets, credentials, or sensitive account data in reports.

### ChatGPT review availability and local evidence

- GitHub is the primary review route for successfully committed and pushed project code/documentation. Codex cannot assume access to ChatGPT Project Sources, conversations, memory or ChatGPT's GitHub connector. Codex operates on local files and explicitly supplied materials.
- Local files are not automatically available to ChatGPT merely because Codex changed them. A confirmed push makes committed files available for GitHub-based review, subject to ChatGPT fetching them and having repository access.
- A GitHub push does not automatically refresh or replace separately uploaded ChatGPT Project Sources. Never claim automatic ChatGPT synchronization or successful publication from a local edit/stage/commit alone.
- Identify important ignored or unpublished research reports/design documents by their exact project-relative paths and actual publication state. References to an ignored report do not publish its contents. Do not call a read-only inspected file changed or claim an unperformed status update.
- If separate Project Sources copies are still in use, identify any relevant stale copies factually; do not categorically require manual re-upload of every changed tracked document. Older task reports retain their historical manual-upload instructions, not a competing mandatory footer.
- Never recommend uploading secrets, private account data, databases, raw datasets, model artifacts or complete research artifact directories. Safe local-only review materials require the user's chosen review route and any necessary explicit publication approval.
- Use exactly one mandatory final-report section: **GITHUB SYNC STATUS**, defined below. It replaces the old mandatory ChatGPT Project Sources update reminder; do not append both sections.

### Safety and approval boundaries

This reporting policy does not authorize additional project phases, historical data access, data collection, model fitting, training, predictions, backtesting, economic evaluation, protected-period access, Binance API requests, order execution, or trading.

All existing project safety restrictions and explicit approval requirements remain unchanged.

Reporting and Git synchronization grant no new development/research task, historical data access, Binance API operation, data collection, model training/fitting, backtesting/economic evaluation, protected-period access, order execution/trading, strategy promotion, research symbol or additional project phase. Git repository configuration, authentication, visibility and branch-setting changes also need separate explicit authorization.

## Conditional GitHub Auto-Sync Policy

### Standing authorization and per-task precedence

For FUTURE explicitly user-approved tasks, automatically commit and push approved, security-reviewed, task-related changes only after successful completion and all required gates below. Do not request separate Git publication approval for ordinary eligible files when these gates are satisfied. The sole authorized destination is the existing **PRIVATE `YAlmahdi/binance-demo-bot`**, branch **`main`**, through configured **`origin`**. This is standing Git synchronization authorization only, not authorization to begin another task or extend its scope.

A direct current-task restriction on writes, staging, commits, pushes, network or other publication prerequisites overrides this policy. **The initial 2026-10-12 policy setup task explicitly prohibits staging, committing and pushing: its AGENTS.md edit must remain local pending user review.** This dated exception does not prohibit later explicitly approved policy-file publication. A no-sync/read-only task or a task with no eligible changes is SKIPPED; do not create an empty commit. No remote/publication checks need be attempted when synchronization is intentionally excluded.

### Start-of-task snapshot and exact task scope

1. Inspect branch, remote configuration and working-tree/index state at task start using permitted read-only local Git commands. Record the starting HEAD, staged files, and pre-existing modified/untracked files. Redact credential-bearing remote information; never inspect secrets to perform these checks.
2. Do only the explicitly approved work. Afterward, identify exact task-created/modified/deleted/renamed paths and, where necessary, approved hunks. A file read or inspected is not a task change. Do not include unrelated user changes or silently publish pending changes/commits from another task.
3. Update `docs/PROJECT_STATUS.md` only when an authorized, verified state change actually requires it. If the current task makes status read-only or restricts modifications to other files, preserve it and report that limitation accurately; no fabricated or unnecessary status edits.
4. Run appropriate task-scoped verification. Documentation-only tasks may use documentation/Git checks instead of unrelated application tests. Required gates must PASS before publication; blocked, stopped, incomplete, partial or unsuccessfully verified work must not be published automatically.
5. Leave unrelated unstaged/untracked work untouched. Pre-existing staged entries block automatic publication; do not reset/unstage them. Pre-existing edits overlapping a selected path/hunk, dependent unpublished changes or uncertain attribution block publication unless the user explicitly authorizes that exact scope and it can be safely verified.

### Publication boundaries and content review

- Ordinary eligible changes may include reviewed task-related source, tests, scripts, docs, safe `research/dependencies/` documentation/manifests, and other explicitly approved source/configuration paths. Directory membership alone is not approval.
- **Protected policy files:** publication of `AGENTS.md` or `.gitignore` requires explicit task-specific approval of publication of those exact paths. Permission to edit a protected policy file is not automatically permission to publish it.
- Exclude real `.env`/environment variants, credentials, private keys/passwords/tokens/secret stores, private account data and sensitive personal information. `.env.example` is an exception only when explicitly task-related and reviewed to contain blank/dummy placeholders, never actual credentials.
- Exclude `data/`, `logs/`, `artifacts/`, `manual-public-metadata/`, research datasets, raw exchange responses, model weights/generated model artifacts, private databases, generated logs, local caches, virtual environments and wheel caches. Never upload complete research artifact directories.
- **`reports/` remains ignored by default.** A selected report may be considered only after explicit approval of its exact path and content review. If it remains ignored, leave it unpublished and list it as local review evidence. An ignore exception requires separately authorized `.gitignore` editing/publication and exact report approval; never silently change ignore rules or use `git add -f`.
- Review candidate changed content/diffs for secrets/sensitive URLs, private records, unsafe production/live additions, unintended data/models, generated/large outputs and unrelated modifications. Refuse credential/private-key paths without opening them; redact findings rather than exposing values. Reject unsafe links/path escapes or unexpected file types. Apply the same review to the staged snapshot.
- Stage only an explicit verified file-path allowlist. Never use unrestricted `git add .`, `git add -A`, directory-wide staging or force-add. Verify both staged names and staged content match the approved task scope, including rename/deletion sides. Any unexpected staged entry, unrelated hunk or unreviewed dependency blocks commit; do not repair the index automatically.

### Remote, commit and push gates

1. Before publication, verify current branch `main`, configured `origin` and its effective fetch/push destination, including overrides/URL rewrites, identify exactly `YAlmahdi/binance-demo-bot`. Confirm the repository is PRIVATE and current remote `main` state with safe read-only checks. GitHub/Git remote checks are permitted only for synchronization and only when the current task permits them; no Binance/external-data scope is granted. Do not read or expose credential values; approved Git clients may use existing authentication internally.
2. A local cached `origin/main`, the user's earlier privacy statement or a successful old push is not fresh remote/privacy verification. If required checks are unavailable, unauthenticated, ambiguous, stale or fail, BLOCK publication rather than guessing. Do not change remotes, authentication, branch settings or visibility to make checks pass.
3. Require a non-conflicted existing local/remote `main` baseline with starting local HEAD equal to freshly verified remote HEAD before creating this task's commit. An unborn/missing branch, ahead/behind/divergent history, unexpected remote change or existing unpublished commits blocks automatic synchronization. Never publish earlier commits merely because this task passed; request a specific user decision without taking recovery action.
4. After task/scope/security/staged/remote gates pass and eligible changes exist, create one focused commit containing exactly the approved staged snapshot and push it normally to `origin/main`. Verify the resulting commit's paths/content and that no unexpected hook-induced changes entered it. Stop on unexpected behavior; do not amend, reset or perform automatic recovery.
5. Never merge, rebase, force push, rewrite history, change branches or resolve conflicts automatically. A remote race must be handled by normal non-force push rejection, not overwriting remote work. Re-check state as necessary before the single push; no silent retries or follow-up repair task.
6. A successful local commit is not synchronization. Check the actual push exit/result and publication confirmation that remote `main` contains the task commit; do not infer success from local tracking refs alone. If confirmation is unavailable, report publication unconfirmed and BLOCKED, even if the command returned success. If the push was attempted and failed, report FAILED, the local task commit SHA/count and actual known publication state. When the commit remains unpublished, explicitly identify the local unpublished commit SHA. If a timeout/transport error leaves remote acceptance uncertain, report UNKNOWN/unconfirmed rather than inventing either acceptance or absence; any permitted read-only confirmation is not a push retry.
7. On commit/push/Git failure, report the precise redacted stage/reason and any remaining staged changes or unpublished local commit. Stop without destructive recovery or retry. A failure before push is BLOCKED; an attempted failed push is FAILED. No eligible changes means SKIPPED, not a fabricated success.
8. Count files from the actual task commit, not all working-tree changes. For a confirmed successful push, "Files pushed" means the number of reviewed task-changed file paths introduced by that commit, not a Git network-transfer statistic. A failed/unconfirmed push reports 0 confirmed pushed files and explains any uncertainty. Never count merely inspected, ignored or uncommitted paths as committed/pushed.

### Mandatory final GitHub synchronization report

At the end of **EVERY** final Codex task report, include exactly one clearly named final section: **GITHUB SYNC STATUS**. It applies to successful, failed, blocked, stopped, partial, read-only and documentation-only tasks, including tasks with no changes. Put all implementation details, tests, limitations, exactly one recommended logical next step and local-review explanations before it; no competing mandatory footer or text after the table. Do not begin or authorize that next step without the user's approval.

Use this table, replacing alternatives/placeholders with actual evidence:

| Field | Result |
|---|---|
| Status | SUCCESS / FAILED / BLOCKED / SKIPPED |
| Repository | YAlmahdi/binance-demo-bot |
| Branch | main |
| Task verification | PASS / FAIL / NOT RUN, with reason |
| Files committed | Actual count |
| Files pushed | Actual confirmed count |
| Commit SHA | Actual task commit SHA or N/A |
| Push result | Confirmed result or NOT ATTEMPTED |
| Failure / blocking reason | Actual redacted reason or None |
| Required next action | Specific action or None |
| Local review files | Relevant ignored/unpublished project-relative paths or None |

Repository and branch identify the intended publication target. If the actual inspected remote/branch differs, disclose that difference in the result/reason and BLOCK publication; never report target `main` as the actual branch when it is not.

- **SUCCESS:** push completed successfully and publication was confirmed; never use for a mere edit, stage or local commit.
- **FAILED:** a push was attempted but failed. Identify an unpublished local commit if one exists.
- **BLOCKED:** required authorization/security/task verification/Git or remote checks prevented or could not confirm publication; no uncertainty hidden.
- **SKIPPED:** no synchronization needed, or an explicit task restriction intentionally excludes it. Explain the restriction/no-change case.

For the initial 2026-10-12 setup task, report **SKIPPED**, 0 files committed, 0 files pushed, Commit SHA N/A and Push result NOT ATTEMPTED. Reason: **Policy setup task explicitly prohibits Git commit and push; AGENTS.md changes remain local pending user review.** Do not stage or publish this setup automatically after verification.
