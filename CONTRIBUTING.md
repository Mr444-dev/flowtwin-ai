# Contributing

## Local setup

Use Python 3.11 or 3.12, then install the application and test dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
```

The original event log is downloaded separately by `flowtwin download` and must not be committed. Local databases, models, metrics, and prediction exports are also ignored by Git.

## Before opening a pull request

```powershell
python -m unittest discover -s tests -v
python -m compileall -q src tests
```

Changes to feature timing, terminal labels, split boundaries, snapshot selection, weights, or metrics should include regression tests and a short methodology note. Never add a performance number unless it comes from `flowtwin train` on the documented source and chronological test split.
