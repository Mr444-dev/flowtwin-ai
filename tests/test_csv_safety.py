from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from flowtwin.csv_safety import safe_csv_value


class CsvSafetyTests(unittest.TestCase):
    def test_spreadsheet_formula_prefixes_are_neutralized(self) -> None:
        for value in ("=1+1", "+SUM(A1:A2)", "-1+2", "@cmd", "\t=1", "  =1+1"):
            with self.subTest(value=value):
                self.assertTrue(safe_csv_value(value).startswith("'"))

    def test_plain_text_and_non_text_values_are_preserved(self) -> None:
        self.assertEqual(safe_csv_value("A_Pending"), "A_Pending")
        self.assertEqual(safe_csv_value(1.25), 1.25)
        self.assertIsNone(safe_csv_value(None))


if __name__ == "__main__":
    unittest.main()
