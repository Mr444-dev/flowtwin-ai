# Model Card: FlowTwin AI

## Summary

FlowTwin predicts the number of **calendar hours** from an observed process prefix to the last observed terminal event in a completed BPI Challenge 2017 application trace.

## Intended use

- A reproducible portfolio example of predictive process monitoring.
- Retrospective exploration of one anonymized historical event log.
- Demonstrating chronological validation, baseline comparison, case-weighted metrics, and prefix replay.

## Out-of-scope use

- Credit approval, offer selection, customer eligibility, or credit scoring.
- Staff scheduling, customer contact, SLA enforcement, or operational decisions.
- Claims about current bank operations or the institution represented by the dataset.
- Causal conclusions or what-if simulation.

## Data and population

The source is the public BPI Challenge 2017 loan-application event log from 4TU.ResearchData. One trace is treated as one application. Regression uses only complete traces under the documented terminal-activity heuristic and traces with at least two usable events. This selects cases that reached a recognized ending; it does not estimate time-to-resolution for all still-open cases.

The log is historical (2016–2017). Its current availability and license terms must be checked at the source record before reuse. The project does not include the source log.

## Features

Features include current activity, observed prefix length, elapsed calendar time, time since the previous event, activity-family counts, selected application attributes, and offer attributes only after they appear in the timestamped prefix. Trace-only offer attributes without an observation time are excluded. The event-level availability assumption still needs inspection against the actual XES source before using measured results.

## Training and evaluation

- HistGradientBoostingRegressor with absolute-error loss.
- Prefix checkpoints at 1, 3, 5, 10, 20, and 40 observed events when a later event remains.
- Chronological train/validation/test cutoffs derived from case start times; cases crossing a cutoff are excluded from the corresponding window.
- Each case has equal total training and evaluation weight, shared across its available checkpoints.
- Baseline: training-set median remaining time for the current activity, with a global case-balanced fallback.
- Main metric: case-weighted MAE in hours. The test report also includes median and 90th-percentile absolute error, RMSE, a case-level bootstrap interval, interval coverage and width, and stage metrics.
- The 90% interval uses a validation residual quantile; it is empirical and can lose coverage under process drift.

## Limitations and risks

- Performance is not currently established: the official source could not be downloaded in the authoring environment, so no real-data model score is published.
- The terminal list and attribute availability rules are explicit heuristics. Their actual frequencies and semantics must be validated on the source log.
- Completed-case-only training has selection bias and does not solve right-censoring statistically.
- A single chronological holdout cannot establish robustness across process changes. Rolling-origin evaluation and a later-period external test would be stronger.
- Checkpoint evaluation covers six event counts. The dashboard can replay other prefixes; those intermediate predictions are not separately represented in the reported test metrics.
- No fairness, subgroup calibration, or sensitive-feature ablation has been run. This model must not inform credit decisions.
- This historical offline replay has no live event stream, synchronized state, or validated simulator.

## Human oversight

Treat every output as an exploratory estimate. Inspect the history, compare against the baseline, review uncertainty, and do not use the forecast to make a consequential decision about a person.
