from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

WEB_DEPS_AVAILABLE = all(
    importlib.util.find_spec(name) is not None
    for name in ("fastapi", "httpx2", "numpy", "pandas", "sklearn", "joblib")
)


@unittest.skipUnless(WEB_DEPS_AVAILABLE, "Install project[test] to run the HTTP API tests")
class WebApiTests(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi.testclient import TestClient
        from flowtwin import web

        self.web = web
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / "flowtwin.sqlite3"
        self._write_database()
        for name, value in (
            ("DB_PATH", self.db),
            ("METRICS_PATH", self.root / "metrics.json"),
            ("MODEL_PATH", self.root / "missing.joblib"),
            ("REPORTS_DIR", self.root / "reports"),
        ):
            patcher = patch.object(web, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = TestClient(web.app)

    def _write_database(self) -> None:
        con = sqlite3.connect(self.db)
        con.executescript(
            """
            CREATE TABLE cases (
                case_id TEXT PRIMARY KEY, started_at TEXT, ended_at TEXT, terminal_activity TEXT,
                outcome TEXT, event_count INTEGER, is_complete INTEGER, case_attrs_json TEXT, events_json TEXT
            );
            CREATE TABLE activity_counts (activity TEXT PRIMARY KEY, count INTEGER);
            CREATE TABLE transitions (from_activity TEXT, to_activity TEXT, count INTEGER,
                                      PRIMARY KEY(from_activity, to_activity));
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """
        )
        start = datetime(2020, 1, 1, tzinfo=timezone.utc)
        events = [
            {"a": "A_Submitted", "t": start.isoformat(), "l": "complete", "x": {}},
            {"a": "A_Pending", "t": datetime(2020, 1, 1, 1, tzinfo=timezone.utc).isoformat(), "l": "complete", "x": {}},
        ]
        con.execute(
            "INSERT INTO cases VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("case-1", events[0]["t"], events[-1]["t"], "A_Pending", "accepted", 2, 1, "{}", json.dumps(events)),
        )
        con.execute("INSERT INTO activity_counts VALUES (?, ?)", ("A_Submitted", 1))
        con.execute("INSERT INTO activity_counts VALUES (?, ?)", ("A_Pending", 1))
        con.execute("INSERT INTO transitions VALUES (?, ?, ?)", ("A_Submitted", "A_Pending", 1))
        con.execute("INSERT INTO metadata VALUES (?, ?)", ("dataset", json.dumps({"quality": {}, "completion_rule": "test"})))
        con.commit()
        con.close()

    def test_dashboard_and_case_replay_return_expected_shapes(self) -> None:
        dashboard = self.client.get("/api/dashboard")
        replay = self.client.get("/api/case", params={"case_id": "case-1", "prefix": 1})
        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(dashboard.json()["summary"]["case_count"], 1)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.json()["remaining_actual_hours"], 1.0)
        self.assertIsNone(replay.json()["forecast"])

    def test_search_is_parameterized_and_query_length_is_bounded(self) -> None:
        injected = self.client.get("/api/cases", params={"q": "%' OR 1=1 --"})
        oversized = self.client.get("/api/cases", params={"q": "x" * 81})
        self.assertEqual(injected.status_code, 200)
        self.assertEqual(injected.json(), [])
        self.assertEqual(oversized.status_code, 422)

    def test_case_id_and_prefix_bounds_are_validated(self) -> None:
        missing = self.client.get("/api/case", params={"case_id": ""})
        long_id = self.client.get("/api/case", params={"case_id": "x" * 129})
        too_large = self.client.get("/api/case", params={"case_id": "case-1", "prefix": 100_001})
        self.assertEqual(missing.status_code, 422)
        self.assertEqual(long_id.status_code, 422)
        self.assertEqual(too_large.status_code, 422)


if __name__ == "__main__":
    unittest.main()
