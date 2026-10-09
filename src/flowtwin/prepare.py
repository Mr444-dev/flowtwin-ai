from __future__ import annotations

import gzip
import json
import math
import os
import sqlite3
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Iterator

from defusedxml import ElementTree as ET

from .config import (
    CATEGORICAL_CASE_FIELDS,
    DB_PATH,
    NUMERIC_CASE_FIELDS,
    RAW_DIR,
    TERMINAL_ACTIVITIES,
)


MAX_COMPRESSED_BYTES = 4 * 1024**3
MAX_UNCOMPRESSED_BYTES = 8 * 1024**3
MAX_EVENTS_PER_TRACE = 100_000
MAX_TOTAL_EVENTS = 10_000_000
MAX_CASES = 250_000
MAX_TRACE_ATTRIBUTES = 256
MAX_EVENT_ATTRIBUTES = 256
MAX_XML_DEPTH = 256
MAX_ATTRIBUTE_VALUE_CHARS = 4_096
MAX_ACTIVITY_NAME_CHARS = 512
MAX_CASE_ID_CHARS = 128
MAX_RETAINED_CHARS_PER_TRACE = 16 * 1024 * 1024
MAX_DISTINCT_ACTIVITIES = 10_000
MAX_DISTINCT_TRANSITIONS = 100_000
APPLICATION_START_ATTRIBUTES = {
    "case:ApplicationID",
    "case:RequestedAmount",
    "case:LoanGoal",
    "case:ApplicationType",
}
RETAINED_EVENT_ATTRIBUTES = (
    set(NUMERIC_CASE_FIELDS)
    | set(CATEGORICAL_CASE_FIELDS)
    | APPLICATION_START_ATTRIBUTES
    | {"concept:name", "time:timestamp", "lifecycle:transition", "case:concept:name"}
)
TRACE_ATTRIBUTE_KEYS = (
    {"concept:name", "case:concept:name"}
    | APPLICATION_START_ATTRIBUTES
    | set(NUMERIC_CASE_FIELDS)
    | set(CATEGORICAL_CASE_FIELDS)
)


def prepare_data(xes_path: Path | None = None) -> dict[str, Any]:
    """Stream the XES log into SQLite, retaining only the fields used by the demo."""
    source = xes_path or RAW_DIR / "BPI Challenge 2017.xes.gz"
    if not source.exists():
        raise FileNotFoundError(f"File not found: {source}. Run this first: flowtwin download")
    if not source.is_file() or not (source.name.lower().endswith(".xes") or source.name.lower().endswith(".xes.gz")):
        raise ValueError("The source must be a regular .xes or .xes.gz file.")
    source_size = source.stat().st_size
    if source_size == 0:
        raise ValueError("The XES file is empty.")
    if source_size > MAX_COMPRESSED_BYTES:
        raise ValueError(f"The XES file exceeds the {MAX_COMPRESSED_BYTES // 1024**3} GiB limit.")

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{DB_PATH.name}.", suffix=".building", dir=DB_PATH.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    con: sqlite3.Connection | None = None
    try:
        con = sqlite3.connect(temp_path)
        _create_schema(con)
    except Exception:
        if con is not None:
            con.close()
        temp_path.unlink(missing_ok=True)
        raise
    assert con is not None
    quality = Counter()
    transitions: Counter[tuple[str, str]] = Counter()
    activity_counts: Counter[str] = Counter()

    try:
        opener = gzip.open if source.suffix.lower() == ".gz" else open
        with opener(source, "rb") as stream:
            limited_stream = _BoundedReader(stream, MAX_UNCOMPRESSED_BYTES)
            for case_id, trace_attrs, raw_events in _iter_trace_records(limited_stream, quality):
                inserted = con.execute("INSERT OR IGNORE INTO seen_case_ids VALUES (?)", (case_id,))
                if inserted.rowcount == 0:
                    quality["duplicate_case_ids"] += 1
                    continue
                quality["unique_case_ids"] += 1
                if quality["unique_case_ids"] > MAX_CASES:
                    raise ValueError(f"The XES file exceeds the limit of {MAX_CASES:,} cases.")
                events = _normalize_events(raw_events, trace_attrs, quality)
                if not events:
                    quality["cases_without_valid_events"] += 1
                    continue

                activities = [str(e["a"]) for e in events]
                for activity in activities:
                    if activity not in activity_counts and len(activity_counts) >= MAX_DISTINCT_ACTIVITIES:
                        raise ValueError(
                            f"The XES file exceeds the limit of {MAX_DISTINCT_ACTIVITIES:,} distinct activities."
                        )
                    activity_counts[activity] += 1
                for transition in zip(activities, activities[1:]):
                    if transition not in transitions and len(transitions) >= MAX_DISTINCT_TRANSITIONS:
                        raise ValueError(
                            f"The XES file exceeds the limit of {MAX_DISTINCT_TRANSITIONS:,} distinct transitions."
                        )
                    transitions[transition] += 1

                start = _parse_time(events[0]["t"])
                end = _parse_time(events[-1]["t"])
                terminal = activities[-1]
                complete = terminal in TERMINAL_ACTIVITIES
                outcome = _outcome(terminal) if complete else "censored"
                case_attrs = _visible_case_attrs(
                    {key: value for key, value in trace_attrs.items() if key.startswith("case:")}
                )
                con.execute(
                    "INSERT INTO cases VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        case_id,
                        start.isoformat(),
                        end.isoformat(),
                        terminal,
                        outcome,
                        len(events),
                        int(complete),
                        json.dumps(case_attrs, ensure_ascii=False, separators=(",", ":")),
                        json.dumps(events, ensure_ascii=False, separators=(",", ":")),
                    ),
                )
                quality["cases_read"] += 1
                quality["complete_cases"] += int(complete)
                quality["censored_cases"] += int(not complete)
                quality["events_kept"] += len(events)
                if quality["cases_read"] % 1000 == 0:
                    con.commit()
                    print(f"\rProcessed {quality['cases_read']:,} cases", end="", flush=True)
        print()

        if quality["cases_read"] == 0:
            raise ValueError("No case with a valid ID, event, and timestamp was found.")

        for (activity_a, activity_b), count in transitions.items():
            con.execute("INSERT INTO transitions VALUES (?, ?, ?)", (activity_a, activity_b, count))
        for activity, count in activity_counts.items():
            con.execute("INSERT INTO activity_counts VALUES (?, ?)", (activity, count))
        source_metadata = {
            "source_file": source.name,
            "source_url": "https://data.4tu.nl/articles/dataset/BPI_Challenge_2017/12696884",
            "prepared_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "terminal_activities": sorted(TERMINAL_ACTIVITIES),
            "completion_rule": "last observed activity is in terminal_activities",
            "quality": dict(quality),
        }
        con.execute("INSERT INTO metadata VALUES (?, ?)", ("dataset", json.dumps(source_metadata)))
        con.execute("DROP TABLE seen_case_ids")
        con.commit()
        con.close()
        temp_path.replace(DB_PATH)
        print(f"Database prepared: {DB_PATH}")
        return source_metadata
    except Exception:
        con.close()
        temp_path.unlink(missing_ok=True)
        raise


class _BoundedReader:
    """Count decompressed bytes to limit oversized or highly compressed XES input."""

    def __init__(self, stream: BinaryIO, maximum: int) -> None:
        self._stream = stream
        self._maximum = maximum
        self._read_bytes = 0

    def read(self, size: int = -1) -> bytes:
        data = self._stream.read(size)
        self._read_bytes += len(data)
        if self._read_bytes > self._maximum:
            raise ValueError(f"The decompressed XES file exceeds the {self._maximum // 1024**3} GiB limit.")
        return data


def _create_schema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE cases (
            case_id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            ended_at TEXT NOT NULL,
            terminal_activity TEXT NOT NULL,
            outcome TEXT NOT NULL,
            event_count INTEGER NOT NULL,
            is_complete INTEGER NOT NULL,
            case_attrs_json TEXT NOT NULL,
            events_json TEXT NOT NULL
        );
        CREATE INDEX cases_started ON cases(started_at);
        CREATE TABLE transitions (from_activity TEXT, to_activity TEXT, count INTEGER,
                                  PRIMARY KEY(from_activity, to_activity));
        CREATE TABLE activity_counts (activity TEXT PRIMARY KEY, count INTEGER);
        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE seen_case_ids (case_id TEXT PRIMARY KEY);
        """
    )


def _iter_trace_records(
    stream: BinaryIO, quality: Counter[str]
) -> Iterator[tuple[str, dict[str, Any], list[dict[str, Any]]]]:
    """Yield one compact trace at a time and clear each XML event immediately."""
    stack: list[ET.Element] = []
    trace_element: ET.Element | None = None
    attrs: dict[str, Any] = {}
    events: list[dict[str, Any]] = []
    event_count = 0
    trace_attribute_count = 0
    retained_chars = 0

    for action, element in ET.iterparse(stream, events=("start", "end")):
        tag = _local(element.tag)
        if action == "start":
            if tag == "trace":
                if trace_element is not None:
                    raise ValueError("Invalid XES: found a nested trace element.")
                trace_element = element
                attrs = {}
                events = []
                event_count = 0
                trace_attribute_count = 0
                retained_chars = 0
            stack.append(element)
            if len(stack) > MAX_XML_DEPTH:
                raise ValueError(f"The XES XML exceeds the nesting limit of {MAX_XML_DEPTH} elements.")
            continue

        parent = stack[-2] if len(stack) > 1 else None
        record: tuple[str, dict[str, Any], list[dict[str, Any]]] | None = None
        trace_finished = False
        if trace_element is not None:
            if tag == "event" and parent is trace_element:
                event_count += 1
                if event_count > MAX_EVENTS_PER_TRACE:
                    raise ValueError(f"A case exceeds the limit of {MAX_EVENTS_PER_TRACE:,} events.")
                quality["events_seen"] += 1
                if quality["events_seen"] > MAX_TOTAL_EVENTS:
                    raise ValueError(f"The XES file exceeds the limit of {MAX_TOTAL_EVENTS:,} events.")
                event = _read_event(element, quality)
                if event is not None:
                    retained_chars += _event_character_count(event)
                    if retained_chars > MAX_RETAINED_CHARS_PER_TRACE:
                        raise ValueError(
                            "A case exceeds the limit of "
                            f"{MAX_RETAINED_CHARS_PER_TRACE // 1024 // 1024} MiB of retained event data."
                        )
                    events.append(event)
                element.clear()
            elif parent is trace_element:
                trace_attribute_count += 1
                if trace_attribute_count > MAX_TRACE_ATTRIBUTES:
                    raise ValueError(f"A case exceeds the limit of {MAX_TRACE_ATTRIBUTES} trace attributes.")
                key = element.attrib.get("key")
                if key and key in TRACE_ATTRIBUTE_KEYS:
                    attrs[key] = _typed_value(element)
                element.clear()
            elif element is trace_element and tag == "trace":
                record = _finish_trace(attrs, events, quality)
                if parent is not None:
                    parent.remove(element)
                element.clear()
                trace_element = None
                trace_finished = True
            elif (
                parent is not None
                and _local(parent.tag) == "event"
                and len(stack) >= 3
                and stack[-3] is trace_element
            ):
                # Keep direct event attributes until _read_event sees the
                # completed event; its nested payloads are still cleared.
                pass
            else:
                # Nested attribute payloads are not used by this demo. Clear
                # them as they are parsed so they cannot accumulate in memory.
                element.clear()
        elif tag != "log":
            # Global XES declarations are not used by the demo.
            element.clear()

        stack.pop()
        if trace_finished and record is not None:
            yield record


def _read_event(element: ET.Element, quality: Counter[str]) -> dict[str, Any] | None:
    event = _parse_attributes(element, RETAINED_EVENT_ATTRIBUTES)
    if not event.get("concept:name"):
        quality["events_missing_activity"] += 1
        return None
    timestamp = event.get("time:timestamp")
    if not timestamp:
        quality["events_missing_timestamp"] += 1
        return None
    activity = str(event["concept:name"])
    timestamp = str(timestamp)
    lifecycle = str(event.get("lifecycle:transition") or "")
    if len(activity) > MAX_ACTIVITY_NAME_CHARS:
        raise ValueError(f"An activity name exceeds the limit of {MAX_ACTIVITY_NAME_CHARS} characters.")
    if len(timestamp) > 64:
        raise ValueError("An event timestamp exceeds the limit of 64 characters.")
    if len(lifecycle) > 64:
        raise ValueError("A lifecycle transition exceeds the limit of 64 characters.")
    return {
        "a": activity,
        "t": timestamp,
        "l": lifecycle,
        "x": {key: value for key, value in event.items() if key.startswith("case:")},
    }


def _finish_trace(
    attrs: dict[str, Any], events: list[dict[str, Any]], quality: Counter[str]
) -> tuple[str, dict[str, Any], list[dict[str, Any]]] | None:
    case_id = attrs.get("concept:name") or attrs.get("case:ApplicationID")
    if not case_id:
        for event in events:
            case_id = event.get("x", {}).get("case:ApplicationID") or event.get("x", {}).get("case:concept:name")
            if case_id:
                break
    if not case_id:
        quality["cases_missing_id"] += 1
        return None
    case_id = str(case_id)
    if len(case_id) > MAX_CASE_ID_CHARS:
        raise ValueError(f"A case ID exceeds the limit of {MAX_CASE_ID_CHARS} characters.")
    return case_id, attrs, events


def _normalize_events(
    events: list[dict[str, Any]], trace_attrs: dict[str, Any], quality: Counter[str]
) -> list[dict[str, Any]]:
    # If XES lifecycle transitions exist, use complete events; preserve entries
    # without a transition because some logs mix explicit and implicit events.
    has_lifecycle = any(event.get("l") for event in events)
    if has_lifecycle:
        complete = [event for event in events if event.get("l", "").lower() in ("", "complete")]
        if complete:
            events = complete

    parsed: list[tuple[datetime, int, dict[str, Any]]] = []
    previous: datetime | None = None
    for index, event in enumerate(events):
        try:
            timestamp = _parse_time(event["t"])
        except (ValueError, TypeError):
            quality["events_invalid_timestamp"] += 1
            continue
        if previous and timestamp < previous:
            quality["out_of_order_events"] += 1
        previous = timestamp
        normalized = {
            "a": event["a"],
            "t": timestamp.isoformat(),
            "l": event.get("l") or "",
            "x": event.get("x", {}),
        }
        parsed.append((timestamp, index, normalized))
    parsed.sort(key=lambda item: (item[0], item[1]))

    result: list[dict[str, Any]] = []
    previous_signature: tuple[str, str, str] | None = None
    # Only fields documented as application-level inputs are assumed available
    # from case start. Offer attributes stay event-timed, even if a trace-level
    # copy exists, so a later offer cannot leak into an earlier prefix.
    visible_case_keys = {
        key for key in APPLICATION_START_ATTRIBUTES if trace_attrs.get(key) not in (None, "")
    }
    for _, _, event in parsed:
        signature = (event["a"], event["t"], event["l"])
        if signature == previous_signature:
            quality["adjacent_duplicate_events"] += 1
        previous_signature = signature
        # Case attributes repeated on every event add redundant bytes. Store
        # their first event-level appearance only; features carry values forward.
        first_values: dict[str, Any] = {}
        for key, value in event.get("x", {}).items():
            if key not in visible_case_keys:
                first_values[key] = value
                visible_case_keys.add(key)
        event["x"] = first_values
        result.append(event)
    return result


def _parse_attributes(element: ET.Element, allowed_keys: set[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for index, child in enumerate(element, start=1):
        if index > MAX_EVENT_ATTRIBUTES:
            raise ValueError(f"An event exceeds the limit of {MAX_EVENT_ATTRIBUTES} attributes.")
        key = child.attrib.get("key")
        if key and key in allowed_keys:
            result[key] = _typed_value(child)
    return result


def _typed_value(element: ET.Element) -> Any:
    value = element.attrib.get("value", "")
    if len(value) > MAX_ATTRIBUTE_VALUE_CHARS:
        raise ValueError(f"An attribute value exceeds the limit of {MAX_ATTRIBUTE_VALUE_CHARS} characters.")
    kind = _local(element.tag)
    if kind in ("int", "integer", "long"):
        try:
            return int(value)
        except ValueError:
            return value
    if kind in ("float", "double"):
        try:
            number = float(value)
            return number if math.isfinite(number) else value
        except ValueError:
            return value
    if kind == "boolean":
        return value.lower() == "true"
    return value


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _outcome(activity: str) -> str:
    if activity in {"A_Pending", "O_Accepted"}:
        return "accepted"
    if activity in {"A_Denied", "O_Refused"}:
        return "declined"
    if activity in {"A_Cancelled", "O_Cancelled"}:
        return "cancelled"
    return "other_terminal"


def _visible_case_attrs(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if key in APPLICATION_START_ATTRIBUTES}


def _event_character_count(event: dict[str, Any]) -> int:
    count = len(event["a"]) + len(event["t"]) + len(event.get("l", ""))
    for key, value in (event.get("x") or {}).items():
        count += len(key) + len(str(value))
    return count
