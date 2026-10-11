# Research V2: independent offline opportunity research

Date: 2026-10-10. Refined after design review on 2026-10-10. **PROPOSED ONLY - NOT IMPLEMENTED - NOT APPROVED.**

This document is a research design, not a new experiment or a trading system. Approval to write it does not authorize code, labels, fitting, data collection or evaluation. All numbers and choices below are proposed for review. Existing Phase 4A features, labels, p>=0.65 threshold, models, risk settings, frozen simulator and journals remain unchanged. No locked selection-validation or final outcomes were opened.

Evidence: `docs/PROJECT_STATUS.md` and `reports/ml-research/development-diagnostics/report.md`, using previously saved development results. Historical coverage below comes from those documents, not a new database query. Risk evidence remains **NOT CLEARED**.

## 1. What the first experiment established

The fixed logistic regression did not demonstrate predictive or economic value:

- Only 2 of 1,331 development-window predictions reached p>=0.65 (0.1503%). Fold probability maxima were 0.4991, 0.9840 and 0.5332. Thus only fold 2 admitted trades.
- Across 1,325 valid scored labels, model log loss was 0.675798 versus 0.648350 for the training-prevalence predictor; Brier score was 0.236359 versus 0.227817. Lower is better for both metrics. Each fold underperformed that simple predictor.
- Both admitted trades were ETHUSDT LONGs, stopped within their entry candle. Their probabilities were 0.983985 and 0.962885, but combined net PnL was -95.47 simulated USDT. Ten and eleven of their fourteen continuous feature values exceeded pooled training ranges. Extreme feature values produced extreme logits, which the saved arithmetic checks reproduced.
- Removing those two rows does not remove fold 2's scoring deficit. Calibration and changing class prevalence show broader problems. A high estimated probability was not reliable evidence of a good trade.

The model learned coefficients connecting the old features to outcomes of *baseline-approved opportunities*. It never evaluated the entire opportunity space. Sparse admissions, extrapolation, weak calibration, overlapping examples and a short changing market period are plausible contributors; saved results do not identify one proven cause. Checks found no discrepancy in feature order, scaling arithmetic, probabilities, threshold decisions or trade accounting within their tested scope. This does not rule out every programming, data or simulation error.

Lower turnover reduced losses relative to the losing baseline, but did not beat cash economically. Two trades are insufficient evidence. This is a failed research hypothesis within the observed scope, not proof that a different model will work.

## 2. Independent decisions and the alternative hypotheses

Direct LONG/SHORT/NO TRADE prediction is scientifically useful if opportunities are scheduled independently of EMA/RSI/MACD filters and the labels, costs and evaluation are fixed before results are seen. The question becomes: can observable market information distinguish profitable actions from abstention?

However, a class label hides payoff size. Winning 60% of the time at +1 risk unit and losing 40% at -2 units gives an expected -0.2 units. Classification accuracy alone cannot identify an economic edge.

**Recommended first hypothesis:** estimate the net payoff of LONG and SHORT separately, then permit NO TRADE. This preserves payoff magnitude and makes the economic question explicit. A direct three-class classifier is an alternative requiring its own approval, not an extra experiment automatically added to this plan.

| Target | Benefit | Main limitation |
|---|---|---|
| Expected net return on entry notional | Comparable in basis points; directly includes costs | Different stop distances imply different risk per notional |
| Expected net payoff / planned risk budget (R) | Aligns with sizing and retains win/loss asymmetry | Funding can exceed the planned budget; heavy tails affect regression |
| Best realized action: LONG, SHORT or NO TRADE | Simple interpretation and familiar classification metrics | Discards magnitude; noisy hindsight winners can be hard to predict |
| Downside-penalized payoff or lower payoff quantile | Explicitly values downside | Additional target choices, more data and complexity; defer |
| Fixed-horizon net return | Simple financial calculation | Represents a different exit contract from the existing ATR simulator |

For the classifier alternative, label the better positive realized payoff as LONG or SHORT; label both non-positive payoffs, or an exact tie, NO TRADE. This hindsight answer is a training target only. It must never be used as an executable portfolio or a claimed achievable oracle profit.

## 3. Proposed opportunity and financial-label contract

Use BTCUSDT and ETHUSDT on saved completed 5-minute bars. Propose one decision per symbol per UTC hour, using the candle that closes immediately before the hour. This reduces duplication and compute; it can miss shorter opportunities. This new cadence is a V2 hypothesis, not a change to the frozen baseline.

Require a common 200-bar contiguous completed warm-up. Enumerate both actions without the old strategy's eligibility filters. For each decision, simulate one isolated LONG and one isolated SHORT from separate fresh 10,000-USDT reference accounts, with next-candle-open entries. They are counterfactual alternatives, not simultaneous real positions.

Reuse the verified financial assumptions without editing their implementation: ATR14, 2-ATR stop, 3-ATR target, maximum 48 five-minute bars (four hours), planned risk 0.5%, leverage cap 2x, existing quantity/price rules, fee 0.0005 per leg, slippage 0.0002, funding reserve 0.001 and actual available historical funding debits/credits under the existing conservative rules. Count each cost once. Apply the simulator's existing stop-first ambiguous-bar and adverse-fill rules.

Proposed primary targets are each action's net PnL divided by the reference planned risk budget (50 USDT), with cash payoff zero. R is a normalization, **not a guarantee that losses cannot exceed 1R**. Keep overruns as observed losses and risk flags; do not rewrite labels to fit the budget.

An isolated label starts with fresh daily-loss state and no other positions. Its eligibility therefore differs from a shared account with depleted equity, a daily halt or a conflicting BTC/ETH position. Labels measure isolated opportunities; realized portfolio evaluation must enforce the shared account's daily state and one-position limit. Summing isolated payoffs is not a portfolio backtest.

Require both action outcomes to be financially valid for the initial paired regression. Unknown funding, non-executable quantity, candle gaps or incomplete horizons are exclusions with reasons, never automatic NO TRADE labels. Reserve the full four-hour label interval even if a simulated trade exits early. Decisions at a period boundary need their entire horizon inside that period.

Portfolio decisions must not use future label-validity flags. Score every causally eligible scheduled decision, then apply information actually available at each simulated execution step. If an admitted exposure later encounters missing funding, its complete cost result is INSUFFICIENT; retrospective deletion cannot establish profitability.

The proposed V2 action rule is to select the larger predicted net R only when it is positive; otherwise choose cash, with exact ties also cash. This zero-payoff decision rule is separate from V1's unchanged p>=0.65 filter and is not a confidence guarantee. No threshold sweep is authorized.

Propose a fixed abstention rule if any continuous input falls outside that fold's training minimum/maximum. Learn bounds only from training. This addresses the observed extrapolation risk but can reject useful new regimes; expanding folds also change coverage. Report abstentions and their coverage explicitly. Do not alter bounds after inspecting results. This choice was motivated by inspected development evidence and therefore needs fresh confirmation.

### Funding completeness, labels and comparable portfolios

In a later approved V2 audit, establish a settlement-coverage inventory for each symbol/holding interval: UTC event times, signed rates and required price/notional inputs. Candle coverage does not prove funding completeness. Do not assume a permanently fixed settlement cadence or treat an absent record as zero. If the applicable schedule or a required settlement cannot be established, mark funding UNKNOWN with its interval and reason.

A complete, reconciled loss exceeding the funding reserve remains a valid negative payoff label. Keep the full loss and budget-breach flag; never cap at -1R, drop it as an outlier or relabel it NO TRADE. Such a label can inform separately approved research but cannot establish risk clearance. The reserve is a sizing allowance, not another charged funding settlement: actual funding must not be charged twice.

If either action has incomplete funding, its exact payoff is unavailable. Exclude the paired row from fitting/exact-label scoring, retain original records and known costs, and report missingness by fold, symbol and UTC period. Never invent funding or substitute zero. Describe exclusion-related selection bias. This future-label exclusion must never become a portfolio entry filter using information from after the decision.

Apply identical known settlements and frozen financial rules to compared portfolios. Preserve conservative simulator outputs but mark them partial/assumption-dependent where funding is uncertain. If any compared trading policy holds exposure through an unresolved settlement, exact economic ranking for that common window is INSUFFICIENT. Cash still has verified zero trading payoff, but uncertain trading results cannot establish superiority to cash or baseline. Do not delete affected trades or choose an easier window. Default/stress retain existing contracts unchanged; disclose fee/slippage/reserve settings and actual settlement treatment separately.

## 4. Minimal causal inputs and point-in-time requirements

Propose eight continuous features plus one ETHUSDT indicator, shared by the two payoff outputs:

| Feature | Definition at the completed decision close |
|---|---|
| Log returns over 1, 12 and 48 bars | Three backward-looking close-to-close returns |
| Recent return volatility | Population standard deviation of the last 48 completed one-bar log returns |
| Relative ATR | ATR14 divided by current close |
| Relative candle range | (High - low) / close |
| Relative candle body | (Close - open) / close |
| Relative volume | log(1 + current volume / mean of preceding 20 bars), excluding current bar from denominator |
| Symbol indicator | ETHUSDT=1; BTCUSDT=0 |

These are a proposed separate nine-feature V2 schema. The existing sixteen-feature schema stays untouched. No indicator shopping or feature selection follows evaluation. Keep transformations and units explicit, with no future-filled values or outcome-derived inputs.

Use UTC candle close times and distinguish event time from availability/receipt time. Store source, retrieval time, immutable snapshot hash and revisions; a subsequently corrected historical bar is not proof of what a live decision would have seen. Completed-candle values are a documented historical approximation where receipt histories are absent. Require contiguous warm-up, valid OHLC and a positive prior-volume denominator; propose rejecting zero-range/zero-volume decision bars as an objective data-quality rule while preserving raw records. No forward/backward filling through gaps.

Funding is a label cost, not a feature until historical as-of availability is demonstrated. Historical open interest, order books and announcements must not be reconstructed from present snapshots. Fit scaling and bounds on training only; [scikit-learn's leakage guidance](https://scikit-learn.org/stable/common_pitfalls.html) explains this separation.

### Fixed training-only bounds and abstention sufficiency

For each fold, use exactly the post-purge/post-buffer finite, valid paired training row IDs used to fit the model. For each of the eight continuous features j, calculate L[j]=minimum(raw x[j]) and U[j]=maximum(raw x[j]), pooled across BTC and ETH. Use raw feature units before scaling, not symbol-specific bounds or percentiles. Constant features have equal bounds. Equality is accepted; any value below L or above U requires abstention. No padding, evaluation-derived tolerance, clipping or retrospective widening. Validate the binary symbol flag against its schema separately.

Freeze bounds, feature definitions, training counts, row-ID hashes and UTC range with the fold artifact. Recalculate only from each next fold's own expanding training partition. Invalid/nonfinite features are data-quality rejections, reported separately from range abstention.

Report abstention counts/rates by fold, symbol and fixed non-overlapping seven-day UTC blocks anchored at evaluation start, including the last partial block. Show per-feature breaches and joint abstentions without double-counting a row. The denominator is all causally feature-eligible scheduled decisions, including decisions with unavailable future labels. Also show total scheduled decisions, causal exclusions, in-range coverage, valid labels and executed trades. Future-label exclusions must not shrink this denominator.

Proposed hard sufficiency rule: out-of-range abstention greater than 25% overall in any fold, for either symbol in a fold, or in any symbol/seven-day block with at least 50 eligible decisions makes coverage INSUFFICIENT. Smaller blocks are reported as too small to assess independently, not passing. The original evaluation minimums (300 valid paired rows, 100 per symbol, 60 joint non-overlapping four-hour groups) must also hold in the in-range subset. Apply these gates to confirmation/final windows too. These are fixed proposed gates awaiting approval, not active settings or measured results.

Report prediction diagnostics on all finite scored rows with valid labels, and the in-range subset separately; abstention must not hide prediction errors. Do not widen bounds, lower minimums or slide dates after seeing outcomes. New regimes are limitations on training support, not automatic model success or failure. A different bounds policy requires a new approved recipe and fresh confirmation.

## 5. Is the existing dataset enough?

Saved documentation reports 25,920 five-minute candles and 268 funding records per symbol, covering 2026-07-11 06:50 through 2026-10-09 06:49:59.999 UTC. Development covers July 11 through August 31 exclusive, with 14,606 bars and 151 funding records per symbol. Documented problems include funding gaps, timestamp jitter, zero-range/zero-volume candles and extreme Demo prices. These are prior metadata, not newly verified coverage.

Ninety days would provide at most about 4,320 hourly paired decisions across two symbols before exclusions. Two actions per decision are correlated, not two independent samples. Shared market shocks and overlapping four-hour labels reduce effective sample size further.

The dataset can support engineering and explicitly approved exploratory development. It is insufficient for credible independent confirmation of a design motivated by its own diagnostics. Parts of the old final period were already examined in baseline research; relabeling that period does not create a fresh holdout. Existing locked ML periods remain locked.

Additional data that would improve credibility:

- Longer, newly reserved Demo history spanning different trends, volatility and funding regimes; aim for at least six months, preferably six to twelve, without claiming calendar duration guarantees statistical power.
- Complete public Demo funding settlements, coherent candle timestamps and documented instrument/cost assumptions; more rows cannot repair systematically unrealistic data.
- Prospective public Demo snapshots with receipt times and, if available, contemporaneous spread/mark-price information to assess fill and funding assumptions.

Historical availability must be checked only under separate collection approval. Demo retention may prevent this plan; do not silently substitute production data. More Demo data still cannot establish production-market representativeness. No authenticated collection or credentials are needed or approved here.

### Newly retrieved history is not prospective evidence

Newly retrieved historical data describes events before the recipe freeze or first observation. Downloading it now changes retrieval time, not event time. Even history never opened by this project may have influenced design through published charts or earlier research. Record event/retrieval dates and prior inspection separately. It may support development or an explicitly reserved retrospective test; it is not genuinely prospective evidence.

Genuinely prospective, previously unobserved data concerns events occurring after the relevant recipe and evaluation calendar are frozen. Archive observations as they arrive with event/receipt times and immutable versions; protect confirmation/final outcomes until their approval gates. After a recipe change, only outcomes after the new freeze can be prospective confirmation of that revised recipe. Previously observed dates never become fresh again.

**Availability is NOT VERIFIED in this task.** No Binance lookup, request or market-data access was performed. Later, with explicit public-data availability/collection approval, review current official Demo documentation and the existing public-only client allowlist; verify origin, public routes, pagination, limits and funding semantics before requesting anything. Use small bounded public GET probes near preregistered candidate dates for both symbols and funding, then an authorized coverage inventory. Record requested/returned times, earliest/latest completed records, truncation, gaps, timestamp consistency and settlement completeness. Probes retrieve data and themselves require approval. A successful recent request cannot prove 180-day coverage. No credentials, authenticated routes or production fallback.

If 180 suitable Demo days are unavailable, record DATA AVAILABILITY INSUFFICIENT and pause fitting/confirmation. Seek separate approval to accumulate prospective Demo observations under the fixed calendar, or conduct a clearly exploratory fixed-date pilot using only explicitly authorized development data. A pilot cannot satisfy the 180-day confirmation design or support deployment claims. A shorter design requires a new proposal, sample/power justification and approval before its outcomes are inspected. Do not silently shorten/slide splits, substitute production data, or reopen/retrieve replacements for old locked periods.

### Separate future-expansion data-only scope - 2026-10-11

The user separately approved public Demo availability checks and bounded historical collection for SOLUSDT, BNBUSDT and XRPUSDT as future-expansion DATA ONLY. BTCUSDT and ETHUSDT remain the ONLY active symbols in this proposed V2 recipe. No additional symbol encoding, nine-feature change, targets, risk settings, model or training/evaluation calendar is approved by that data task.

Narrow public ingestion support and synthetic/mock tests were added independently of V2 engineering. The actual attempt passed Demo server time but stopped after three public exchange-metadata network failures. No contract/history availability was verified and no symbol datasets were collected. See `reports/future-expansion/future-data-20261010T222338Z-be582410/report.md` and the current status for exact evidence.

If a later authorized attempt retrieves history, it remains historical future-expansion inventory, not prospective confirmation or automatically eligible research data. The hybrid historical-development/prospective-confirmation option above still requires its own explicit design/calendar approval. This data-only request neither approves a hybrid schedule nor unlocks old evaluation periods. The original 120/30/30 and three-fold design remains a proposal, unchanged. V2 engineering/fitting/evaluation remain unapproved and risk remains NOT CLEARED.

## 6. Chronological design and protection of evaluation data

The preferred proposed plan is 180 genuinely prospective days after the complete V2 recipe freeze: first 120 days development, next 30 days one-time confirmation, final 30 days sealed final evaluation. Preregister exact UTC boundaries before the first observation; historical metadata informs feasibility but cannot turn past dates into future events. A hybrid of newly retrieved history for development and prospective confirmation/final data is a separate schedule requiring design approval, provenance and exclusion of old locked periods. If development causes a recipe change, reserve new future confirmation/final boundaries after that new freeze. Availability, quality or sample failure means INSUFFICIENT; do not slide dates to manufacture samples or performance.

Three expanding development folds: train first 60 days, evaluate next 20; train first 80, evaluate next 20; train first 100, evaluate next 20. Keep both symbols and both action labels from each decision timestamp in the same partition.

Purge any training row whose conservative label-end time is later than evaluation start minus four hours. This leaves an additional four-hour buffer after its complete four-hour label interval. Require evaluation label intervals to end within the evaluation window. Use timestamp intervals, not an assumed number of rows: missing bars and paired symbols make a row-count gap unsafe. [TimeSeriesSplit](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html) supplies expanding splits and a row gap, but does not implement this paired interval contract automatically.

Outer folds never train on future rows. If a future separately approved inner validation scheme permits data on both sides, purge overlap and embargo at least four hours after its evaluation interval too. No such inner model selection is in this initial proposal. Train preprocessing, bounds and model parameters exclusively on each fold's training partition.

Report paired chronological loss differences with UTC-day block uncertainty and a fixed four-hour non-overlapping diagnostic subset. Show raw and effective counts; intervals conditional on three fitted models are not evidence about every possible retraining. Blocks across only a few days provide weak uncertainty estimates.

Maintain an experiment registry including rejected ideas, inspected dates, hashes and failed gates. Old inspected development evidence is exploratory. Never rename an old holdout as a fresh test. After inspecting confirmation, any recipe change consumes it for that design; subsequent confirmation needs newly reserved data. Opening confirmation and then final outcomes each requires explicit approval. No old locked outcome is needed for this proposal.

## 7. Simple benchmarks, comparisons and proposed gates

Start with one two-output regularized linear model: standardize eight continuous inputs, pass the symbol flag unchanged, and fit multi-output Ridge with alpha=1, intercept enabled and SVD solver. One fixed fit per development fold means **three fits total**, not a search. [Ridge documentation](https://scikit-learn.org/stable/modules/linear_model.html) describes its squared-error objective and L2 penalty. Linear coefficients are inspectable but do not capture every nonlinear relationship; heavy payoff tails are a known weakness.

Use zero-payoff predictions and each action's training-mean payoff as predictive baselines. Use cash NO TRADE and the frozen strategy as economic baselines. A fixed L2 multinomial logistic model is a separately approved alternative, followed only with evidence by robust/quantile or more complex models. No neural network, GPU or automated optimization is justified initially.

Regression evaluation: MAE and MSE per action, mean prediction bias, realized payoff by fixed predicted-payoff buckets, tail losses, range-abstention coverage and uncertainty. Regression payoff reliability is separate from classification probability calibration. If the classifier alternative is approved, report class counts, log loss, Brier score and calibration as well as payoff asymmetry.

Portfolio comparisons use identical evaluation dates, starting capital, data, warm-up, cutoff, costs and frozen risk rules. Preserve the frozen baseline's original five-minute decision cadence; explicitly report its cadence difference from the proposed hourly policy. Use the existing deterministic symbol priority and shared position/daily-loss gates. Model outputs never override sizing or risk. Compare default and doubled fees/slippage/funding-reserve stress with the same predictions and no refitting; stress sizing may differ under the existing cost contract. Report actual funding-cost treatment separately, not an unexplained doubling of every cash flow.

Proposed hard gates, to approve before implementation/results:

- Per fold: at least 1,000 valid paired training decisions, including 300 per symbol; at least 300 valid evaluation decisions, including 100 per symbol and 60 jointly grouped non-overlapping four-hour decision groups. A classifier alternative additionally requires at least 40 training and 20 evaluation examples per class.
- Predictive evidence: pooled development MAE at least 1% better than training means for each action, with MSE no worse; later independent confirmation must support an improvement under the preregistered uncertainty analysis. Wide intervals or failed minimums mean INSUFFICIENT, not permission to adjust splits.
- Economic evidence in each later confirmation/final window: at least 50 closed trades across ten entry days, positive net PnL exceeding both cash and frozen baseline, profit factor at least 1.1, maximum drawdown at most 10%, and positive doubled-cost net PnL. Report all development folds rather than selecting the best.
- Risk: unresolved budget breaches or unknown costs prevent clearance irrespective of profit. A performance gate cannot override **NOT CLEARED**.

These conservative research gates are provisional and are not power calculations or execution certification. Failing a gate is a valid result. Enough rows alone does not make a hypothesis credible.

### Extreme payoffs and predictions

Proposed audit rules do not authorize winsorization or new risk settings. For each action report finite label count, min/max, mean, median, standard deviation, P1/P99, signed tails, cost components and overlapping interval clusters. Flag |realized R|>3 for mandatory review, and evaluation targets outside that action's training min/max. Training distribution summaries use training only. The fixed 3R flag is an audit trigger, not a loss cap or label-deletion rule.

Trace extremes to entry/exit timing, next-open execution, OHLC assumptions, quantity/filter rounding, fees, slippage, funding and net-PnL reconciliation. Genuine large gains/losses stay in original data and primary metrics. Inconsistent arithmetic is FAIL; unresolved explanations or inputs are INSUFFICIENT pending review. Neither permits editing labels. Genuine adverse tails may fail risk gates while passing arithmetic validity.

Report predicted-R distributions by action/fold/symbol. Nonfinite predictions are a numerical-validity FAIL. Flag finite |predicted R|>3 and predictions beyond that action's training-target range; verify stored feature order, training-only scaler, coefficients and manual arithmetic. Finite extremes can reflect extrapolation or poor specification rather than a programming error. Unresolved flags prevent a research PASS. Do not clip, recalibrate, change the positive-payoff threshold or refit in response. An audit flag does not silently become a new trading rule.

Positive predicted mean payoff is not sufficient evidence about downside tails, uncertainty, correlated exposure, funding completeness or operational safety. Every action still faces the frozen risk gates; unresolved funding findings independently block risk clearance.

Prediction metrics assess isolated LONG/SHORT targets at scheduled decisions: MAE/MSE, bias and payoff-bucket reliability. Economic metrics assess a changing shared account: net PnL, costs, turnover, win rate, profit factor, drawdown and daily halts. Position conflicts, equity-based sizing and rejected entries prevent translating regression error directly into portfolio profit. Keep full valid-row and in-range prediction metrics distinct from executed trades. Two correlated counterfactual actions do not count as independent evidence.

### Prevent acceptance based on a few lucky wins

Keep all primary outcomes and all three folds visible. Report top one/three/five wins' shares of total positive trade PnL and of net PnL when net is positive, plus concentration by symbol, UTC day and overlapping four-hour intervals. Break tied trade-PnL ranks by entry time, then symbol, deterministically.

Proposed additional safeguard: if the top three wins account for at least 50% of total positive trade PnL, or recorded net trade PnL excluding those wins is non-positive, economic evidence is INSUFFICIENT. Apply to pooled development and independently to each confirmation/final window alongside original trade/day minimums. With no wins the concentration ratio is undefined; sufficient observations with non-positive performance FAIL the performance gate. Inadequate counts remain INSUFFICIENT.

Top-three exclusion is arithmetic sensitivity on the eventual saved ledger, not a new simulated policy: decisions, equity and sizing would differ without those trades. It must not replace the full result, justify removing labels, select the best model/fold or claim an achievable alternate return. Retain paired UTC-day block uncertainty; inconclusive intervals remain INSUFFICIENT. Do not optimize exclusion counts, concentration cutoffs or bucket boundaries using evaluation outcomes.

## 8. Risk limitations remain blockers

The frozen limits remain planned risk 0.5% per trade, leverage 2x, daily loss halt 2%, one shared position and no Martingale or uncontrolled increases. Stops, daily halts and modeled costs cannot guarantee realized loss caps under gaps, funding or uncertain fills.

Prior evidence identifies five BTC isolated labels losing about 64.24-79.15 USDT against a 50-USDT planned budget. Funding debits were about 21.55-43.75 against reserves of 7.20-14.58. These overlapping cases reflect two LONGs around July 20 and three SHORTs around August 3, not necessarily five independent funding events. Existing accounting reconciled the excess with actual funding; labels must remain intact.

Keep this issue visible in targets and portfolio reports. A future funding-aware sizing/reserve correction would require a separately reviewed, versioned risk change and new experiment; it must not overwrite old evidence. This proposal authorizes no correction. Risk evidence stays NOT CLEARED even if future predictions improve.

OHLC fills, historical instrument filters, Demo spikes, missing funding and lack of liquidation modeling limit conclusions. Actual isolated-margin configuration, exchange protective orders, reconciliation and operational kill switches remain unimplemented. Offline abstention is not an exchange kill switch. No execution approval follows from research performance.

### Separate PASS, FAIL and INSUFFICIENT evidence

| Evidence | PASS in its limited scope | FAIL | INSUFFICIENT |
|---|---|---|---|
| Financial-label integrity | Complete inputs and reconciled costs, including genuine overruns | Demonstrated arithmetic/timing error | Unknown funding/input or unexplained extreme |
| Prediction | Predefined improvement supported by adequate coverage, samples and uncertainty | Adequate evidence misses performance gate | Missing targets, excessive abstention, insufficient rows or uncertainty |
| Shared-portfolio economics | Complete comparable costs and all performance/concentration gates supported | Adequate complete evidence misses performance gate | Unknown exposed funding, too few trades or outlier-dependent result |
| Risk | No unresolved breaches and relevant controls verified | Demonstrated risk-budget or control breach | Required safety evidence absent or unresolved |

Report dimensions together. Financial reconciliation never means acceptable risk. When missing evidence and known failures coexist, retain both rather than using INSUFFICIENT to hide a measured loss or breach. The five historical overruns remain adverse findings in unchanged V1 evidence; no new V2 labels or risk results were produced here. **Overall risk remains NOT CLEARED; no overall acceptable-system PASS or activation is possible under current evidence.**

## 9. Incremental plan, approvals and compute budget

| Gate | Work only after separate explicit approval | Exit evidence |
|---|---|---|
| A: design | Review targets, nine features, cadence, bounds, gates and dates | Frozen preregistration; this document alone is not approval |
| B: engineering | Separate V2 loader/schema, causal features, paired labels, interval splits and artifact registry; synthetic-first tests | Timing, financial parity, gap/funding, train-only transform, lock protection and determinism audits; no fitting |
| C: data | Check and collect explicitly authorized public Demo data, then quality-audit immutable snapshots | Coverage/availability and exclusions; insufficient data stops the plan |
| D: development | Exactly three fixed Ridge fits and chronological portfolio comparisons | All gates, baselines, uncertainty, cost/risk flags and hashes; no selection/final access |
| E: confirmation | One locked confirmation evaluation after development review | Independent results; recipe changes require new confirmation data |
| F: final | One sealed final evaluation after another approval | Research conclusion only; no deployment or Phase 3 |

Engineering approval does not imply collection or fitting approval. Reading existing development data for V2 also requires explicit scope approval. Keep proposed modules in a separate `research_v2` namespace and artifact tree rather than extending the V1 reader into locked periods. Reuse frozen financial components through a reviewed adapter; tests must show no baseline behavior change. No automatic model activation, self-learning or pipeline that silently opens later periods.

Estimated local work, **not benchmarked**: synthetic tests seconds to minutes; saved-data preparation about 1-10 minutes; three small CPU fits seconds to approximately one minute; isolated label generation and portfolio replays about 5-30 minutes for 180 days, depending on implementation. Collection latency/retention is unknown. Plan below 1 GB working memory, no GPU and reuse of the pinned research environment only after compatibility review; no dependency installation now.

At 180 days, two symbols imply roughly 103,680 five-minute bars, 8,640 hourly paired decisions and 17,280 isolated action simulations before exclusions. At about 49 bars per action this is approximately 846,720 bar steps, not independent observations. A small approved engineering benchmark should replace these estimates before any long run. The initial fitting budget stays three primary fits, with no parameter/seed search.

## 10. Deliverables and present approval boundary

The original design task and this documentation-only refinement changed only this proposal and `docs/PROJECT_STATUS.md`. No V2 code, features, labels, data, models or results exist. Existing source and explicitly protected V1 artifact/report hashes were checked for equality across the documentation change. No database, credential, network or locked-outcome access occurred. Documentation checks are not software test execution; historical test results remain historical.

Share this proposal and the current project status for independent review; the saved development diagnostic is the supporting evidence. The next decision is whether to approve this design or revise its explicit tradeoffs. Coding, training, collection and later-period evaluation each remain unapproved. **Stop here and wait for explicit approval.**
