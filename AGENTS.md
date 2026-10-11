# Futures AI Lab project instructions

Scope: this directory and its children. Current implementation includes Phase 1 Demo diagnostics/data and Phase 2 offline indicator research/backtesting. No paper/Demo execution or ML engine is enabled. Backtests must remain offline and historical-only, without credential reads. Public Demo history collection is allowed only when explicitly requested, using the credential-free public_history client and its restricted GET routes. Do not use authenticated configuration/client code for research. Wait for explicit approval before advancing to execution or ML.

- Use Binance USD-M Futures Demo only. Never introduce production execution endpoints or a live mode. Preserve the client's phase-1 method/path allowlist.
- Before changing strategy, risk, ML or execution behavior, review existing code and report material safety issues. Do not advance phases merely because a skill exists.
- Never open `.env`, secret environment values, private keys or secret stores in agent tools. Never request, print, partially reveal or upload credentials. Use `.env.example` and dummy values. The local app can consume Demo credentials internally only for a user-requested diagnostic; this does not authorize trading.
- No trades or order API calls while creating/reviewing skills. No unsupervised online learning or ML promotion without untouched out-of-sample performance and risk validation.
- Keep training, evaluation, backtesting, paper simulation and Demo execution separate. Skills give instructions; they do not create a sandbox or enforce risk limits in runtime code.

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

### Mandatory ChatGPT Project Sources update reminder

At the very end of EVERY final Codex task report, append a clearly visible Markdown section with the exact heading:

**CHATGPT PROJECT SOURCES UPDATE**

This section is mandatory for completed, failed, blocked, stopped, partial, and documentation-only tasks, including tasks where no project files were changed.

Track the following files:

- `AGENTS.md`
- `docs/PROJECT_STATUS.md`
- `docs/RESEARCH_V2_PROPOSAL.md`
- `docs/RESEARCH_V2_HYBRID_PLAN.md`

For each task:

1. Compare the actual verified changed-file list against the tracked files above.
2. If any tracked file was created or modified, display **UPDATE REQUIRED** in bold.
3. Under **FILES TO REFRESH**, list ONLY the tracked files actually created or modified, using their exact project-relative paths.
4. Under **REVIEW FILES TO UPLOAD**, list any new or materially updated reports, research documents, or design documents needed for independent ChatGPT review. Include exact project-relative paths.
5. If no tracked files changed and no important review files require uploading, display **NO UPDATE REQUIRED** in bold.
6. Never report a file as changed merely because it was read or inspected.
7. Never claim that ChatGPT Project Sources were automatically synchronized or updated. The user must manually refresh the relevant files.
8. Do not recommend uploading `.env` files, credentials, API keys, private account information, databases, raw datasets, model artifacts, or entire artifact directories.
9. If a task fails or stops before status documentation can be updated, report the actual state accurately. Never claim an unperformed update.
10. Keep this reminder as the FINAL section of every user-facing task report, after all implementation details, tests, limitations, and next-step recommendations.

Required output format when updates are needed:

**CHATGPT PROJECT SOURCES UPDATE**

**UPDATE REQUIRED**

**FILES TO REFRESH**
- `exact/project-relative/path`

**REVIEW FILES TO UPLOAD**
- `exact/project-relative/report/path`

Omit either file list when it has no entries.

Required output format when no updates are needed:

**CHATGPT PROJECT SOURCES UPDATE**

**NO UPDATE REQUIRED**

### Safety and approval boundaries

This reporting policy does not authorize additional project phases, historical data access, data collection, model fitting, training, predictions, backtesting, economic evaluation, protected-period access, Binance API requests, order execution, or trading.

All existing project safety restrictions and explicit approval requirements remain unchanged.

This policy changes reporting requirements only. It does not authorize phase advancement, ML implementation or training, trading execution, or exchange actions.
