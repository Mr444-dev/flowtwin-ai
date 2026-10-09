from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from flowtwin.features import build_features
from flowtwin.sampling import snapshot_prefix_counts, stage_for_prefix


class FeatureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.events = [
            {"a": "A_Submitted", "t": "2020-01-01T10:00:00+01:00", "x": {}},
            {
                "a": "W_Validate",
                "t": "2020-01-01T11:00:00+01:00",
                "x": {"case:RequestedAmount": 12000, "case:LoanGoal": "Home improvement"},
            },
            {"a": "A_Pending", "t": "2020-01-02T10:00:00+01:00", "x": {}},
        ]

    def test_prefix_does_not_read_future_events(self) -> None:
        first = build_features(self.events, 1)
        self.assertEqual(first["current_activity"], "A_Submitted")
        self.assertEqual(first["elapsed_hours"], 0)
        self.assertIsNone(first["requested_amount"])
        self.assertEqual(first["loan_goal"], "Unknown")

    def test_prefix_features_use_only_values_already_seen(self) -> None:
        second = build_features(self.events, 2)
        self.assertEqual(second["current_activity"], "W_Validate")
        self.assertEqual(second["elapsed_hours"], 1)
        self.assertEqual(second["requested_amount"], 12000.0)
        self.assertEqual(second["loan_goal"], "Home improvement")

    def test_timezone_offsets_are_normalized(self) -> None:
        features = build_features(self.events, 2)
        self.assertEqual(features["hours_since_previous"], 1)

    def test_prefix_bounds_are_checked(self) -> None:
        for prefix in (0, 4):
            with self.subTest(prefix=prefix), self.assertRaises(ValueError):
                build_features(self.events, prefix)

    def test_snapshot_policy_uses_observed_event_counts(self) -> None:
        self.assertEqual(snapshot_prefix_counts(100), (1, 3, 5, 10, 20, 40))
        self.assertEqual(snapshot_prefix_counts(50), (1, 3, 5, 10, 20, 40))
        self.assertEqual(snapshot_prefix_counts(2), (1,))
        self.assertEqual(snapshot_prefix_counts(1), ())
        self.assertEqual(
            [stage_for_prefix(p) for p in (1, 3, 5, 10, 20)],
            ["early", "early", "mid", "mid", "late"],
        )
        with self.assertRaises(ValueError):
            stage_for_prefix(0)


if __name__ == "__main__":
    unittest.main()
