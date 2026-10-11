# Phase 4A â€” offline ML research proposal

Status: **ENGINEERING IMPLEMENTATION APPROVED ONLY â€” model fitting, selection-validation evaluation and final-period access remain unapproved.** Prepared 2026-10-10 after reading `docs/PROJECT_STATUS.md`, the ml-trading-research, quant-backtesting and trading-code-review skills, and the current simulator/strategy interfaces.

The original proposal stage created this design only. Current authorization is limited to the engineering modules and development audit below; actual completed components/tests are recorded in PROJECT_STATUS.md. Model fitting, predictions, selection-validation/final evaluation, dependency installation and exchange activity remain outside this approval.

## Engineering approval clarifications â€” before implementation

The user's current approval covers only the loader, 16-feature pipeline, baseline opportunities, isolated labels, chronological/purged manifests, provenance/artifacts and offline engineering tests. It does not approve the broader training/evaluation stages described later in this proposal. No model, probability prediction or portfolio ML admission policy will be created or run in this task. Only development-period feature/label/split audits are permitted. Selection-validation outcomes and final-period labels/predictions remain locked.

### Fresh-account labels versus a shared portfolio

For each eligible baseline signal, the label creates a separate 10,000 USDT account with no position, no pending entry and no accumulated prior loss. The one-shot adapter offers that signal once at the original candle close. The unchanged engine attempts it at the next open using the frozen signal ATR, contract assumptions and risk rules; it does not emit follow-on signals.

Daily-loss state starts inside this isolated run: the signal candle initializes the UTC day's anchor at 10,000 and the halt is initially false. Only this opportunity's fees, adverse marks, funding and PnL can trigger its daily rule. If it crosses UTC midnight, the existing engine resets that next day's anchor to this isolated account's opening marked equity. There is no inherited loss or halt from another opportunity. This is the engine's existing daily reset, not a new risk parameter.

The shared-portfolio simulation instead carries its evolving cash/equity, current positions and latched daily loss state across consecutive signals. A signal may be rejected because a position is already open, the shared portfolio cap is full, a prior loss halted the day, or changed equity makes the rounded order too small. Simultaneous symbols compete under unchanged BTC priority. None of those cross-opportunity conflicts exists in an isolated label.

Opportunity eligibility is the frozen baseline's LONG/SHORT decision plus valid causal features, independent of whether the old shared portfolio admitted the signal. Labels have an additional retrospective validity gate: a full 48-bar horizon inside the permitted period, sufficiently known funding, and a reference account trade that passes next-open sizing. Non-executable or uncertain outcomes are exclusions, not invented losses or wins. Future size/funding/horizon exclusion flags are never predictors or model admission signals. Isolated opportunities may overlap each other and cannot be summed into an executable account, account return or independent trade sample. Label probability is conditional on this fresh-reference experiment, not the exact future shared-portfolio payoff.

### Frozen threshold and payoff reporting

The proposed model admission threshold remains exactly **p >= 0.65**. It will not be optimized from validation or final-period results. Later approved prediction reports must include fixed equal-width probability-bucket counts, observed win fractions, average net PnL, mean winning/losing payoff, payoff ratio, net-risk-budget units, fees/slippage/funding and uncertainty/sparse-bin flags. This distinguishes chance of winning from expected payoff. Report implied break-even win fractions from observed payoff asymmetry as descriptive quantities, not replacement admission thresholds. Engineering reports can show development-only isolated payoff statistics; probability buckets must be marked NOT AVAILABLE until fitting/prediction is explicitly approved.

### Hard sample-size gates

All sample/class/nonoverlap minimums in section 9 are hard research gates. A deficient count yields **INSUFFICIENT**, even when another metric looks favorable. Never move UTC split boundaries, relax purging/buffer, shorten the horizon, change label exclusions or lower minimums to manufacture a sufficient sample. Engineering completeness and sample sufficiency are separate decisions. Validation/final gates whose outcomes are locked must be NOT EVALUATED, not PASS or an inferred class count.

## 1. First experiment and boundaries

Question: can an interpretable offline model distinguish promising from unpromising **opportunities already proposed by the frozen baseline**, after simulated costs?

The first model is a veto filter, not a new directional strategy. At a completed 5m candle, the unchanged baseline proposes LONG, SHORT or NO TRADE. The model estimates the chance that that particular proposed trade would have positive net PnL in an isolated reference simulation. A separate offline research adapter passes the proposed side/ATR onward only if probability >= 0.65; otherwise it emits NO TRADE. It never converts NO TRADE into an entry, switches direction, changes ATR levels or enlarges risk.

The 0.65 model threshold is a proposed experimental setting, not a change to baseline thresholds and not a guaranteed expected-profit threshold. Probability of winning alone does not measure payoff size. The separate portfolio/cost evaluation determines whether the filter has economic value. There will be no threshold grid search, feature-selection search, calibration tuning or hyperparameter sweep in experiment 001.

Training opportunities are **all causally generated eligible baseline signals**, including signals that the historical shared account would reject while already positioned or halted. Do not fit only the 851 executed trades: they are a selected, portfolio-dependent subset. Labels for hypothetical opportunities may overlap; they are not an executable portfolio or independent observations.

## 2. Data and point-in-time assumptions

Input is only existing `data/research-90d.sqlite3`: BTCUSDT/ETHUSDT, 25,920 5m candles each, UTC 2026-07-11 06:50:00 through 2026-10-09 06:49:59.999. `data/market.sqlite3`, original reports/journals and frozen files remain unchanged.

The data loader must use SQLite read-only/query-only access, verify integrity, shared contiguous time grids and the frozen snapshot hash. Its partition queries limit what training jobs can load. It must never instantiate SQLiteStore on the source, perform ingestion or access Phase 1 settings/client code.

Decision time is a candle's close timestamp; every feature has availability <= that close. Recorded close time is an assumed historical availability time: the snapshot does not establish real latency, revisions or what a live stream would have delivered then. No feature uses the next open, future high/low, future funding, future fill, realized outcome, prior journal attribution, or whole-dataset statistics.

Funding records are available for cost accounting, with two potential schedule gaps per symbol. Their retrospective collection/observation times are not evidence of historical predictability, so **no funding predictor is included**. OI snapshots cannot reconstruct historical OI, so no OI predictor. No synthetic production data, cross-symbol feature joins or higher-timeframe joins are included in version 001.

## 3. Proposed fixed 16-feature schema

C is the current completed candle close. Indicator definitions reuse `src/demo_futures/indicators.py` unchanged. Returns and ratios are dimensionless.

| Group | Exact proposed columns | Count |
|---|---|---:|
| Backward returns | log(C_t/C_(t-k)) for k = 1, 3, 12, 48 candles | 4 |
| EMA trend | C/EMA20 - 1; EMA20/EMA50 - 1; EMA50/EMA200 - 1 | 3 |
| Momentum | (RSI14 - 50)/50; MACD12/26/C; MACD histogram12/26/9/C | 3 |
| Volatility/volume/candle | ATR14/C; current volume / preceding 20-bar mean; (high-low)/C; (close-open)/C | 4 |
| Known context | symbol_is_ETH (0/1); proposed_side_is_LONG (0/1) | 2 |

Rolling quantities end at the decision candle, except relative-volume denominator explicitly excludes the current candle. EMA/RSI/ATR/MACD seed conventions remain frozen. First 199 candles are warm-up; longer backward features must also be available. Missing, nonfinite or inconsistent inputs produce no training row/no model admission, with a reason. No backward fill, centered window, interpolation or data-learned imputation. Zero-range candle features are zero; unavailable volume history is rejected.

Feature computation can retain causal state from earlier permitted history when a validation window begins. This is past information, not transformer fitting on validation data. Changing or appending later candles must not change earlier features. Raw price, timestamp, outcome columns, label identifiers and portfolio balances are excluded from predictors.

## 4. Target: a cost-aware isolated proposed trade

Binary target: **y=1 if the isolated proposed trade's net PnL > 0; y=0 if net PnL <= 0**, under the existing default assumptions. Flat outcomes are explicitly counted with class 0. Also retain net PnL, net/planned-risk-budget, exit reason and actual outcome time for diagnostics, never as input features.

Timing:

1. Baseline signal/ATR is generated at candle t close.
2. Earliest entry is the open of candle t+1, including existing adverse slippage and tick rounding.
3. Stop/target use the frozen signal ATR and existing sizing semantics at that next open: stop 2x ATR, target 3x ATR.
4. Exit follows the frozen simulator: stop/target or its daily-loss rule, otherwise the 48th held candle's close. Maximum target horizon is **48 future 5m candles = 4 hours**.
5. Unknown OHLC path keeps stop-first priority and the existing conservative daily/funding rules. Gap stops and targets follow existing rules. No favorable fill ordering is selected for a label.

Reference sizing uses a fresh simulated 10,000 USDT account, the same 0.5% planned risk, 2x maximum leverage, one position, UTC 2% daily rule, funding reserve and offline contract specs. Each opportunity is evaluated in isolation; no neighboring opportunity changes its label. This avoids making the supervised target depend on a previous policy's account path, but means its probability is not a direct forecast of a future shared-account outcome. Cost/precision and portfolio selection can create a target-to-policy mismatch, which must be measured separately.

Costs: 0.05% fee per side, 0.02% adverse slippage per fill plus existing tick rounding, and available recorded signed funding while held. Sizing's 0.1% funding reserve is not charged again. Rates/filters are research assumptions, not verified historical exchange terms. Label 1 does not certify true economic profitability if funding is incomplete.

Reuse `BacktestEngine` unchanged with a one-opportunity Signal adapter over the signal candle plus the following 48 candles. Subsequent signals are NO TRADE. This reuses `size_position`, fill priorities, cost settlement and holding count, instead of implementing a second financial engine. Tests must compare this label path with hand-calculated fixtures and direct engine results. Use actual recorded funding points; never fabricate dummy events or silently enable a missing-funding override to satisfy the engine's nonempty-history requirement. A preceding real event can establish a nonempty series without adding a settlement inside a window.

Each label records decision_time, entry_time, outcome_time and a **conservative label interval** [next_open, next_open + 4h). Purging uses the full four-hour interval even when a stop exits earlier. This deliberately sacrifices some data to make boundary logic auditable.

If next-open sizing fails, mark NO_EXECUTABLE_REFERENCE_TRADE and exclude from classifier fitting/scoring, with counts/reasons. If 48 future bars are absent or cross the partition outcome boundary, mark INCOMPLETE_HORIZON. Never shorten the label horizon or invent an end-of-data profit.

For windows that could overlap a known potential funding gap, retain the feature/opportunity record but mark the cost-aware label FUNDING_UNCERTAIN and exclude it from supervised fitting/scoring. Missing-rate exclusions are retrospective data-quality handling, **not a prediction-time admission rule**. The actual portfolio replay does not learn future gap/label-validity flags or suppress trades using them; it exposes any resulting uncertain funding costs and cannot receive an unqualified economic PASS when trades overlap those gaps. Likewise future reference-size rejection is not handed to the classifier as a feature; the ordinary risk gate runs at next open.

## 5. Exact chronological plan (UTC, half-open boundaries)

Partition by decision/feature-availability timestamps, never dataframe row number. BTC and ETH at the same timestamp always stay in the same partition.

| Stage | Nominal decision period | Use |
|---|---|---|
| Development | [2026-07-11 06:50, 2026-08-31 00:00) | Feature/label construction, expanding walk-forward fitting and synthetic engineering checks. |
| Selection validation | [2026-08-31 00:00, 2026-09-15 00:00) | One evaluation of the fixed recipe; PASS/FAIL/INSUFFICIENT. No threshold adjustment from its results. |
| ML-reserved final period | [2026-09-15 00:00, 2026-10-09 06:50) | Locked until the recipe/artifact are frozen and final evaluation receives separate approval. One confirmatory evaluation for that frozen recipe. |

Three expanding outer development folds:

| Fold | Nominal training start/end | Nominal evaluation start/end |
|---|---|---|
| 1 | July 11 06:50 to August 1 00:00 | August 1 00:00 to August 11 00:00 |
| 2 | July 11 06:50 to August 11 00:00 | August 11 00:00 to August 21 00:00 |
| 3 | July 11 06:50 to August 21 00:00 | August 21 00:00 to August 31 00:00 |

All dates are 2026 UTC. Training/evaluation endpoints above are nominal: warm-up, full-horizon exclusions, purging and embargo reduce eligible samples. Counts must be reported after implementation; they have not been generated now.

For evaluation start B: first purge every training label whose full interval could overlap evaluation; additionally require **training_label_end_exclusive <= B - 4h**. That adds a four-hour pre-evaluation safety buffer after label maturity. With the four-hour target horizon, decision cutoffs are roughly eight hours before B. The extra buffer reduces near-boundary dependence; it does not make all observations independent. The same rule applies at development-to-validation and pre-final-fit-to-final boundaries.

This is forward-only fitting: future rows are never admitted to a past fold. A post-test embargo intended for splits with future training data is therefore unnecessary here. Earlier fold evaluation data can become training history in a later fold only when its labels have matured and the same buffer is satisfied. No random/stratified shuffling across time.

All evaluation labels must end inside their evaluation period. For portfolio comparisons, the entry-admission window ends four hours before period end for every policy, so maximum-horizon positions can settle without an artificial end-of-data exit. This scheduled calendar cutoff is known in advance and common to all policies; it is not based on future profitability. Report the exact eligible calendar window.

Overlapping labels inside a partition remain correlated. For uncertainty, use a predeclared paired **24h UTC block bootstrap, 1,000 resamples, seed 42**, retaining both symbols together. In addition report a deterministic nonoverlapping diagnostic subset selected chronologically across both symbols using the full four-hour label interval: sort by decision time then BTCUSDT before ETHUSDT, retain the first valid candidate and advance eligibility to its conservative interval end before retaining another. It is a sensitivity analysis, not a new training recipe. Do not call thousands of overlapping opportunities thousands of independent trials. Temporal blocks still do not guarantee independence, especially with few days.

## 6. Honest final-period handling

The whole 90-day dataset already appears in baseline evaluation and diagnostics. Its last weeks therefore are **ML-reserved, previously inspected data**, not a genuinely untouched market holdout. This prospective restriction protects against further model-selection reuse, but cannot undo earlier human/research exposure. Final scores must disclose that fact.

Before any fit, write a proposal/configuration digest, split manifest and experiment register. Development/validation preparation must not generate final-period labels, scores, predictions or class summaries. Reading the full-file hash is allowed for provenance; interpreting final observations is not part of a development job. Training loaders reject requested ranges that cross the locked boundary.

Opening the final period needs separate explicit approval after the recipe and final pre-period model artifact are frozen. Log an evaluation receipt before computing results; a failed/interrupted run consumes the attempt and may only be resumed with the identical artifact/configuration, with both attempts recorded. No hidden retry after edits. A later change in features, horizon, model or threshold is a new exploratory experiment; it cannot reuse the same period as independent confirmation.

No approved fitting/transformation step may use final-period data. Before the final opening, refit once on the permitted development + validation history after applying final-boundary purge/buffer, using exactly the already-fixed recipe. For the selection-validation evaluation, fit a separate model on development history only, with the August 31 boundary purge/buffer; it cannot fit on selection-validation rows. For the eventual final evaluation, the new pre-period refit may include those now-historical validation rows, but its scores do not retrospectively replace the earlier validation result. No learned post-calibrator is included in version 001. A truly fresh market holdout would require later separately approved collection; do not fetch anything now or substitute production history.

## 7. Model and comparisons

Proposed first estimator: pooled BTC/ETH **L2-regularized logistic regression**, standardized continuous features, symbol/side flags, C=1.0, lbfgs, fit_intercept=true, class_weight=None, maximum 2,000 iterations and seed 42. Single-thread numerical settings and an exact pinned research dependency environment will be recorded before a fit. Stop on nonconvergence rather than silently changing solver/settings.

Propose an optional research dependency group using official scikit-learn/NumPy/SciPy; exact compatible versions and hashes must be frozen during approved implementation before fitting. Do not install dependencies at this proposal stage. Keep the existing diagnostics environment separate. Use the pinned library's supported L2 API; current official documentation deprecates the older penalty argument in favor of l1_ratio/C. No code is committed against an unverified installed version now.

The scaler/model pipeline is freshly fitted only on permitted training rows per fold. No full-series scaling, target encoding, feature selection, oversampling or data-derived clipping. Zero-variance handling uses training variance only. Model coefficients, intercept and feature units are reported; coefficient associations are not causal explanations.

Prediction comparisons on the same label-eligible opportunities:

- Majority-class hard prediction determined from that fold's training labels only; deterministic tie chooses class 0.
- Constant training-prevalence probability as the proper log-loss/Brier comparison. This avoids making a hard majority guess look artificially probabilistic.
- Always reject (class 0) can have a confusion matrix/balanced accuracy/Brier score. It is not a meaningful calibrated probability forecast; a p=0 predictor has infinite log loss when positives occur, represented explicitly rather than JSON infinity or a claimed finite advantage.

Trading comparisons on exactly the same calendar window/account/risk/cost assumptions:

- Frozen baseline, admitting all its qualifying opportunities subject to its existing risk gate.
- ML-filtered baseline with the fixed p>=0.65 adapter and the same risk gate.
- Majority/prevalence filter applying the same admission threshold, as an additional sanity check.
- NO TRADE cash account, zero trades/costs/drawdown; win rate/PF undefined.

All policies start separate 10,000 USDT accounts per evaluation window. Indicator state can use earlier permitted candles, but adapters suppress entries before the window. Recompute exposure and window metrics on the evaluation segment, not the warm-up prefix; assert matching boundaries, initial capital and reference costs. Do not splice separate fold accounts into a fictitious continuous equity curve. Report each fold independently and appropriate sample/time-weighted predictive summaries.

`BaselineStrategy`, `BacktestEngine`, `BacktestConfig`, fill/risk rules and original journals stay unchanged. Reuse the engine's existing injected-strategy interface from new research modules only. The model cannot fit from its signals method or automatically reload another artifact. A later inference module remains offline and can load only an explicitly named research artifact.

## 8. Prediction quality versus economic results

Classification report: class counts, confusion matrix, precision/recall, balanced accuracy, ROC-AUC and PR-AUC when defined, log loss, Brier score, and reliability table/diagram. Use ten fixed equal-width probability bins, report bin counts and ECE weighted by counts, and flag bins with fewer than ten observations. No claim of calibrated confidence from raw predict_proba output. Report paired block-bootstrap uncertainty and symbol/side breakdowns without selecting new policies from them.

Trading report: accepted/rejected opportunities, trade count, LONG/SHORT and symbol totals, realized net PnL after all recorded costs, fees/slippage/funding, average winner/loser/duration, turnover, exposure, profit factor and conservative maximum drawdown, plus planned-risk violations and cost/funding caveats.

Rerun each policy with doubled fee/slippage assumptions only as a declared sensitivity scenario after approval. This creates new reports, never overwrites the original 90-day journals or changes stored defaults. No retraining or probability threshold changes under stress. Label/portfolio differences must be documented: isolated labels can overlap, but the real simulated shared account only holds the positions allowed by its frozen gate.

## 9. Acceptance criteria to approve before fitting

These are **proposed research gates**, not claimed results or deployment permission. A working foundation can pass engineering tests while its model fails performance gates; a negative/insufficient result is a valid research outcome.

| Gate | Proposed criterion |
|---|---|
| Engineering/safety | Existing offline suite and new leakage/label/split tests pass; zero source/input mutations, network/credential access or execution activation; partition and artifact manifests complete. |
| Reproducibility | Same pinned environment/seed produces identical rows, labels and split membership; coefficients/probabilities agree to absolute 1e-10; economic Decimal ledgers reconcile to existing 1e-12 USDT tolerance. |
| Training sample sufficiency | Each development fit has >=200 valid candidates, >=40 in each class. Otherwise INSUFFICIENT; do not move boundaries to fix counts. |
| Fold evaluation sufficiency | Each outer evaluation has >=100 label-valid candidates, >=20 in each class, and >=30 members in the chronological nonoverlapping diagnostic subset. Otherwise report the fold as INSUFFICIENT. |
| Validation/final prediction sufficiency | Each has >=100 valid candidates, >=20 in each class, and >=60 nonoverlapping diagnostic observations; count shared timestamps and dependence explicitly. Otherwise INSUFFICIENT. |
| Predictive research merit | Development pooled out-of-fold and selection-validation log loss each improve >=1% over training-prevalence predictor; Brier is no worse; validation ECE <=0.10. Require paired 95% block-bootstrap interval for mean log-loss improvement to exclude zero; too-wide/too-short evidence is INSUFFICIENT. Apply the same predeclared gate at final evaluation, with its previously-inspected-data caveat. Accuracy alone is not a PASS. |
| Economic sample sufficiency | >=50 closed filtered-policy trades over >=10 UTC entry-active days in selection validation and final evaluation separately; otherwise INSUFFICIENT. Trades need not be independent. |
| Economic research merit | Default net PnL >0 and exceeds both baseline and NO TRADE on the identical evaluation period; PF >=1.10; conservative DD <=10%; net PnL remains >0 under doubled costs. Selection-validation and final results assessed separately. |
| Risk evidence | No violation of configured planned-risk/entry leverage/position limits, no pyramiding or unauthorized fit/model changes. Any loss exceeding planned risk must be reported and investigated; fail the candidate risk gate pending review. A 2% entry halt is not a guaranteed realized-loss ceiling. |
| Funding/data evidence | No unknown cost exposure may be silently reported as verified net profitability. Known funding-gap overlap produces INSUFFICIENT economic evidence unless independently resolved by later approved data work. Demo realism/latency/liquidation omissions remain disclosed even when other gates pass. |
| Activation | Always NOT APPROVED FOR EXECUTION. No active-model pointer, deployment, exchange inference or self-retraining. Truly untouched out-of-sample evidence and separate authorization are required for any later promotion. |

Thresholds are research choices for review, not statistical guarantees or industry safety standards. In particular, a 10% simulated drawdown gate does not establish real-account safety. Keep PASS, FAIL and INSUFFICIENT distinct. Never relax gates after seeing results.

## 10. Modular architecture — design and implementation boundary

```mermaid
flowchart LR
    DB[Saved SQLite: read only] --> DATA[Partition-restricted loader]
    DATA --> F[Causal features and baseline opportunities]
    DATA --> L[Isolated cost-aware labels]
    F --> S[UTC split and purge manifest]
    L --> S
    S --> M[Training-only scaler and logistic model]
    M --> P[Prediction and calibration report]
    M --> A[Offline admission adapter]
    A --> B[Unchanged historical simulator]
    B --> T[Baseline / ML / cash trading comparisons]
    P --> R[Immutable research report and decision]
    T --> R
```

The engineered loader/features/labels/splits/artifacts are now implemented and tested; see PROJECT_STATUS.md for evidence. Model fitting, classification/calibration evaluation, inference and promotion remain proposed and unimplemented. Current engineering uses only the standard library; ML dependency installation is deferred until separately approved fitting work.

| Design path | Responsibility |
|---|---|
| `src/demo_futures/ml_research/config.py` | Immutable experiment recipe, schema/horizon/split/cost digests, no Phase 1 Settings imports. |
| `src/demo_futures/ml_research/dataset.py` | Read-only SQLite access, quality/fingerprint checks, partition restrictions. |
| `src/demo_futures/ml_research/features.py` | Fixed close-time feature schema and availability metadata. |
| `src/demo_futures/ml_research/labels.py` | One-opportunity engine adapter, outcomes, maturity intervals and exclusion reasons. |
| `src/demo_futures/ml_research/splits.py` | UTC folds, both-symbol grouping, full-horizon purge and buffer. |
| `src/demo_futures/ml_research/model.py` | Training-only preprocessing/estimator, schema-checked offline predictions. |
| `src/demo_futures/ml_research/evaluation.py` | Classification/calibration versus priors; window-correct portfolio comparisons and stress. |
| `src/demo_futures/ml_research/artifacts.py` | Immutable manifests, explicit research-version loads, evaluation register/receipt. |
| `scripts/ml_research.py` | Explicit stages; no implicit fitting on import or default invocation. Final evaluation is separately locked. |
| `tests/test_ml_*.py` | New offline research unit/integration fixtures, no account actions. |

Engineering-only completion and exact tested paths are tracked in PROJECT_STATUS.md. The model.py and evaluation.py paths below remain proposed and absent. Opportunity enumeration, safety guards and audit reporting are additional engineering modules; they do not fit a model.

Artifacts go only to `artifacts/ml-research/<experiment-id>/` and `reports/ml-research/<experiment-id>/`, never original report paths. Experiment id derives from approved config, code/data fingerprints and stage. Save UTC boundaries, feature order/types, label validity/counts, model coefficients/intercept, scaler mean/scale, dependency versions, seed/thread settings, fold predictions, metrics, research-gate decisions and all attempted/resumed runs. A changed recipe gets a new id.

Store simple numeric model/scaler parameters in versioned JSON with strict finite-value/dimension/schema checks; do not load untrusted pickle/joblib blobs. Artifacts state OFFLINE_RESEARCH_ONLY and execution_enabled=false, with no automatically selected latest/active version. Features and labels are separate records keyed by symbol/decision time; label columns are not accessible to prediction adapters.

## 11. Required tests and incremental implementation after approval

1. Data/contracts first: read-only SQLite, input/frozen-source checks, feature schema and timing metadata. No fit yet. Test future perturbation/prefix equality, rejection of nonfinite/warm-up inputs, cross-symbol timestamp ordering and locked-period queries.
2. Labels/splits second: hand-calculated LONG/SHORT outcomes, adverse fills, fees/funding exactly once, ATR/risk fidelity, stop-first/gap/holding/daily behavior, next-candle timing, missing funding/horizons, and parity with unchanged engine. Test interval boundaries, embargo off-by-one cases, same-timestamp BTC/ETH grouping, no label across protected intervals, and training-only transformer row ids.
3. Run existing/new offline tests and review sample/split manifests before the first approved fit. Verify baseline source hashes and original journals remain identical. No parameter search to create a desired class balance.
4. Approved development fitting only: deterministic scaler/logistic model, majority/prior baselines, probability/schema checks, no fit during offline inference, calibration diagnostics and cloned-engine replay. Reject absent/failed artifacts and any attempted auto-activation. Report each fold and failures honestly.
5. Selection validation once under the frozen recipe, research-gate report and updated PROJECT_STATUS.md describing what was actually built. No final-period opening as part of this step.
6. Stop for separate final-evaluation approval. Execution/Phase 3 remains prohibited regardless of research results.

The original proposal stage had no new ML engineering test evidence. The approved engineering implementation now has a separate offline suite and development feature/label/split audit; current counts and artifact paths are recorded in PROJECT_STATUS.md. Engineering tests and sample sufficiency do not establish predictive/economic merit. Training, selection-validation evaluation, final opening and model activation remain unimplemented and unapproved.

## 12. Primary references and rationale

- [scikit-learn logistic regression](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.LogisticRegression.html): regularization and supported solver/API details. The proposed estimator is a simple explanatory baseline; its existence does not guarantee predictive value.
- [scikit-learn leakage guidance](https://scikit-learn.org/stable/common_pitfalls.html): fit transformations only on training data and use a pipeline. Our time/horizon restrictions are additional project-specific controls.
- [scikit-learn TimeSeriesSplit](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html): forward time splitting and a sample-count gap. Irregular candidate times and paired symbols require our proposed timestamp/label-interval splitter rather than treating an off-the-shelf row gap as complete purging.
- [scikit-learn probability calibration](https://scikit-learn.org/stable/modules/calibration.html): reliability and probabilistic scoring. Regularized logistic output must still be checked, not assumed calibrated.

These official sources support library behavior. Feature choices, UTC boundaries, label definition, extra four-hour buffer and numeric research gates are our proposed experiment design, not claims made by those sources. Existing engine code and saved project reports support the preserved financial assumptions and known data limitations. No Binance documentation or endpoint was contacted for this proposal.

## Current approval and next boundary

Review the fixed 16-feature schema, four-hour isolated cost-aware profitability target, UTC splits/purge/buffer, logistic recipe/admission threshold and numeric research gates. The current approval authorizes engineering implementation and development-only audits. Training and selection-validation evaluation require a further explicit approval; architectural approval alone does not authorize them. The final period remains separately locked; no approval here authorizes Phase 3, training during inference, model activation or any exchange action.

**Current boundary: complete approved engineering and development-only audits, then stop. Do not fit models or evaluate selection validation/final periods without further explicit approval.**
