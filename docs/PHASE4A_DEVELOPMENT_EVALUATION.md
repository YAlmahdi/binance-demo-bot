# Phase 4A development-fold evaluation

Completed 2026-10-10 after explicit approval for development fitting only. Experiment: `development-928f3f181f2825ba8b7a`. Exactly three historical fits, one frozen recipe, no search. Models are inactive. **Risk evidence: NOT CLEARED.** Selection validation and final outcomes remain locked.

## Result in plain English

The indicators did not improve prediction over a constant probability equal to the training win rate. Model log loss and Brier were worse in every fold. At p >= 0.65 it took two simulated trades; both lost. Avoiding most trades reduced the frozen baseline's losses, but holding cash did better. There is no evidence of a profitable or deployable model.

The model learned associations, not profitable trading knowledge. Normalized MACD coefficients were positive in all three fits and EMA20/EMA50 spread coefficients negative. The LONG flag changed sign. Correlated indicators prevent a causal interpretation. No feature selection followed these findings.

Both admitted ETH LONGs occurred August 19. Probabilities were 98.40% and 96.29%; both stopped in the entry candle, losing 47.4944 and 47.9708 simulated USDT. Several influential inputs exceeded training ranges. Candle range was 18.7 and 33.2 training standard deviations above its mean; normalized MACD 10.3 and 9.2. A linear logit can confidently extrapolate beyond its observed training inputs. The probabilities were unreliable here. No clipping, outlier filter or recipe change was made.

## Implemented architecture

Paths below are relative to `C:\Users\yazan\Development\binance-demo-bot`.

| New file | Purpose |
|---|---|
| `src/demo_futures/ml_research/development_data.py` | Existing engineering manifest/CSV/ledger checks, fixed memberships and checked training-only partitions; no label regeneration. |
| `src/demo_futures/ml_research/model.py` | Training-only scaler of 14 continuous columns, two unchanged binary flags, fixed L2 logistic fitting and inert numeric model prediction. |
| `src/demo_futures/ml_research/evaluation.py` | Log loss/Brier, classification/calibration, majority/prior baselines, fixed ten payoff buckets, paired UTC-block uncertainty and nonoverlap sensitivity. |
| `src/demo_futures/ml_research/portfolio.py` | Causal admission adapter over unchanged BacktestEngine; same-window policy and cost comparisons, with no retrospective label-status filters. |
| `src/demo_futures/ml_research/development_runtime.py` | Network/credential guards, exact pinned environment and exclusive inactive artifact versions. Original engineering guard is unchanged. |
| `scripts/run_development_folds.py` | Passing tests/provenance required; registers before fitting; exactly three fixed folds. No parameter/stage overrides or automatic refits. |
| `scripts/verify_development_folds.py` | Full offline tests, synthetic fit fixtures and separate evidence; original engineering evidence is preserved. |
| `scripts/verify_development_results.py` | Reconstructs inert JSON models without fit; independently verifies predictions/scores/journals and writes descriptive supplements. |

Original features, labels, splits, engineering modules, strategy, indicators, risk, backtester and historical journals are unchanged. The old engineering entrypoint remains appropriate to its engineering stage; do not rerun it to regenerate data.

## Frozen recipe and separate environment

L2 logistic regression, C=1, lbfgs, intercept, no class weights, max_iter=2000, seed=42. Pinned library defaults otherwise. In sklearn 1.9.1 `l1_ratio=0` specifies L2. StandardScaler fits only the current fold's first 14 training columns; symbol/side flags pass through. Fit/prediction numerical BLAS limits are one thread. No calibrator, imputation, clipping, feature selection, sampling or tuning.

Admission remains p >= 0.65. Accuracy uses the explicitly separate conventional classification cutoff 0.5; it does not change trading admission.

Environment: `C:\Users\yazan\Development\research-environments\futures-ai-lab-logistic-v001`, Python 3.12.14. Exact pins: scikit-learn 1.9.1, numpy 2.5.3, scipy 1.18.1, joblib 1.6.0, threadpoolctl 3.7.0, required narwhals 2.27.1 and cloudpickle 3.1.2. No pandas, deep learning or trading dependencies installed. Official wheel hashes were verified before local no-index/no-deps/hash-required installation; pip check passed. Pins and provenance are under `research/dependencies/`; wheel binaries are locally ignored. Downloads used only official package hosts; research execution was offline.

Official API sources: [LogisticRegression](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.LogisticRegression.html), [StandardScaler](https://scikit-learn.org/stable/modules/generated/sklearn.preprocessing.StandardScaler.html), [calibration](https://scikit-learn.org/stable/modules/calibration.html). Exact official package metadata/download URLs are recorded locally. These describe library behavior, not profitability.

## Data, timing and gates

Only existing engineering `engineering-65fb33dd258060c94ffd` and saved development candles/funding were interpreted: UTC [2026-07-11 06:50, 2026-08-31 00:00), 14,606 contiguous 5m bars and 151 funding observations per symbol. Original 2,397 features and 2,390 valid labels remain unchanged; six funding-uncertain and one incomplete-horizon exclusions remain.

| Fold / UTC evaluation | Train rows / class 0 / 1 | Eval rows / class 0 / 1 / nonoverlap | Iterations |
|---|---|---|---|
| 1 / Aug 1–11 | 1033 / 669 / 364 | 371 / 261 / 110 / 44 | 35 |
| 2 / Aug 11–21 | 1409 / 933 / 476 | 388 / 278 / 110 / 46 | 38 |
| 3 / Aug 21–31 | 1796 / 1211 / 585 | 566 / 327 / 239 / 44 | 28 |

Training expands from the fixed July start. Full training label horizons must mature by evaluation start minus four hours. Current/future-fold evaluation labels never enter that fold's fitting. Earlier evaluation can become matured training history in later folds as approved. All hard classification sample gates pass, with no boundary changes; this does not prove independence.

Portfolio indicators retain past warm-up candles; entries before the evaluation start are masked. Each policy starts a fresh 10,000 simulated account on identical dates with the same full-horizon cutoff. Do not concatenate fold curves as one account. Baseline rules are unchanged: this comparison restricts them to common research windows rather than rerunning the original continuous 90-day account.

All 1,331 causal window opportunities were scored for admission (371/394/566). Classification uses 1,325 valid matured labels (371/388/566). Six funding-uncertain fold-2 opportunities were still scored; future exclusion flags never gate admission.

## Predictions

Lower log loss/Brier is better. The prior predicts each fold's training win fraction for every eval row. Majority predicts its training majority class, always zero here.

| Fold | Model / prior log loss | Model / prior Brier | Model / majority accuracy | Model ECE |
|---|---|---|---|---|
| 1 | .663829 / .614895 | .226968 / .211708 | 70.35% / 70.35% | .131481 |
| 2 | .646003 / .603026 | .220054 / .206081 | 70.62% / 71.65% | .109346 |
| 3 | .704069 / .701349 | .253692 / .253276 | 57.60% / 57.77% | .093982 |
| Pooled OOF | .675798 / .648350 | .236359 / .227817 | 64.98% / 65.36% | .066474 |

OOF predictions were generated before their own evaluation outcomes entered fitting. Pooled class counts: 866 nonpositive/459 positive. Hard majority log loss is infinite on positive outcomes because it assigned zero probability; that is explicit, not silently clipped. Its pooled Brier is .346415. Model beats this crude Brier but fails against training prevalence and does not improve majority accuracy.

Paired 24h UTC blocks, both symbols/policies, 1000 resamples, seed42. Pooled prior-minus-model log-loss 95% CI [-.049983,-.008422], indicating worse model scoring in this conditional resampling design. Fold1/2 intervals are negative; fold3 straddles zero (positive-improvement evidence INSUFFICIENT). Only ten blocks per fold/thirty pooled; resampling is conditional on fitted models and does not capture model re-estimation uncertainty. Serial dependence/regimes/overlap limit generalization.

The predeclared nonoverlap subset also has worse model log loss in each fold: .642517/.600428, .793937/.646313, .700897/.691766 (model/prior). Fixed probability buckets report win fractions, mean net/risk/payoff, costs and uncertainty. Fewer than ten rows or ten UTC blocks are marked INSUFFICIENT. Pooled ECE can hide fold differences and does not clear the locked selection-validation gate.

## Portfolios after costs

| Fold | ML trades | ML net | Baseline trades / net | Cash net | ML PF | ML drawdown | Doubled-cost ML net |
|---|---|---|---|---|---|---|---|
| 1 | 0 | 0.00 | 73 / -1424.95 | 0.00 | Undefined | 0.00% | 0.00 |
| 2 | 2 | -95.47 | 94 / -1622.92 | 0.00 | 0 | .9547% | -95.68 |
| 3 | 0 | 0.00 | 102 / -1428.76 | 0.00 | Undefined | 0.00% | 0.00 |

Units are simulated USDT. Prior/majority policies admit no trades at .65 and match cash. Fold2 ML win rate zero. All ML economic sample evidence is INSUFFICIENT against the future minimum of 50 trades/ten entry days. Zero trades are not positive profitability or safety proof. Positive net, beats cash, PF and doubled-cost-positive gates do not pass. This is development diagnosis, not selection-validation acceptance.

Stress doubles fees/slippage only, without refitting or changing predictions. Frozen sizing recomputes quantity/admissions: it is not just a doubled bill on fixed quantities. Funding, .5% risk, 2x, 2% daily limit, ATR levels and holding limit remain unchanged.

One fold2 baseline trade overlaps the Aug17 08:00 funding gap in both scenarios: exact economic funding completeness there is INSUFFICIENT. No ML trade overlaps the detected gap. Unchanged simulator behavior is reported openly; missing funding is not certified zero.

## Funding risk remains NOT CLEARED

The same five isolated BTC stop labels exceed their 50-unit budget; no negative row was removed. Two July 20 LONGs and three August 3 SHORTs share settlement events. Losses 64.24–79.15, funding debits 21.55–43.75, sizing reserves 7.20–14.58. Every ledger reconciles `net = -planned_loss + sizing_reserve - funding_cost`. Reserve sizes the trade and is not charged again; actual funding was approximately three times the reserve. A reserve assumption does not guarantee a realized loss cap.

Saved labels have zero planned-entry budget/leverage violations and new ML portfolios have no observed realized-budget overrun. Neither clears the underlying issue. No label/risk/simulator change. Real protective orders, liquidation, restart-safe halts and exchange kill switches remain unimplemented.

## Tests and preservation

**223 discovered, 222 passed, zero failures/errors, one opt-in network test skipped.** This is 182 prior offline passes plus 40 new development tests. Unit fitting uses synthetic data only; exactly three historical fits occurred separately.

| New test file | Passed | Meaning within tested scope |
|---|---|---|
| `tests/test_ml_model.py` |14|Training scaler statistics, flags, deterministic recipe, no inference fit, purge/embargo/minima, convergence stop and finite inactive schema.|
| `tests/test_ml_evaluation.py` |10|Hand scores, infinite majority loss, bucket/probability boundaries, bootstrap/sparsity and separate accuracy/admission cutoffs.|
| `tests/test_ml_development_data.py` |7|Actual saved counts/membership, future eval-label changes excluded from training, locked stages, versions/paths and guard.|
| `tests/test_ml_portfolio.py` |9|Next-open timing, .65/cash, same-window financial parity, gap reporting without hindsight, ledger and stress preserving risk.|

`test_ml_development_fixtures.py` is synthetic helpers only. All prior tests retain their scope. Mock account/client tests send no requests or validation orders.

Separate saved-artifact verifier: **58 checks pass**, zero fits, including JSON prediction replay, exact train IDs/scaler, independent sklearn scores, all 30 journal ledgers/timing and preservation. Networking and credential-file reads are blocked. Hooks are supplementary safeguards, not an OS sandbox.

**92 protected files UNCHANGED**, including both databases, frozen code/original tests/journals/reports and current engineering CSV/config/split/test/verification artifacts. Research DB hash: `becff4021769cb8d9555c454f768592a55a266ab8924d2eb46479773f2ef755c`. Whole-file hashes/SQLite integrity are provenance, not interpretation of later outcomes.

## Changed files and review materials

Added five modules/three scripts above, four test files and one synthetic helper, this guide, dependency locks/provenance, protected witness/run receipt and versioned artifacts/reports. Updated `docs/PROJECT_STATUS.md`; appended the local wheel-directory exclusion to `.gitignore`. Original requirements, AGENTS.md, approved proposal and all engineering/trading code/data/journals are unchanged.

Share:

- This guide, current status and approved `docs/PHASE4A_RESEARCH_PROPOSAL.md`.
- `reports/ml-research/development-928f3f181f2825ba8b7a/{report.md,evaluation.json,tests.json,predictions.csv,coefficients.csv,manifest.json}` and per-fold/policy/scenario simulated trade/equity CSVs.
- `artifacts/ml-research/development-928f3f181f2825ba8b7a/{config.json,provenance.json,splits.json,fold-1-model.json,fold-2-model.json,fold-3-model.json,manifest.json}`. Numeric inert JSON, no executable serialization.
- `reports/ml-research/development-928f3f181f2825ba8b7a-verification/{verification.json,probability-bucket-payoffs.csv,admitted-feature-contributions.csv,manifest.json}`.
- New modules/scripts/tests and dependency lock/provenance; unchanged reused code/engineering CSVs if needed. No credentials/account data/databases/private logs/wheels/environments.

## Offline verification and next approval

PowerShell in the official project:

```powershell
$researchPython = 'C:\Users\yazan\Development\research-environments\futures-ai-lab-logistic-v001\Scripts\python.exe'
& $researchPython -B scripts/verify_development_folds.py
& $researchPython -B scripts/verify_development_results.py
```

The completed experiment refuses automatic refitting. Review saved results, not different runs. No active/latest pointer exists. Future selection validation requires explicit approval; final opening is separate. The final period was previously inspected for baseline research, so it is not genuinely untouched even though no ML outcomes were opened here.

Stop here. No further fitting, tuning, selection-validation/final evaluation, activation, orders, Phase3, dashboard or VPS work is approved. OHLC path/latency, historical cost/filter assumptions, Demo representativeness, overlapping isolated labels, incomplete funding and limited blocks remain unverified limitations.
