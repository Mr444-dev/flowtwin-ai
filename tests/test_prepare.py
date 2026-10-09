from __future__ import annotations

import json
import gzip
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from defusedxml.common import DefusedXmlException

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from flowtwin import prepare


def _xes_trace(case_id: str, activity: str = "A_Pending") -> str:
    return f"""<trace>
      <string key="concept:name" value="{case_id}" />
      <event>
        <string key="concept:name" value="A_Submitted" />
        <date key="time:timestamp" value="2017-01-01T10:00:00Z" />
        <string key="lifecycle:transition" value="start" />
      </event>
      <event>
        <string key="concept:name" value="A_Submitted" />
        <date key="time:timestamp" value="2017-01-01T10:00:00Z" />
        <string key="lifecycle:transition" value="complete" />
      </event>
      <event>
        <string key="concept:name" value="{activity}" />
        <date key="time:timestamp" value="2017-01-02T10:00:00Z" />
        <string key="lifecycle:transition" value="complete" />
      </event>
    </trace>"""


class PrepareTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "sample.xes"
        self.db = self.root / "processed" / "flowtwin.sqlite3"

    def _write_log(self, traces: str) -> None:
        self.source.write_text(f"<log>{traces}</log>", encoding="utf-8")

    def test_parse_filters_lifecycle_start_and_classifies_outcome(self) -> None:
        self._write_log(_xes_trace("case-1"))
        with patch.object(prepare, "DB_PATH", self.db):
            result = prepare.prepare_data(self.source)

        con = sqlite3.connect(self.db)
        try:
            row = con.execute("SELECT outcome, is_complete, event_count, events_json FROM cases").fetchone()
        finally:
            con.close()
        events = json.loads(row[3])
        self.assertEqual((row[0], row[1], row[2]), ("accepted", 1, 2))
        self.assertEqual([event["a"] for event in events], ["A_Submitted", "A_Pending"])
        self.assertEqual(result["quality"]["complete_cases"], 1)

    def test_offer_attributes_from_trace_are_not_visible_before_event(self) -> None:
        trace = _xes_trace("case-1").replace(
            '<string key="concept:name" value="case-1" />',
            '<string key="concept:name" value="case-1" />'
            '<float key="case:CreditScore" value="650" />'
            '<float key="case:RequestedAmount" value="12000" />',
        ).replace(
            '<string key="concept:name" value="A_Pending" />',
            '<string key="concept:name" value="A_Pending" />'
            '<float key="case:CreditScore" value="700" />',
        )
        self._write_log(trace)
        with patch.object(prepare, "DB_PATH", self.db):
            prepare.prepare_data(self.source)
        con = sqlite3.connect(self.db)
        try:
            initial, events_json = con.execute("SELECT case_attrs_json, events_json FROM cases").fetchone()
        finally:
            con.close()
        initial_attrs = json.loads(initial)
        events = json.loads(events_json)
        from flowtwin.features import build_features

        first = build_features(events, 1, initial_attrs)
        last = build_features(events, 2, initial_attrs)
        self.assertEqual(first["requested_amount"], 12000)
        self.assertEqual(first["credit_score"], -1.0)
        self.assertEqual(last["credit_score"], 700)

    def test_nonterminal_last_event_is_censored(self) -> None:
        self._write_log(_xes_trace("case-1", "W_Assess"))
        with patch.object(prepare, "DB_PATH", self.db):
            prepare.prepare_data(self.source)
        con = sqlite3.connect(self.db)
        try:
            outcome, complete = con.execute("SELECT outcome, is_complete FROM cases").fetchone()
        finally:
            con.close()
        self.assertEqual((outcome, complete), ("censored", 0))

    def test_malicious_dtd_is_rejected(self) -> None:
        self.source.write_text(
            '<!DOCTYPE log [<!ENTITY xxe SYSTEM "file:///does-not-exist">]><log>&xxe;</log>',
            encoding="utf-8",
        )
        with patch.object(prepare, "DB_PATH", self.db):
            with self.assertRaises(DefusedXmlException):
                prepare.prepare_data(self.source)
        self.assertFalse(self.db.exists())
        self.assertEqual(list(self.db.parent.glob("*.building")), [])

    def test_empty_parse_preserves_existing_database(self) -> None:
        self._write_log("")
        self.db.parent.mkdir(parents=True)
        self.db.write_bytes(b"existing database sentinel")
        with patch.object(prepare, "DB_PATH", self.db):
            with self.assertRaisesRegex(ValueError, "No case with a valid ID"):
                prepare.prepare_data(self.source)
        self.assertEqual(self.db.read_bytes(), b"existing database sentinel")
        self.assertEqual(list(self.db.parent.glob("*.building")), [])

    def test_trace_event_limit_is_enforced(self) -> None:
        self._write_log(_xes_trace("case-1"))
        with patch.object(prepare, "DB_PATH", self.db), patch.object(prepare, "MAX_EVENTS_PER_TRACE", 1):
            with self.assertRaisesRegex(ValueError, "case exceeds the limit"):
                prepare.prepare_data(self.source)
        self.assertFalse(self.db.exists())

    def test_total_event_limit_is_enforced(self) -> None:
        self._write_log(_xes_trace("case-1"))
        with patch.object(prepare, "DB_PATH", self.db), patch.object(prepare, "MAX_TOTAL_EVENTS", 2):
            with self.assertRaisesRegex(ValueError, "limit of 2 events"):
                prepare.prepare_data(self.source)
        self.assertFalse(self.db.exists())

    def test_case_limit_is_enforced(self) -> None:
        self._write_log(_xes_trace("case-1") + _xes_trace("case-2"))
        with patch.object(prepare, "DB_PATH", self.db), patch.object(prepare, "MAX_CASES", 1):
            with self.assertRaisesRegex(ValueError, "limit of 1 cases"):
                prepare.prepare_data(self.source)
        self.assertFalse(self.db.exists())

    def test_distinct_activity_limit_is_enforced(self) -> None:
        self._write_log(_xes_trace("case-1"))
        with patch.object(prepare, "DB_PATH", self.db), patch.object(prepare, "MAX_DISTINCT_ACTIVITIES", 1):
            with self.assertRaisesRegex(ValueError, "distinct activities"):
                prepare.prepare_data(self.source)
        self.assertFalse(self.db.exists())

    def test_event_attribute_count_limit_is_enforced(self) -> None:
        self._write_log(_xes_trace("case-1"))
        with patch.object(prepare, "DB_PATH", self.db), patch.object(prepare, "MAX_EVENT_ATTRIBUTES", 2):
            with self.assertRaisesRegex(ValueError, "event exceeds the limit of 2 attributes"):
                prepare.prepare_data(self.source)
        self.assertFalse(self.db.exists())

    def test_trace_attribute_count_limit_is_enforced(self) -> None:
        trace = _xes_trace("case-1").replace(
            '<string key="concept:name" value="case-1" />',
            '<string key="concept:name" value="case-1" />'
            '<string key="unused" value="discarded" />',
        )
        self._write_log(trace)
        with patch.object(prepare, "DB_PATH", self.db), patch.object(prepare, "MAX_TRACE_ATTRIBUTES", 1):
            with self.assertRaisesRegex(ValueError, "case exceeds the limit of 1 trace attributes"):
                prepare.prepare_data(self.source)
        self.assertFalse(self.db.exists())

    def test_attribute_value_length_limit_is_enforced(self) -> None:
        self._write_log(_xes_trace("case-1"))
        with patch.object(prepare, "DB_PATH", self.db), patch.object(prepare, "MAX_ATTRIBUTE_VALUE_CHARS", 5):
            with self.assertRaisesRegex(ValueError, "attribute value exceeds the limit"):
                prepare.prepare_data(self.source)
        self.assertFalse(self.db.exists())

    def test_retained_data_per_trace_limit_is_enforced(self) -> None:
        self._write_log(_xes_trace("case-1"))
        with patch.object(prepare, "DB_PATH", self.db), patch.object(prepare, "MAX_RETAINED_CHARS_PER_TRACE", 10):
            with self.assertRaisesRegex(ValueError, "retained event data"):
                prepare.prepare_data(self.source)
        self.assertFalse(self.db.exists())

    def test_gzip_log_is_supported(self) -> None:
        compressed = self.root / "sample.xes.gz"
        with gzip.open(compressed, "wb") as stream:
            stream.write(f"<log>{_xes_trace('case-1')}</log>".encode("utf-8"))
        with patch.object(prepare, "DB_PATH", self.db):
            prepare.prepare_data(compressed)
        self.assertTrue(self.db.exists())

    def test_decompressed_size_limit_is_enforced(self) -> None:
        self._write_log(_xes_trace("case-1"))
        with patch.object(prepare, "DB_PATH", self.db), patch.object(prepare, "MAX_UNCOMPRESSED_BYTES", 10):
            with self.assertRaisesRegex(ValueError, "decompressed XES file exceeds the"):
                prepare.prepare_data(self.source)
        self.assertFalse(self.db.exists())

    def test_invalid_timestamps_are_counted_and_skipped(self) -> None:
        trace = _xes_trace("case-1").replace(
            'value="2017-01-02T10:00:00Z"', 'value="not-a-timestamp"', 1
        )
        self._write_log(trace)
        with patch.object(prepare, "DB_PATH", self.db):
            result = prepare.prepare_data(self.source)
        self.assertEqual(result["quality"]["events_invalid_timestamp"], 1)
        con = sqlite3.connect(self.db)
        try:
            event_count = con.execute("SELECT event_count FROM cases").fetchone()[0]
        finally:
            con.close()
        self.assertEqual(event_count, 1)

    def test_duplicate_case_ids_are_counted_and_skipped(self) -> None:
        self._write_log(_xes_trace("case-1") + _xes_trace("case-1", "A_Denied"))
        with patch.object(prepare, "DB_PATH", self.db):
            result = prepare.prepare_data(self.source)
        self.assertEqual(result["quality"]["cases_read"], 1)
        self.assertEqual(result["quality"]["duplicate_case_ids"], 1)

    def test_unsupported_extension_and_empty_file_are_rejected(self) -> None:
        wrong_type = self.root / "sample.xml"
        wrong_type.write_text("<log/>", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, r"\.xes"):
            prepare.prepare_data(wrong_type)
        self.source.write_bytes(b"")
        with self.assertRaisesRegex(ValueError, "file is empty"):
            prepare.prepare_data(self.source)


if __name__ == "__main__":
    unittest.main()
