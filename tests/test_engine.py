from __future__ import annotations

import unittest

from sillage.engine import build_triage_report
from sillage.repository import incident_by_id


class GroundedTriageTests(unittest.TestCase):
    def test_duplicate_incident_selects_the_duplicate_runbook(self) -> None:
        incident = incident_by_id("INC-2407")
        self.assertIsNotNone(incident)

        report = build_triage_report(incident or {})
        selected = next(evidence for evidence in report.evidence if evidence.source_type == "runbook")

        self.assertEqual(selected.source_id, "runbook.orders-duplicate")
        self.assertIn("Contain publication", report.decision)
        self.assertGreaterEqual(report.confidence, 0.8)

    def test_report_carries_contract_runbook_and_observed_signals(self) -> None:
        incident = incident_by_id("INC-2408")
        self.assertIsNotNone(incident)

        report = build_triage_report(incident or {})
        evidence_types = [evidence.source_type for evidence in report.evidence]

        self.assertIn("data_contract", evidence_types)
        self.assertIn("runbook", evidence_types)
        self.assertGreaterEqual(evidence_types.count("signal"), 3)
        self.assertIn("does not change data", report.safety_note)

    def test_unknown_contract_is_not_silently_triaged(self) -> None:
        incident = {
            "id": "INC-test",
            "contract_id": "contract.unknown",
            "severity": "SEV-2",
            "title": "Unknown contract",
            "summary": "Test fixture",
            "signals": [],
        }

        with self.assertRaises(LookupError):
            build_triage_report(incident)
