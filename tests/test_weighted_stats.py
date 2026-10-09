from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from flowtwin.weighted_stats import weighted_quantile


class WeightedStatisticsTests(unittest.TestCase):
    def test_equal_weights_match_empirical_inverse_cdf(self) -> None:
        self.assertEqual(weighted_quantile([1, 2, 3, 4], [1, 1, 1, 1], 0.50), 2)
        self.assertEqual(weighted_quantile([1, 2, 3, 4], [1, 1, 1, 1], 0.90), 4)

    def test_weights_can_represent_equal_case_mass(self) -> None:
        self.assertEqual(weighted_quantile([0, 10, 10], [0.5, 0.25, 0.25], 0.50), 0)
        self.assertEqual(weighted_quantile([0, 10, 10], [0.5, 0.25, 0.25], 0.51), 10)

    def test_invalid_weights_and_quantiles_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            weighted_quantile([], [], 0.5)
        with self.assertRaises(ValueError):
            weighted_quantile([1], [-1], 0.5)
        with self.assertRaises(ValueError):
            weighted_quantile([1], [1], 1.1)


if __name__ == "__main__":
    unittest.main()
