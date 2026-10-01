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
        self.assertEqual(report.decision_code, "HOLD_FOR_REVIEW")
        self.assertEqual(report.gate_state, "review_required")
        self.assertTrue(report.quality_gate["all_passed"])
        self.assertTrue(report.provenance["evidence_hash"])
        self.assertTrue(all(evidence.content_hash for evidence in report.evidence))
        self.assertGreaterEqual(len(report.impact), 2)

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

    def test_weak_signal_abstains_instead_of_forcing_a_runbook(self) -> None:
        incident = {
            "id": "INC-weak-evidence",
            "contract_id": "contract.orders.v3",
            "severity": "SEV-2",
            "title": "Unexpected telemetry anomaly",
            "summary": "A monitor shows a pattern that has not been described in an active operating guide.",
            "opened_at": "2026-10-01T10:00:00Z",
            "signals": [
                {
                    "kind": "quality",
                    "name": "unclassified telemetry pattern",
                    "value": "present",
                    "threshold": "not recorded",
                    "observed_at": "2026-10-01T09:59:00Z",
                    "source_snapshot_id": "quality.unclassified.2026-10-01T0959Z",
                }
            ],
        }

        report = build_triage_report(incident)

        self.assertEqual(report.decision_code, "INSUFFICIENT_EVIDENCE")
        self.assertEqual(report.gate_state, "review_required")
        self.assertIsNone(report.ranking["selected_runbook"])
        self.assertFalse(report.quality_gate["all_passed"])
        self.assertNotIn("runbook", [evidence.source_type for evidence in report.evidence])
        self.assertLess(report.confidence, 0.4)
