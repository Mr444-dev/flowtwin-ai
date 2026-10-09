from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

TRAINING_DEPS_AVAILABLE = all(
    importlib.util.find_spec(name) is not None for name in ("numpy", "pandas", "sklearn", "joblib")
)


@unittest.skipUnless(TRAINING_DEPS_AVAILABLE, "Install the project dependencies to run the model smoke test")
class TrainingSmokeTests(unittest.TestCase):
    def test_training_pipeline_writes_case_weighted_metrics_and_artifacts(self) -> None:
        from flowtwin import train

        temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        db_path = root / "synthetic.sqlite3"
        artifacts = root / "artifacts"
        reports = root / "reports"
        metrics_path = reports / "metrics.json"
        _write_synthetic_database(db_path)

        with (
            patch.object(train, "DB_PATH", db_path),
            patch.object(train, "ARTIFACTS_DIR", artifacts),
            patch.object(train, "REPORTS_DIR", reports),
            patch.object(train, "METRICS_PATH", metrics_path),
        ):
            metrics = train.train_model()

        self.assertEqual(metrics["snapshot_policy"]["prefix_event_counts"], [1, 3, 5, 10, 20, 40])
        self.assertEqual(metrics["evaluation_weighting"], "equal total weight per case, divided among its observed checkpoints")
        self.assertEqual(metrics["case_counts"], {"train": 84, "validation": 18, "test": 18})
        self.assertEqual(metrics["snapshot_counts"], {"train": 504, "validation": 108, "test": 108})
        self.assertTrue((artifacts / "remaining_time.joblib").is_file())
        self.assertTrue((reports / "test_predictions.csv").is_file())
        self.assertEqual(json.loads(metrics_path.read_text(encoding="utf-8"))["test"]["mae_hours"], metrics["test"]["mae_hours"])


def _write_synthetic_database(path: Path) -> None:
    con = sqlite3.connect(path)
    con.execute(
        """CREATE TABLE cases (
            case_id TEXT PRIMARY KEY, started_at TEXT, ended_at TEXT, terminal_activity TEXT,
            outcome TEXT, event_count INTEGER, is_complete INTEGER, case_attrs_json TEXT, events_json TEXT
        )"""
    )
    base = datetime(2020, 1, 1, tzinfo=timezone.utc)
    activities = ["A_Submitted", "W_Validate", "O_Sent", "A_Validating", "W_Assess", "A_Pending"]
    rows = []
    for case_number in range(120):
        start = base + timedelta(days=case_number)
        duration_hours = 2 + case_number % 6
        events = []
        for event_number in range(41):
            activity = "A_Pending" if event_number == 40 else activities[(event_number + case_number % 3) % 5]
            timestamp = start + timedelta(hours=duration_hours * event_number / 40)
            events.append({"a": activity, "t": timestamp.isoformat(), "l": "complete", "x": {}})
        attrs = {
            "case:RequestedAmount": 5000 + (case_number % 20) * 500,
            "case:LoanGoal": "Home improvement" if case_number % 2 else "Car",
            "case:ApplicationType": "New credit" if case_number % 3 else "Existing loan takeover",
        }
        rows.append(
            (
                f"synthetic-{case_number:03d}",
                events[0]["t"],
                events[-1]["t"],
                "A_Pending",
                "accepted",
                len(events),
                1,
                json.dumps(attrs),
                json.dumps(events),
            )
        )
    con.executemany("INSERT INTO cases VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    con.commit()
    con.close()


if __name__ == "__main__":
    unittest.main()
