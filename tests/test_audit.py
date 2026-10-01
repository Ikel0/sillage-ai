from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sillage import audit


class AuditTrailTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.original_runtime_dir = audit.RUNTIME_DIR
        self.original_database = audit.DATABASE
        audit.RUNTIME_DIR = Path(self.temporary_directory.name)
        audit.DATABASE = audit.RUNTIME_DIR / "audit.db"

    def tearDown(self) -> None:
        audit.RUNTIME_DIR = self.original_runtime_dir
        audit.DATABASE = self.original_database
        self.temporary_directory.cleanup()

    def test_records_compact_json_event(self) -> None:
        first_event_id = audit.record("triage_generated", {"confidence": 0.91}, incident_id="INC-2407")
        event_id = audit.record("operator_review_recorded", {"outcome": "accepted"}, incident_id="INC-2407")
        events = audit.recent_events()

        self.assertEqual(first_event_id, 1)
        self.assertEqual(event_id, 2)
        self.assertEqual(events[0]["event_type"], "operator_review_recorded")
        self.assertEqual(events[0]["incident_id"], "INC-2407")
        self.assertEqual(events[1]["payload"]["confidence"], 0.91)
        self.assertTrue(events[0]["event_hash"])
        self.assertEqual(events[0]["previous_hash"], events[1]["event_hash"])
