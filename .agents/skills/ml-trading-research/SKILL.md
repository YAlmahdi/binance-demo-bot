---
name: ml-trading-research
description: "Develop and audit interpretable trading ML experiments, point-in-time features, chronological walk-forward evaluation, and model promotion evidence. Use for research and model review, not automatic deployment or retraining during execution."
---

# Ml Trading Research

## Purpose and use

Evaluate whether a simple predictive model adds value beyond the indicator baseline and no trading. Review existing research and data availability first. No ML engine exists in phase 1; do not create one merely because this skill is installed.

## Safety rules

- Only Binance USD-M Futures Demo; prohibit production execution endpoints and live trading modes.
- Do not read credential files, `.env`, secret environment values, or private keys. Never print, partially expose, copy, upload, or request API secrets. Training and evaluation must operate offline without keys.
- Keep training, test evaluation, paper simulation, and Demo execution separate. No orders or network order-validation calls during setup.
- Do not self-train or modify a running model during trading. Reject deployment/promotion unless an untouched out-of-sample dataset passes predefined performance and risk gates. Insufficient evidence means keep the model inactive.

## Engineering instructions

1. Specify the prediction target, label horizon, decision time, cost assumptions, and feature availability before fitting. Use logistic regression or another simple interpretable baseline before deep models.
2. Use only values known at decision time: closed candles, causal indicators, and funding/OI available by that time. A current OI snapshot cannot reconstruct the past. Keep future-dependent labels isolated from feature construction.
3. Use chronological outer walk-forward folds. Purge training labels whose horizons overlap the evaluation interval, and add a justified gap/embargo when needed. Do not shuffle temporal samples.
4. Fit scalers, imputers, feature selection, calibration, thresholds and hyperparameters only on training/inner validation data for each fold. Rebuild the full pipeline per fold. Keep the final holdout untouched until the experiment is frozen.
5. Evaluate prediction metrics/calibration and cost-aware trading outcomes using the same simulator and risk rules as the baseline/no-trade policies. Summarize each fold as well as aggregate results, cost stress and drawdown. Log all tried experiments to expose selection bias.
6. Save immutable model/pipeline versions, feature schema, data hashes, UTC split boundaries, label horizon, library versions, seed, metrics, and promotion decision. Never load an untrusted serialized model.
7. Define numerical gates before evaluating: minimum independent observations/trades, net performance versus both comparators, maximum drawdown, risk-limit breaches, and cost sensitivity. If thresholds are not agreed, produce a research candidate marked NOT APPROVED; never invent permissive gates after seeing results.
8. A passing model remains a candidate until explicitly activated in the reviewed Demo inference configuration. Inference cannot call fit, select a new version automatically, or rewrite the approved artifact.

## Required tests

Test feature causality by altering future rows; higher-timeframe as-of joins; disjoint/purged label ranges; per-fold transformer fitting; reproducibility; feature schema mismatch; probability bounds/calibration; missing/stale input rejection; failed and absent promotion evidence; and inference refusing unapproved model versions. Keep training tests offline.

## Acceptance criteria

Reproducible saved experiment, no leakage in tested boundaries, out-of-sample baseline comparisons and costs, interpretable model explanation, and explicit PASS/FAIL/INSUFFICIENT evidence against predeclared gates. No promotion on training scores alone, too-small samples, or a failed risk gate. Report uncertainty; no guaranteed returns.

## Common mistakes

Random train/test splits; fitting a scaler before splitting; selecting thresholds on the final holdout; overlapping forward-return labels across folds; overclaiming confidence from raw probabilities; comparing policies over different periods; repeatedly reusing the holdout; automatic online retraining or swapping artifacts during execution.
