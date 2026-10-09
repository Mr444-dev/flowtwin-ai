# Methodology and repository audit

## Overall assessment: Needs revision for data-backed claims

The project is now structured as a reproducible portfolio repository with method documentation, CI, safety checks, and synthetic training/API smoke tests. The analytics should **not** be presented as validated yet: the official event log was not downloaded in this environment, so the real model was not trained and no real-data metric was computed. This assessment separates code checks from evidence about the model.

## High-priority findings

### 1. Future-informed sampling — fixed in this revision

The previous trainer selected snapshots at percentages of each completed trace's final length (20%, 50%, 80%). That indirectly exposed final trace length through the observed prefix size and meant evaluation did not match an online forecast moment. It could make the reported score optimistic or otherwise misrepresent the dashboard use case.

**Fix:** snapshots now use fixed event counts (1, 3, 5, 10, 20, 40), and stage labels depend only on observed events. A regression test checks the policy.

### 2. Unequal case influence — fixed in this revision

Cases with more eligible checkpoints previously contributed more training rows and more weight to MAE, baseline medians, and interval coverage. Prefixes from a single case are correlated.

**Fix:** each case has total weight 1, divided across its checkpoints. Reported overall error, weighted quantiles, interval coverage/width, and baseline population now use case-balanced logic. Stage MAE and calibration summarize checkpoint errors per case before averaging. The bootstrap resamples per-case mean errors.

### 3. No real-data training or metric — unresolved blocker

The official download failed from this environment with DNS resolution error (`getaddrinfo failed`). The local runtime also lacks scikit-learn, pandas, and NumPy, so it cannot execute model fitting or the HTTP app. Of 29 discovered tests, 25 dependency-light tests pass and four model/API integration tests are skipped locally; they do not establish MAE, interval coverage, baseline lift, or real-data parsing quality.

**Required evidence:** download the official source, verify the published checksum, run download → prepare → train, inspect `reports/generated/metrics.json` and `test_predictions.csv`, and retain no score in the README until that run succeeds.

### 4. Completion and censoring are heuristics — unresolved data validation

The end-of-case label is derived from a short explicit terminal-activity list. This can misclassify traces if the last event is an offer-level outcome, the process continues outside the log, or the log is truncated. Training only on recognized completed traces can select a non-representative population.

**Required check:** after the source is available, count cases by last activity, inspect terminal sequences, compare trace ends to the log's observation cutoff, and reconcile labels against the challenge documentation. Report completed, censored, excluded, and too-short case counts by time window.

### 5. Attribute timing and sensitive features — unresolved data validation

Application-level fields are assumed available at case start; offer-level values are admitted only when present on a timestamped event. The raw XES encoding may still repeat values before they are truly operationally known. Credit score and offer terms can be sensitive or outcome-adjacent attributes.

**Required check:** inspect actual event/trace placement and first-observed timestamps. Report a feature ablation without credit score and offer attributes, and do not position this as a credit decision model.

## Medium-priority findings

### 6. One chronological holdout

One train/validation/test cut is better than random row splitting but gives a single estimate in a historical process. It does not show how metrics vary across dates or concept drift.

**Improvement:** add rolling-origin evaluation and report metrics by period. Keep a final untouched period for the headline result.

### 7. Checkpoint-only evaluation, free-form replay

The reported metrics use six fixed event counts, while the slider can show a prediction at any prefix. The in-between prediction can be useful interactively, but is not represented in the test score.

**Improvement:** either align replay controls to the trained checkpoints or add a separate dense-prefix evaluation and label both clearly.

### 8. Empirical prediction interval

The symmetric interval uses a validation quantile of absolute residuals. This is easy to explain, but it is not a guarantee under drift, and a single radius can hide different error profiles by stage.

**Improvement:** report stage-level coverage and width (now included in the JSON output), retain the test-only audit, and consider a formally specified conformal method after confirming its sampling assumptions.

### 9. Reproducibility and product testing

Dependencies use version ranges rather than a lockfile. API and training tests are now included as CI smoke tests using synthetic fixtures; they were skipped locally because the current runtime lacks the model dependencies. CI has not yet run on GitHub.

**Improvement:** review CI status after the first push, pin a tested dependency set/lockfile, and add a real-data smoke run outside the unit-test job when the source is accessible.

## Checks completed here

- 25 of 29 discovered tests passed locally; four tests requiring model/API dependencies were skipped. The passing tests cover prefix features, fixed checkpoint policy, weighted quantiles, XES parsing and hardening, downloader integrity, and spreadsheet-safe CSV values.
- `python -m compileall -q src tests` completed successfully.
- Full model fitting, HTTP API integration, dashboard rendering, and original-data validation remain unverified locally.

## Release gate

This is suitable to publish as **code for review and testing**, with the unverified status visible. It is not ready to publish numeric model-performance claims. Before claiming predictive value, attach the generated metrics and predictions from the original log, validate the completion/attribute assumptions, review stage and time-slice errors, and confirm the model beats the case-balanced baseline on the untouched chronological test set.
