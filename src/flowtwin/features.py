from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from .config import CATEGORICAL_CASE_FIELDS, NUMERIC_CASE_FIELDS


def build_features(
    events: list[dict[str, Any]], prefix_count: int, initial_attributes: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Build features using only the first ``prefix_count`` observed events."""
    if not events or prefix_count < 1 or prefix_count > len(events):
        raise ValueError("prefix_count must be within the available case history.")

    prefix = events[:prefix_count]
    first_time = _parse_time(prefix[0]["t"])
    last_time = _parse_time(prefix[-1]["t"])
    activities = [str(event.get("a") or "Unknown") for event in prefix]
    current = activities[-1]
    counts = {"A": 0, "O": 0, "W": 0}
    for activity in activities:
        if activity[:1] in counts:
            counts[activity[:1]] += 1

    features: dict[str, Any] = {
        "current_activity": current,
        "prefix_length": prefix_count,
        "elapsed_hours": max(0.0, (last_time - first_time).total_seconds() / 3600),
        "hours_since_previous": (
            max(0.0, (_parse_time(prefix[-1]["t"]) - _parse_time(prefix[-2]["t"])).total_seconds() / 3600)
            if prefix_count > 1
            else 0.0
        ),
        "unique_activities": len(set(activities)),
        "a_events_seen": counts["A"],
        "o_events_seen": counts["O"],
        "w_events_seen": counts["W"],
        "current_activity_repeats": sum(activity == current for activity in activities[:-1]),
    }

    # Case-level values may first appear on a later event; use only values
    # observed by the chosen prefix, taking the earliest visible value.
    visible: dict[str, Any] = {
        key: value for key, value in (initial_attributes or {}).items() if value not in (None, "")
    }
    for event in prefix:
        for key, value in (event.get("x") or {}).items():
            if key not in visible and value not in (None, ""):
                visible[key] = value

    for source, feature in NUMERIC_CASE_FIELDS.items():
        features[feature] = _number(visible.get(source))
    for source, feature in CATEGORICAL_CASE_FIELDS.items():
        value = visible.get(source)
        features[feature] = str(value) if value not in (None, "") else "Unknown"
    return features


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None
