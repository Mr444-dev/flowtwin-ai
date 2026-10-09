from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.feature_selection import VarianceThreshold
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from .config import (
    ARTIFACTS_DIR,
    DB_PATH,
    METRICS_PATH,
    NUMERIC_CASE_FIELDS,
    REPORTS_DIR,
    SNAPSHOT_PREFIX_COUNTS,
)
from .features import build_features
from .csv_safety import safe_csv_value
from .sampling import snapshot_prefix_counts, stage_for_prefix
from .weighted_stats import weighted_quantile


CATEGORICAL_FEATURES = ["current_activity", "loan_goal", "application_type"]
NUMERIC_FEATURES = [
    "prefix_length",
    "elapsed_hours",
    "hours_since_previous",
    "unique_activities",
    "a_events_seen",
    "o_events_seen",
    "w_events_seen",
    "current_activity_repeats",
    *NUMERIC_CASE_FIELDS.values(),
]
FEATURE_COLUMNS = [*CATEGORICAL_FEATURES, *NUMERIC_FEATURES]


def train_model() -> dict[str, Any]:
    if not DB_PATH.exists():
        raise FileNotFoundError("No prepared database found. Run: flowtwin prepare")

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    case_index = [
        dict(row)
        for row in con.execute(
            "SELECT case_id, started_at, ended_at, is_complete FROM cases ORDER BY started_at, case_id"
        )
    ]
    if len(case_index) < 100:
        con.close()
        raise ValueError(f"Too few cases ({len(case_index)}) for a reliable chronological split.")

    validation_start = case_index[int(len(case_index) * 0.70)]["started_at"]
    test_start = case_index[int(len(case_index) * 0.85)]["started_at"]
    completed_cases_in_windows = {"train": 0, "validation": 0, "test": 0}
    excluded_cases_crossing_cutoffs = 0
    for case in case_index:
        if not case["is_complete"]:
            continue
        if case["started_at"] < validation_start and case["ended_at"] < validation_start:
            completed_cases_in_windows["train"] += 1
        elif validation_start <= case["started_at"] < test_start and case["ended_at"] < test_start:
            completed_cases_in_windows["validation"] += 1
        elif case["started_at"] >= test_start:
            completed_cases_in_windows["test"] += 1
        else:
            excluded_cases_crossing_cutoffs += 1

    # Stream one trace at a time rather than loading all 1.2M event records
    # into memory. The compact case index above is enough to assign the split.
    snapshot_rows: dict[str, list[dict[str, Any]]] = {"train": [], "validation": [], "test": []}
    cases_without_forecast_snapshots = 0
    for row in con.execute(
        "SELECT case_id, started_at, ended_at, is_complete, case_attrs_json, events_json "
        "FROM cases WHERE is_complete=1 ORDER BY started_at, case_id"
    ):
        case = dict(row)
        if case["started_at"] < validation_start and case["ended_at"] < validation_start:
            split = "train"
        elif validation_start <= case["started_at"] < test_start and case["ended_at"] < test_start:
            split = "validation"
        elif case["started_at"] >= test_start:
            split = "test"
        else:
            continue
        case_snapshots = _snapshots([case])
        if not case_snapshots:
            cases_without_forecast_snapshots += 1
            continue
        case_weight = 1.0 / len(case_snapshots)
        for snapshot in case_snapshots:
            snapshot["case_weight"] = case_weight
        snapshot_rows[split].extend(case_snapshots)
    con.close()
    case_counts = {
        split: len({row["case_id"] for row in rows}) for split, rows in snapshot_rows.items()
    }
    if any(not snapshot_rows[name] for name in ("train", "validation", "test")):
        sizes = case_counts
        raise ValueError(f"The chronological split produced an empty set: {sizes}. Check the case-completion rule.")

    train = pd.DataFrame(snapshot_rows["train"])
    validation = pd.DataFrame(snapshot_rows["validation"])
    test = pd.DataFrame(snapshot_rows["test"])
    y_train = train["target_hours"].astype(float)
    y_validation = validation["target_hours"].astype(float)
    y_test = test["target_hours"].astype(float)

    encoder = ColumnTransformer(
        transformers=[
            ("categorical", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CATEGORICAL_FEATURES),
            (
                "numeric",
                SimpleImputer(strategy="constant", fill_value=-1.0, keep_empty_features=True),
                NUMERIC_FEATURES,
            ),
        ],
        remainder="drop",
    )
    model = Pipeline(
        steps=[
            ("features", encoder),
            # Optional case attributes can be entirely absent in a dataset or
            # training window. Impute them, then drop constant columns before
            # histogram binning so empty/single-valued inputs remain trainable.
            ("nonconstant", VarianceThreshold()),
            (
                "regressor",
                HistGradientBoostingRegressor(
                    loss="absolute_error",
                    learning_rate=0.08,
                    max_iter=150,
                    max_leaf_nodes=20,
                    l2_regularization=1.0,
                    random_state=17,
                ),
            ),
        ]
    )
    model.fit(
        train[FEATURE_COLUMNS],
        y_train,
        regressor__sample_weight=train["case_weight"].to_numpy(dtype=float),
    )

    validation_pred = np.maximum(0, model.predict(validation[FEATURE_COLUMNS]))
    validation_errors = np.abs(y_validation.to_numpy() - validation_pred)
    interval_radius = weighted_quantile(
        validation_errors,
        validation["case_weight"].to_numpy(dtype=float),
        0.90,
    )
    test_pred = np.maximum(0, model.predict(test[FEATURE_COLUMNS]))

    activity_case_targets = (
        train.groupby(["current_activity", "case_id"], as_index=False)["target_hours"]
        .mean()
    )
    activity_medians = activity_case_targets.groupby("current_activity")["target_hours"].median().to_dict()
    global_case_targets = train.groupby("case_id")["target_hours"].mean()
    global_median = float(global_case_targets.median())
    baseline_pred = np.array(
        [float(activity_medians.get(activity, global_median)) for activity in test["current_activity"]]
    )

    test_weights = test["case_weight"].to_numpy(dtype=float)
    model_metrics = _regression_metrics(y_test.to_numpy(), test_pred, test_weights)
    baseline_metrics = _regression_metrics(y_test.to_numpy(), baseline_pred, test_weights)
    per_case_error = pd.DataFrame(
        {"case_id": test["case_id"], "abs_error": np.abs(y_test.to_numpy() - test_pred)}
    ).groupby("case_id")["abs_error"].mean()
    ci_low, ci_high = _bootstrap_mean_ci(per_case_error.to_numpy())
    covered = (y_test.to_numpy() >= np.maximum(0, test_pred - interval_radius)) & (
        y_test.to_numpy() <= test_pred + interval_radius
    )
    interval_width = test_pred + interval_radius - np.maximum(0, test_pred - interval_radius)
    stage_metrics = []
    stage_frame = test[["case_id", "stage", "target_hours"]].copy()
    stage_frame["abs_error"] = np.abs(y_test.to_numpy() - test_pred)
    stage_frame["interval_covered"] = covered
    stage_frame["interval_width"] = interval_width
    for stage, group in stage_frame.groupby("stage", sort=False):
        per_case_stage = group.groupby("case_id").agg(
            mae_hours=("abs_error", "mean"),
            interval_coverage=("interval_covered", "mean"),
            interval_width_hours=("interval_width", "mean"),
        )
        stage_metrics.append(
            {
                "stage": stage,
                "snapshots": int(len(group)),
                "cases": int(group["case_id"].nunique()),
                "mae_hours": round(float(per_case_stage["mae_hours"].mean()), 3),
                "interval_coverage": round(float(per_case_stage["interval_coverage"].mean()), 4),
                "interval_mean_width_hours": round(float(per_case_stage["interval_width_hours"].mean()), 3),
            }
        )

    improvement = (
        (baseline_metrics["mae_hours"] - model_metrics["mae_hours"])
        / baseline_metrics["mae_hours"]
        * 100
        if baseline_metrics["mae_hours"] > 0
        else None
    )
    metrics: dict[str, Any] = {
        "dataset": "BPI Challenge 2017",
        "target": "calendar hours from observed prefix to final observed terminal activity",
        "unit": "hours",
        "split_method": "chronological by case start; every prefix of a case remains in one split",
        "snapshot_policy": {
            "prefix_event_counts": list(SNAPSHOT_PREFIX_COUNTS),
            "maximum_snapshots_per_case": len(SNAPSHOT_PREFIX_COUNTS),
            "stage_definition": "early: 1-3 observed events; mid: 4-10; late: 11+",
        },
        "evaluation_weighting": "equal total weight per case, divided among its observed checkpoints",
        "train_known_by": validation_start,
        "validation_window": {"from": validation_start, "to": test_start},
        "test_from": test_start,
        "case_counts": case_counts,
        "completed_cases_in_time_windows": completed_cases_in_windows,
        "snapshot_counts": {name: len(rows) for name, rows in snapshot_rows.items()},
        "excluded_cases_crossing_cutoffs": excluded_cases_crossing_cutoffs,
        "completed_cases_without_forecast_snapshots": cases_without_forecast_snapshots,
        "test": {
            **model_metrics,
            "mae_case_bootstrap_95_ci_hours": [round(ci_low, 3), round(ci_high, 3)],
            "baseline_activity_median": baseline_metrics,
            "mae_improvement_vs_baseline_percent": round(float(improvement), 2) if improvement is not None else None,
            "validation_absolute_residual_p90_hours": round(interval_radius, 3),
            "test_interval_coverage": round(float(np.average(covered, weights=test_weights)), 4),
            "test_interval_nominal_coverage": 0.90,
            "test_interval_mean_width_hours": round(float(np.average(interval_width, weights=test_weights)), 3),
            "by_stage": stage_metrics,
        },
        "limitations": [
            "History is from 2016–2017 and is not a live operational feed.",
            "Cases are counted complete by an explicit final-activity heuristic; censored traces are excluded from regression.",
            "The outcome is elapsed calendar time, not staff working time or an SLA breach.",
            "The displayed interval is calibrated on validation residuals; its coverage can drift over time.",
        ],
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "model": model,
            "baseline_by_activity": {str(k): float(v) for k, v in activity_medians.items()},
            "baseline_global": global_median,
            "interval_radius_hours": interval_radius,
            "features": FEATURE_COLUMNS,
        },
        ARTIFACTS_DIR / "remaining_time.joblib",
    )
    METRICS_PATH.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    predictions = test[["case_id", "started_at", "stage", "current_activity", "target_hours"]].copy()
    predictions["model_prediction_hours"] = test_pred
    predictions["baseline_prediction_hours"] = baseline_pred
    predictions["model_absolute_error_hours"] = np.abs(y_test.to_numpy() - test_pred)
    predictions["baseline_absolute_error_hours"] = np.abs(y_test.to_numpy() - baseline_pred)
    predictions["interval_lower_hours"] = np.maximum(0, test_pred - interval_radius)
    predictions["interval_upper_hours"] = test_pred + interval_radius
    predictions["interval_contains_actual"] = covered
    safe_predictions = predictions.astype(object).apply(lambda column: column.map(safe_csv_value))
    safe_predictions.to_csv(REPORTS_DIR / "test_predictions.csv", index=False)
    print(f"Model saved: {ARTIFACTS_DIR / 'remaining_time.joblib'}")
    print(f"Model test MAE: {model_metrics['mae_hours']:.2f} h")
    print(f"Baseline test MAE: {baseline_metrics['mae_hours']:.2f} h")
    print(f"Metrics: {METRICS_PATH}")
    return metrics


def _snapshots(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in cases:
        events = json.loads(case["events_json"])
        if len(events) < 2:
            continue
        end_time = _parse_time(events[-1]["t"])
        initial_attributes = json.loads(case["case_attrs_json"])
        prefix_counts = snapshot_prefix_counts(len(events))
        for prefix_count in prefix_counts:
            feature = build_features(events, prefix_count, initial_attributes)
            stage = stage_for_prefix(prefix_count)
            target = max(
                0.0,
                (end_time - _parse_time(events[prefix_count - 1]["t"])).total_seconds() / 3600,
            )
            rows.append(
                {
                    **feature,
                    "case_id": case["case_id"],
                    "started_at": case["started_at"],
                    "stage": stage,
                    "target_hours": target,
                }
            )
    return rows


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _regression_metrics(actual: np.ndarray, predicted: np.ndarray, weights: np.ndarray) -> dict[str, float]:
    errors = np.abs(actual - predicted)
    return {
        "mae_hours": round(float(np.average(errors, weights=weights)), 3),
        "median_absolute_error_hours": round(weighted_quantile(errors, weights, 0.50), 3),
        "p90_absolute_error_hours": round(weighted_quantile(errors, weights, 0.90), 3),
        "rmse_hours": round(float(np.sqrt(np.average((actual - predicted) ** 2, weights=weights))), 3),
    }


def _bootstrap_mean_ci(case_errors: np.ndarray, repetitions: int = 1000) -> tuple[float, float]:
    rng = np.random.default_rng(17)
    sample_count = len(case_errors)
    draws = rng.choice(case_errors, size=(repetitions, sample_count), replace=True).mean(axis=1)
    low, high = np.quantile(draws, [0.025, 0.975])
    return float(low), float(high)
