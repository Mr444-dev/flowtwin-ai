from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse

from .config import DB_PATH, METRICS_PATH, MODEL_PATH, REPORTS_DIR
from .features import build_features


app = FastAPI(title="FlowTwin AI", version="0.1.0")
_bundle: dict[str, Any] | None = None
_bundle_mtime: float | None = None


@app.middleware("http")
async def security_headers(request: Request, call_next: Any) -> Any:
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; "
        "form-action 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'",
    )
    return response


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/static/{asset_name}", include_in_schema=False)
def static_asset(asset_name: str) -> FileResponse:
    if asset_name not in {"app.js", "styles.css"}:
        raise HTTPException(status_code=404, detail="Resource not found.")
    return FileResponse(Path(__file__).parent / "static" / asset_name)


@app.get("/api/dashboard")
def dashboard_data() -> dict[str, Any]:
    if not DB_PATH.exists():
        return {"ready": False, "message": "No data found. Run flowtwin download, prepare, and train."}

    con = _connect()
    counts = con.execute(
        """SELECT COUNT(*) AS cases, SUM(event_count) AS events,
                  SUM(is_complete) AS complete_cases,
                  MIN(started_at) AS first_start, MAX(started_at) AS last_start
           FROM cases"""
    ).fetchone()
    durations = [row[0] for row in con.execute(
        "SELECT (julianday(ended_at)-julianday(started_at))*24 FROM cases WHERE is_complete=1"
    )]
    starts = con.execute(
        "SELECT substr(started_at, 1, 7) AS month, COUNT(*) AS count "
        "FROM cases GROUP BY month ORDER BY month"
    ).fetchall()
    activities = con.execute(
        "SELECT activity, count FROM activity_counts ORDER BY count DESC LIMIT 9"
    ).fetchall()
    transitions = con.execute(
        "SELECT from_activity, to_activity, count FROM transitions ORDER BY count DESC LIMIT 10"
    ).fetchall()
    outcomes = con.execute(
        "SELECT outcome, COUNT(*) FROM cases GROUP BY outcome ORDER BY COUNT(*) DESC"
    ).fetchall()
    meta_row = con.execute("SELECT value FROM metadata WHERE key='dataset'").fetchone()
    con.close()

    complete_count = int(counts["complete_cases"] or 0)
    duration_values = np.asarray(durations, dtype=float) if durations else np.asarray([])
    summary = {
        "case_count": int(counts["cases"] or 0),
        "event_count": int(counts["events"] or 0),
        "complete_cases": complete_count,
        "censored_cases": int(counts["cases"] or 0) - complete_count,
        "start_range": [counts["first_start"], counts["last_start"]],
        "median_duration_days": round(float(np.median(duration_values) / 24), 1) if len(duration_values) else None,
        "p90_duration_days": round(float(np.quantile(duration_values, 0.90) / 24), 1) if len(duration_values) else None,
    }
    metrics = json.loads(METRICS_PATH.read_text(encoding="utf-8")) if METRICS_PATH.exists() else None
    metadata = json.loads(meta_row[0]) if meta_row else {}
    return {
        "ready": True,
        "summary": summary,
        "months": [{"month": row[0], "count": int(row[1])} for row in starts],
        "activities": [{"activity": row[0], "count": int(row[1])} for row in activities],
        "transitions": [
            {"from": row[0], "to": row[1], "count": int(row[2])} for row in transitions
        ],
        "outcomes": [{"outcome": row[0], "count": int(row[1])} for row in outcomes],
        "metrics": metrics,
        "quality": metadata.get("quality", {}),
        "completion_rule": metadata.get("completion_rule"),
        "data_period_note": "BPI Challenge 2017: applications filed in 2016; events recorded through 1 February 2017.",
        "source": "Boudewijn F. van Dongen, BPI Challenge 2017, 4TU.ResearchData, DOI "
        "10.4121/uuid:5f3067df-f10b-45da-b98b-86ae4c7a310b",
    }


@app.get("/api/cases")
def cases_list(
    q: str = Query(default="", max_length=80), limit: int = Query(default=100, ge=1, le=250)
) -> list[dict[str, Any]]:
    if not DB_PATH.exists():
        return []
    con = _connect()
    if q:
        rows = con.execute(
            "SELECT case_id, started_at, ended_at, event_count, is_complete, outcome "
            "FROM cases WHERE case_id LIKE ? ORDER BY started_at DESC LIMIT ?",
            (f"%{q}%", limit),
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT case_id, started_at, ended_at, event_count, is_complete, outcome "
            "FROM cases ORDER BY started_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    con.close()
    return [dict(row) for row in rows]


@app.get("/api/case")
def case_replay(
    case_id: str = Query(..., min_length=1, max_length=128),
    prefix: int = Query(default=1, ge=1, le=100_000),
) -> dict[str, Any]:
    if not DB_PATH.exists():
        raise HTTPException(status_code=503, detail="Prepare the data first.")
    con = _connect()
    row = con.execute("SELECT * FROM cases WHERE case_id=?", (case_id,)).fetchone()
    con.close()
    if not row:
        raise HTTPException(status_code=404, detail="Case not found.")

    events = json.loads(row["events_json"])
    prefix_count = min(prefix, max(1, len(events) - 1))
    seen = events[:prefix_count]
    initial_attributes = json.loads(row["case_attrs_json"])
    feature = build_features(events, prefix_count, initial_attributes)
    bundle = _load_bundle()
    forecast = None
    if bundle:
        frame = pd.DataFrame([feature], columns=bundle["features"])
        prediction = max(0.0, float(bundle["model"].predict(frame)[0]))
        radius = float(bundle["interval_radius_hours"])
        baseline = float(bundle["baseline_by_activity"].get(feature["current_activity"], bundle["baseline_global"]))
        forecast = {
            "remaining_hours": round(prediction, 1),
            "lower_hours": round(max(0.0, prediction - radius), 1),
            "upper_hours": round(prediction + radius, 1),
            "baseline_hours": round(baseline, 1),
        }

    actual = None
    if row["is_complete"]:
        end_time = _parse_time(events[-1]["t"])
        current_time = _parse_time(seen[-1]["t"])
        actual = max(0.0, (end_time - current_time).total_seconds() / 3600)
    start_time = _parse_time(events[0]["t"])
    current_time = _parse_time(seen[-1]["t"])
    history_start = max(0, len(seen) - 8)
    history = [
        {"sequence": history_start + index + 1, "activity": event["a"], "timestamp": event["t"], "lifecycle": event.get("l", "")}
        for index, event in enumerate(seen[history_start:])
    ]
    return {
        "case_id": row["case_id"],
        "started_at": row["started_at"],
        "terminal_activity": row["terminal_activity"],
        "outcome": row["outcome"],
        "is_complete": bool(row["is_complete"]),
        "event_count": len(events),
        "prefix_count": prefix_count,
        "current_activity": feature["current_activity"],
        "elapsed_hours": round((current_time - start_time).total_seconds() / 3600, 1),
        "remaining_actual_hours": round(actual, 1) if actual is not None else None,
        "forecast": forecast,
        "history": history,
    }


@app.get("/api/metrics.csv")
def metrics_csv() -> FileResponse:
    path = REPORTS_DIR / "test_predictions.csv"
    if not path.exists():
        raise HTTPException(status_code=404, detail="The export is created during model training.")
    return FileResponse(path, filename="flowtwin-test-predictions.csv", media_type="text/csv")


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _load_bundle() -> dict[str, Any] | None:
    global _bundle, _bundle_mtime
    if not MODEL_PATH.exists():
        return None
    modified = MODEL_PATH.stat().st_mtime
    if _bundle is None or modified != _bundle_mtime:
        _bundle = joblib.load(MODEL_PATH)
        _bundle_mtime = modified
    return _bundle


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
