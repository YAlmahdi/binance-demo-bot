---
name: trading-code-review
description: "Review changes to Futures AI Lab for Demo-only safety, secret handling, research leakage, risk controls, and execution correctness. Use for requested reviews or before a proposed trading-logic change; produce findings without enabling execution."
---

# Trading Code Review

## Purpose and use

Review existing behavior before strategy, risk, ML, or execution changes. Prefer concrete reproducible defects over generic checklists. A review request permits inspection and relevant offline tests, not automatically changing logic or running account actions.

## Safety rules

- Binance USD-M Futures Demo only. Any reachable production execution path or live-mode option is a blocking finding, even behind a flag.
- Never read `.env`, credential environment values, private keys, account screenshots, or secret stores. Never print, mask-and-reveal, upload, copy, or request secrets. Review config code and `.env.example` using dummy credentials. Exclude credential files from search/diff commands and reports.
- Do not run orders, `/order/test`, cancellations or close-outs while reviewing or setting up skills. Review execution paths statically and with mock transports.
- Training, evaluation, paper simulation and Demo execution must remain separate. No live trading, unsupervised self-modification, or promotion of a model without independent out-of-sample performance and risk evidence.

## Review workflow

1. Establish the actual scope and baseline: inspect relevant tracked and untracked source files, callers and tests. This project may still be uncommitted; an empty git diff does not mean there is no code. Do not include credential files when enumerating content.
2. Trace network reachability and credential flow. Check exact Demo origin on every request, TLS, redirects/proxies, endpoint allowlists, expired verification, response parsing and error/log redaction. Skills are instructions, not an operating-system sandbox; report enforcement gaps honestly.
3. Trace decision-to-order state: closed-data timing, reason logging, persistent client IDs, ambiguous POST outcomes, reconciliation after restart, duplicate prevention and protective-exit handling. Distinguish the current phase-1 prohibition from future planned execution features.
4. Trace research causality: warm-up, as-of joins, fold boundaries, label horizons, preprocessing fit scopes, cost-aware fill simulation, immutable model versions and promotion records. Flag training metrics passed off as out-of-sample evidence.
5. Check 0.5% sizing, 2x/Isolated defaults, 2% daily entry halt, finite position caps, cost/margin/precision handling, no Martingale, and persistent kill-switch state when these features enter scope. Do not mark a documented future feature as implemented.
6. Run only tests proportionate to the change, offline with dummy credentials. Explain missing coverage and the trigger/consequence of each defect. Do not expand into unrelated refactors or fix code until fixes are requested or already authorized.

## Required tests and evidence

For affected paths, require tests of blocked production origins, secret-safe logging, one-attempt POST and reconciliation, causal features, purged splits, costs/rounding, risk thresholds and halt persistence. Use a minimal synthetic reproduction for a claimed bug. Documentation-only changes need skill validation and source review, not exchange calls.

## Acceptance criteria

Report findings ordered by severity with concrete file/line, trigger, impact, and proposed correction. Separate defects from unverified concerns, planned functionality, and optional improvements. List tests actually run and relevant limitations. If no actionable findings are found, say so without claiming the project is certified safe or profitable. Never approve a failing or unevaluated ML candidate.

## Common mistakes

Reading a secret to check that it exists; whole-repository scans that include `.env`; trusting a feature flag instead of removing production reachability; testing by placing trades; treating mock success as account verification; approving leakage because accuracy is high; hiding missing risk controls behind future plans; changing the strategy while calling it a review.
