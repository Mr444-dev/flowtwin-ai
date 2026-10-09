# FlowTwin AI

**FlowTwin AI** is a portfolio prototype for predictive process monitoring. It estimates how much calendar time may remain in a loan application after observing part of its event history, then compares the ML model with a simple activity-median baseline.

[Dataset notes](DATASET.md) · [Methodology audit](AUDIT.md) · [Model card](MODEL_CARD.md)

The demo uses the public **BPI Challenge 2017** event log. It runs locally, downloads the source data from 4TU.ResearchData, validates the compressed file, streams the XES records into SQLite, trains a regression model, and starts an English-language dashboard with case replay and model evaluation.

## Start on Windows

Install Python 3.10 or newer, then open PowerShell in this folder and run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\start.ps1
```

The first run installs Python packages, downloads the original XES file, prepares the database, trains the model, and opens `http://127.0.0.1:8000`. The complete 4TU log can take time to download and process. The data file is kept in `data/raw/` and is not included in this project. No model score is claimed until this pipeline has run successfully on that original file; generated metrics are local outputs and are not committed.

To run each step yourself:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
flowtwin download
flowtwin prepare
flowtwin train
flowtwin serve
```

Install the test extra and run the suite from the project root:

```powershell
python -m pip install -e ".[test]"
python -m unittest discover -s tests -v
```

The suite covers feature-prefix isolation, fixed snapshot selection, weighted statistics, timestamp handling, XES input validation and parsing, download integrity, spreadsheet formula injection protection, HTTP API behavior, and a synthetic model-training smoke test. Synthetic checks do not replace evaluation on the original full event log. GitHub Actions installs the dependencies and runs the suite on Python 3.11 and 3.12.

If PowerShell blocks script activation, call `.venv\Scripts\python.exe -m pip install -e .` and then `.venv\Scripts\flowtwin.exe <command>` for each command. `flowtwin prepare --xes PATH` accepts a local `.xes` or `.xes.gz` file for repeatable experiments.

## Dataset source and citation

See [DATASET.md](DATASET.md) for the source, scope, interpretation, and reuse notes. The repository contains application code only; it does not include the research data.

## What the app does

1. **Downloads and checks** the original compressed XES file.
2. **Streams and validates** traces into a local SQLite database. It tracks missing IDs, missing activity names, missing or invalid timestamps, duplicate case IDs, out-of-order timestamps, and adjacent duplicate events.
3. **Builds a process overview** with monthly case starts, common activities, common consecutive transitions, and final status counts.
4. **Creates prefix snapshots** after 1, 3, 5, 10, 20, and 40 observed events where available. Checkpoints depend only on events already seen; training does not use the eventual case length to choose a prefix. Each case contributes at most six examples.
5. **Trains a real regression model** (`HistGradientBoostingRegressor`, absolute-error loss) to predict calendar hours between an observed prefix and the last event of a completed trace.
6. **Compares against a baseline** that predicts the training-set median remaining time for the current activity, with a global training median as fallback.
7. **Evaluates chronologically**: all snapshots for one case stay together; training cases have known end times before the validation window; validation ends before the test window. Each case receives equal total training and evaluation weight, divided among available checkpoints. The final test set is not used to tune the model.
8. **Replays a test case** event by event. The dashboard presents the prefix, predicted time, an empirical interval, baseline, and actual remaining time from the rest of the historical trace. The actual value is shown only as a retrospective comparison.

Features include current activity, prefix length, elapsed calendar hours, time since the previous event, counts of observed application/offer/workflow activities, and selected case attributes when they have appeared in the observed prefix. The model does not receive the final status, full event count, final timestamp, or events after the selected prefix.

## Completion and censoring rule

For this MVP, a case is treated as complete only if its **last observed activity** is one of the following:

`A_Pending`, `A_Denied`, `A_Cancelled`, `O_Accepted`, `O_Refused`, `O_Cancelled`.

This explicit rule is a practical heuristic for the demo, not a claim that it reproduces the bank's production closure definition. These are the principal outcomes discussed for the BPI 2017 log in the [BPI Challenge report](https://ais.win.tue.nl/bpi/2017/bpi2017_paper_27.pdf). Cases that do not end in one of these activities are marked as censored and excluded from the remaining-time regression target. The dashboard and generated data-quality summary show how many records were classified each way. Before publishing results, inspect the activity frequencies and confirm the rule against the event-log documentation or domain evidence.

Where the log provides lifecycle transitions, the parser uses `complete` events and keeps events with no lifecycle value. It sorts each case by timestamp and records when the source order was inconsistent. The target is elapsed **calendar** time; it does not represent active staff work, a service-level agreement, or a contractual deadline.

## Metrics and statistical choices

The generated `reports/generated/metrics.json` reports:

- **MAE in hours** as the main regression metric. It is interpretable in the same units as the target and less dominated by a few extreme errors than RMSE.
- **Median absolute error**, the **90th percentile absolute error**, and **RMSE** as supporting views of the error distribution.
- **Baseline MAE** and percent change from the activity-median baseline. A model that does not beat a simple baseline has not shown added predictive value on this test.
- **Metrics by observed prefix stage** (`1–3`, `4–10`, `11+` events), weighting cases equally within each stage so a good overall score cannot hide that the model is weak early in a case.
- A **95% bootstrap interval for mean per-case MAE**. The bootstrap resamples cases, not individual snapshots, because snapshots from the same case are dependent.
- An empirical **90% prediction interval** based on the 90th percentile of absolute validation residuals, followed by the interval's observed test coverage and average width. The nominal level is not a guarantee: distribution shift can reduce coverage.

MAPE is intentionally omitted because a remaining time close to zero makes percentage error unstable. Accuracy is not used because the task is regression. Outcome frequencies and accepted/declined/cancelled labels are descriptive, not a claim about causality or business performance.

## What a reviewer should challenge

- **Future leakage:** features must be constructed from the selected prefix only. Do not use final status, final event count, complete duration, or attributes that only appear after the forecast moment. The feature builder takes an explicit prefix length and scans only those events.
- **Case leakage:** never randomly split prefix rows. All prefixes of an application belong to one time-based split.
- **Censoring:** the end of the file is not the end date of an unfinished case. This MVP excludes cases without a recognized terminal activity instead of fabricating a target.
- **Unit of analysis:** one XES trace is one application. Offers remain events inside that application trace; they are not counted as separate application cases.
- **Calendar time:** nights, weekends, queue time, and customer waiting are included. Do not call it working time.
- **Long-tailed times:** report medians and percentiles alongside means, inspect very long cases, and do not delete them merely because they look like outliers.
- **Baseline value:** report whether ML improves the activity-median predictor. The algorithm name alone does not establish usefulness.
- **Statistical dependence:** several snapshots from one case are related. The case-level bootstrap avoids treating them as independent observations.
- **Causal claims:** an activity correlated with long forecasts is not proven to cause delay. Feature importance and SHAP describe model associations, not intervention effects.
- **Historical drift:** the log is old. Strong performance on this dataset does not establish accuracy on a current bank process.
- **Case attributes:** requested amount, application type, and loan goal are treated as application-start inputs. Offer attributes such as credit score and monthly cost are used only after they first appear on a timestamped event; trace-only offer values are excluded. Verify this assumption against the raw log and process documentation before operational use.
- **Digital twin wording:** this project is an offline replay and predictive-monitoring prototype. It has no live event feed, synchronized operational state, or validated what-if simulator, so it should not be presented as a production digital twin.

## Project layout

```text
src/flowtwin/       XES downloader, parser, feature builder, trainer, API
src/flowtwin/static English local dashboard
data/raw/           downloaded source file (ignored by Git)
data/processed/     SQLite event log (ignored by Git)
artifacts/          trained model (ignored by Git)
reports/generated/  metrics and test predictions (ignored by Git)
```

## Docker

Build with `docker build -t flowtwin-ai .`. The image runs as an unprivileged user and excludes local data, models, reports, tests, and Git metadata from its build context. The container stores runtime files under `/app` (configurable with `FLOWTWIN_HOME`). Keep data in named volumes, and publish the web port only on localhost for local use:

```powershell
docker run --rm -v flowtwin-data:/app/data -v flowtwin-artifacts:/app/artifacts -v flowtwin-reports:/app/reports flowtwin-ai flowtwin download
docker run --rm -v flowtwin-data:/app/data -v flowtwin-artifacts:/app/artifacts -v flowtwin-reports:/app/reports flowtwin-ai flowtwin prepare
docker run --rm -v flowtwin-data:/app/data -v flowtwin-artifacts:/app/artifacts -v flowtwin-reports:/app/reports flowtwin-ai flowtwin train
docker run --rm -p 127.0.0.1:8000:8000 -v flowtwin-data:/app/data -v flowtwin-artifacts:/app/artifacts -v flowtwin-reports:/app/reports flowtwin-ai
```

For local portfolio work, `start.ps1` is the simplest route.

## Scope

This is a learning and portfolio demo built on a public, historical event log. It is not affiliated with the institution represented in the dataset, and it is not a decision system for credit approval, customer contact, staffing, or SLA enforcement. The system performs neither a causal analysis nor an intervention simulation. The optional LLM assistant from the broader project idea is deliberately left out: the regression model and its measured performance are the AI core of this first demo.

## Security and validation

The parser uses `defusedxml`, accepts only `.xes` and `.xes.gz` files, caps compressed input at 4 GiB, caps decompressed XML at 8 GiB, and bounds total cases/events, XML nesting, trace/event attributes, retained data per trace, identifiers, activity names, and distinct activity/transition counts. Unused XML attributes and nested payloads are discarded during streaming. Database builds use a unique temporary file and replace the prior database only after a successful parse. The downloader enforces a 4 GiB limit, checks the advertised transfer length when present, stays on HTTPS, verifies the published MD5, and uses a unique temporary file before replacing the target. API responses include browser security headers and are not cached; the CLI disables request access logs to avoid recording case IDs from query strings. API search values and replay prefixes have bounds; SQL parameters are bound rather than interpolated. CSV text that spreadsheet software could interpret as a formula is prefixed before export.

The dashboard binds to localhost by default. The generated `joblib` model is a trusted local artifact: do not load a model file supplied by an untrusted party, because pickle-based formats can execute code when loaded. MD5 is used only to identify the published research file and detect accidental corruption; it is not a modern cryptographic security guarantee.
