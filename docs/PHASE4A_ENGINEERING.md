# Phase 4A engineering implementation and independent review guide

Completed scope: offline data preparation and engineering diagnostics only. No model was fitted, no predictions were generated and no trading execution was enabled. The current approval/status is in PROJECT_STATUS.md; the fixed recipe and three approval clarifications are in PHASE4A_RESEARCH_PROPOSAL.md.

Official project: `C:\Users\yazan\Development\binance-demo-bot`. Paths below are relative to that project. The project was not moved or duplicated.

## What the modules do

1. `config.py` is the experiment's fixed recipe: dates, ordered 16-feature schema, 48-bar outcome horizon, four-hour buffer, p>=0.65 and hard sample gates. Defaults for simulated costs/risk/contracts are recorded from the unchanged simulator. Overrides of the engineering recipe are rejected.
2. `dataset.py` loads only [July 11 06:50, August 31 00:00), UTC. SQLite is opened read-only/query-only against a stable snapshot. It verifies the approved hash, contiguous shared candle grid, completed bars and funding diagnostics. Protected later rows are not selected. Structural integrity checking and full-file hashing do not interpret final labels/predictions.
3. `features.py` generates the fixed 16 inputs from information at or before candle close. It reuses the existing EMA/RSI/MACD/ATR/volume implementation. First 199 bars are warm-up. Missing/nonfinite values are refused, not filled from later values. No OI/funding/portfolio/label predictor is introduced.
4. `opportunities.py` enumerates every frozen baseline LONG/SHORT decision with valid features. It does not read the original trade journal or restrict samples to the historical 851 admitted trades. NO TRADE reasons and feature exclusions are counted.
5. `labels.py` offers each opportunity once to the unchanged BacktestEngine. Each run starts a separate 10,000 reference account, attempts next-open entry and keeps the original sizing, stop/target, daily rule and simulated costs. Future net PnL is the target, not an input. No additional signal is offered within that run. A valid outcome needs the full 48 future candles. Funding-gap/horizon/size failures are exclusions, not class-0 losses.
6. `splits.py` writes fixed expanding chronological memberships, horizon purges and the extra four-hour buffer. Paired symbols use the same UTC partition. Development gates are checked against fixed counts/classes/nonoverlap minimums; insufficient means INSUFFICIENT. Later periods have boundary metadata only, no memberships/outcomes/class counts. No split is moved to improve counts.
7. `artifacts.py` writes separate feature, label and isolated-trade CSVs plus canonical JSON manifests. Existing bundles cannot be overwritten; an identical rerun must match every byte. SHA-256 fingerprints record the recipe, source, inputs and payloads. There is no active/latest model pointer and no pickle/joblib/model serialization.
8. `safety.py` supplies entrypoint audit hooks blocking socket/DNS/HTTP, credential files and unauthorized client/ML imports. The test runner permits outside-project temporary dummy .env fixtures needed by existing mock tests; the project .env stays blocked. These hooks supplement reviewed code and do not form an OS sandbox or protect against arbitrary malicious Python.
9. `audit.py` reports development counts, hard gates, payoff asymmetry and realized funding-reserve overruns. It produces no model accuracy, calibration, probability predictions or policy-selection results.
10. `scripts/ml_research.py` exposes only `prepare-development`. `scripts/verify_phase4a.py` runs the offline suite and fingerprints the current tested research sources. Preparation requires matching passing-test hashes and unchanged protected inputs.

## Two useful concepts

**Causality:** a predictor must exist when the decision is made. For example, log(C_t/C_(t-12)) uses earlier closes; next candle's high belongs only to the outcome simulator. Feature and label CSVs are separate so future outcomes cannot accidentally be included in the 16 predictors. The future-perturbation test changes later candles and checks that earlier features/opportunities stay exactly the same.

**Purging:** a training decision near a split boundary can have an outcome that extends into the next period. Membership uses the whole four-hour outcome interval, even if the actual stop hit early. Before the August 1 00:00 evaluation, a training label must finish by July 31 20:00, leaving another four-hour safety buffer. Its decision is therefore roughly eight hours before evaluation. This prevents boundary leakage; it does not make overlapping observations inside each period independent.

An isolated label is also different from a shared account: it has no inherited prior loss, halt, open position or symbol conflict. A real simulated portfolio carries those states. A later model's chance of a positive isolated outcome would need separate shared-portfolio testing before any economic claim.

## Verified results and limitations

- Full suite: **183 discovered, 182 passed, zero failures/errors, one opt-in network test skipped**. All previous 116 offline checks and 66 new checks passed. Existing API/settings tests use dummy credentials/mock transports; no exchange requests were sent.
- Development only: 14,606 candles and 151 funding events per symbol, 2,397 opportunities, 2,390 valid labels (840 positive, 1,550 nonpositive), six funding-uncertain exclusions and one incomplete-horizon exclusion.
- Fold train counts: 1,033 / 1,409 / 1,796. Evaluation counts: 371 / 388 / 566, with 44 / 46 / 44 nonoverlapping observations. All predefined development sample gates are SUFFICIENT. No predictive or economic model gate has been evaluated.
- Isolated mean winner +21.10 USDT, loser -36.64. The payoff ratio is about 0.576; descriptive break-even winning fraction about 63.46%. These do not optimize or replace p>=0.65. Probability buckets are NOT AVAILABLE because there is no fitted model.
- **Risk evidence is NOT CLEARED:** five BTC stop-loss labels lost about 64.24–79.15 USDT, beyond the 50 USDT planned budget. Each recorded funding debit exceeds the original 0.1% sizing reserve. The stop ledger reconciles as net = -planned_loss + reserve - funding_cost. The reserve is not charged twice. Overlapping labels can share a settlement; these are not five independent account losses. All losing rows remain included. Planned entry-budget/leverage violations are zero.
- Six outcomes conservatively overlap the potential August 17 08:00 funding gap. The modal schedule is an assumption, not proof of complete funding history. One label uses stop-first on an ambiguous bar and one uncertain funding credit is omitted.
- OHLC path, timing/latency, liquidity, liquidation and Demo realism limitations persist. Later data was already inspected in old baseline research, so the final period is locked now but cannot be described as genuinely untouched.
- Two identical final engineering runs matched byte-for-byte. All nine current bundle payload checksums and 60 protected file hashes verified. The research database still matches its saved collection hash. Original databases/code/journals/AGENTS.md were preserved.
- No dependency installations, model fitting, learned preprocessing, prediction/calibration metrics, selection-validation/final outcomes, exchange activity, orders or activation.

## What the tests establish

| New test module | Passed | What it checks |
|---|---:|---|
| test_ml_dataset.py | 9 | Read-only/query-only refusal, unchanged hashes, protected/changed date refusal, invalid later rows not loaded, grid/WAL/file-kind validation, immutable market records and credential-shaped paths refused before content access. |
| test_ml_features.py | 11 | Manual feature definitions, ordered 16 columns, frozen-indicator parity, warm-up/nonfinite handling, volume denominator, availability, future/prefix causality and deterministic full baseline enumeration. |
| test_ml_labels.py | 21 | Manual LONG/SHORT PnL/cost/quantity checks and direct simulator parity, next-open/exact 48-bar horizon, stop-first/gaps, funding signs/credit assumptions, daily/midnight behavior, exclusions, locks and deterministic labels. |
| test_ml_splits.py | 14 | Off-by-one purge/buffer/maturity boundaries, symbol-time grouping, disjoint memberships, hard sample/class/nonoverlap gates, exclusions not treated as losses, deterministic/locked/unique/full-horizon contracts. |
| test_ml_artifacts.py | 11 | Frozen recipe, canonical finite hashes, exclusive/replayed bundles, mutation detection, separate predictors/outcomes, offline guard/no training command, deterministic integrated audit and funding-overrun explanation without changing targets. |

Synthetic fixtures are engineering evidence. They do not prove economic performance, real API connectivity, statistical independence or model quality. There are no model tests/results because no estimator exists. Development setup/fixture/edit issues encountered during implementation were fixed and followed by the passing full run.

## Reproduce the approved engineering stage

Use Python 3.11+ with the standard library only; no ML installation is needed. In PowerShell on this machine the verified bundled interpreter can be used:

```powershell
Set-Location 'C:\Users\yazan\Development\binance-demo-bot'
$LabPython = 'C:\Users\yazan\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $LabPython -B scripts/verify_phase4a.py
& $LabPython -B scripts/ml_research.py prepare-development
```

There is no training/unlock stage. Existing identical artifacts are verified, not replaced. Do not run original research scripts that regenerate the original journals. Do not invoke Phase 1 account/order-validation commands. A changed frozen input or untested source causes preparation to stop.

Current experiment: `engineering-65fb33dd258060c94ffd`. Its identifier is SHA-256 of the canonical configuration/data/code/proposal provenance, excluding the redundant post_processing_verification receipt, truncated to 20 hexadecimal characters with an engineering- prefix. Saved provenance contains the Python version, default cost/risk/spec manifest hash, snapshot hash, current source/test hashes and both protected-input checks. The chronological row IDs live in splits.json. Versioned payload hashes live in each bundle's manifest.json. The root engineering-tests.json describes the latest full suite; engineering-verification.json records the final two-run replay/checksum/input verification.

## Full changed-file manifest

Modified documents:

- docs/PHASE4A_RESEARCH_PROPOSAL.md — required approval clarifications before coding; completion versus future-stage bookkeeping.
- docs/PROJECT_STATUS.md — actual state, paths, tests, audit, limitations and approval boundary.

New document:

- docs/PHASE4A_ENGINEERING.md — this explanation and review manifest.

New Python modules/scripts/tests:

- src/demo_futures/ml_research/__init__.py
- src/demo_futures/ml_research/artifacts.py
- src/demo_futures/ml_research/audit.py
- src/demo_futures/ml_research/config.py
- src/demo_futures/ml_research/dataset.py
- src/demo_futures/ml_research/features.py
- src/demo_futures/ml_research/labels.py
- src/demo_futures/ml_research/opportunities.py
- src/demo_futures/ml_research/safety.py
- src/demo_futures/ml_research/splits.py
- scripts/ml_research.py
- scripts/verify_phase4a.py
- tests/test_ml_artifacts.py
- tests/test_ml_dataset.py
- tests/test_ml_features.py
- tests/test_ml_fixtures.py
- tests/test_ml_labels.py
- tests/test_ml_splits.py

New root evidence:

- artifacts/ml-research/engineering-input-witness.json
- reports/ml-research/engineering-tests.json
- reports/ml-research/engineering-verification.json

Current bundles:

- artifacts/ml-research/engineering-65fb33dd258060c94ffd/config.json
- artifacts/ml-research/engineering-65fb33dd258060c94ffd/features.csv
- artifacts/ml-research/engineering-65fb33dd258060c94ffd/isolated-trades.csv
- artifacts/ml-research/engineering-65fb33dd258060c94ffd/labels.csv
- artifacts/ml-research/engineering-65fb33dd258060c94ffd/manifest.json
- artifacts/ml-research/engineering-65fb33dd258060c94ffd/provenance.json
- artifacts/ml-research/engineering-65fb33dd258060c94ffd/splits.json
- reports/ml-research/engineering-65fb33dd258060c94ffd/audit.json
- reports/ml-research/engineering-65fb33dd258060c94ffd/manifest.json
- reports/ml-research/engineering-65fb33dd258060c94ffd/report.md
- reports/ml-research/engineering-65fb33dd258060c94ffd/tests.json

Retained superseded engineering bundles (before detailed funding diagnostics; no model ever fitted):

- artifacts/ml-research/engineering-3692c4dc8ccf0bf0def4/config.json
- artifacts/ml-research/engineering-3692c4dc8ccf0bf0def4/features.csv
- artifacts/ml-research/engineering-3692c4dc8ccf0bf0def4/isolated-trades.csv
- artifacts/ml-research/engineering-3692c4dc8ccf0bf0def4/labels.csv
- artifacts/ml-research/engineering-3692c4dc8ccf0bf0def4/manifest.json
- artifacts/ml-research/engineering-3692c4dc8ccf0bf0def4/provenance.json
- artifacts/ml-research/engineering-3692c4dc8ccf0bf0def4/splits.json
- reports/ml-research/engineering-3692c4dc8ccf0bf0def4/audit.json
- reports/ml-research/engineering-3692c4dc8ccf0bf0def4/manifest.json
- reports/ml-research/engineering-3692c4dc8ccf0bf0def4/report.md
- reports/ml-research/engineering-3692c4dc8ccf0bf0def4/tests.json

Nothing was changed in the frozen strategy, indicators, risk engine, simulator, original journals, databases, AGENTS.md, README.md or dependency manifest.

## Files for independent review

Share this guide, PROJECT_STATUS.md, the clarified proposal, the **current** report.md/audit.json/tests.json, config.json/provenance.json/splits.json and both current bundle manifests. Include the new ml_research Python files, both new scripts and test_ml_*.py. For numeric checks, include current features.csv, labels.csv and isolated-trades.csv; these contain only saved-market/simulated research records. Include the engineering verification receipt and protected-input witness for preservation evidence. Existing frozen simulator/strategy/indicator/risk code and relevant prior tests are needed to verify reuse/parity; they were not edited.

Do not include .env, credentials, account data, databases, sensitive logs, .git, caches or virtual environments. No ZIP/upload was requested or performed in this task.

## Stop boundary

Implemented/tested: the approved offline engineering foundation and development audit. Proposed/unimplemented: logistic/scaler fitting, prediction baselines, fixed probability-bucket/calibration reports, model-filtered portfolio and stress evaluations, later validation/final evaluations, model registry and promotion. Phase 3, dashboard and deployment are also absent.

The next step is your review, including the funding-risk finding. **Wait for explicit approval before any fitting or selection-validation evaluation. Final opening needs separate approval.** Do not alter features, strategy, p>=0.65, risk, labels, split dates or minimums based on these diagnostic results.
