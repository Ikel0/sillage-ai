from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from sillage import app as app_module
from sillage import audit
from sillage.app import app


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.original_runtime_dir = audit.RUNTIME_DIR
        self.original_database = audit.DATABASE
        audit.RUNTIME_DIR = Path(self.temporary_directory.name)
        audit.DATABASE = audit.RUNTIME_DIR / "api-audit.db"
        app_module._write_calls.clear()
    def tearDown(self) -> None:
        audit.RUNTIME_DIR = self.original_runtime_dir
        audit.DATABASE = self.original_database
        self.temporary_directory.cleanup()

    def request(self, method: str, path: str, json: object | None = None) -> httpx.Response:
        async def send() -> httpx.Response:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                return await client.request(
                    method, path, json=json, headers={"X-Sillage-Session": "test-session-api-0001"}
                )

        return asyncio.run(send())

    def test_health_exposes_safety_mode(self) -> None:
        response = self.request("GET", "/api/health")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["autonomous_actions"])
        self.assertIn("X-Request-ID", response.headers)

    def test_control_room_is_served_by_the_application(self) -> None:
        response = self.request("GET", "/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Sillage", response.text)
        self.assertIn("ne relance, ne modifie, ne notifie rien", response.text)
        self.assertIn("Décidé par", response.text)
        self.assertNotIn("intelligence", response.text)

    def test_control_room_javascript_is_served(self) -> None:
        response = self.request("GET", "/assets/app.js")

        self.assertEqual(response.status_code, 200)
        self.assertIn("loadIncidents", response.text)

    def test_triage_is_grounded_and_audited(self) -> None:
        response = self.request("POST", "/api/incidents/INC-2407/analyze")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        selected = next(item for item in payload["report"]["evidence"] if item["source_type"] == "runbook")
        self.assertEqual(selected["source_id"], "runbook.orders-duplicate")
        self.assertFalse(payload["meta"]["automated_action"])
        self.assertEqual(payload["report"]["decision_code"], "CONTAIN_AND_REVIEW")
        self.assertTrue(payload["report"]["provenance"]["evidence_hash"])
        self.assertTrue(payload["meta"]["trace_id"])

        audit_response = self.request("GET", "/api/audit")
        self.assertEqual(audit_response.json()["items"][0]["event_type"], "triage_generated")
        self.assertEqual(audit_response.json()["items"][0]["payload"]["contract"]["version"], "3.2.0")
        self.assertTrue(audit_response.json()["items"][0]["event_hash"])

    def test_operator_review_is_validated_and_audited(self) -> None:
        triage = self.request("POST", "/api/incidents/INC-2408/analyze").json()
        review = self.request(
            "POST",
            "/api/incidents/INC-2408/reviews",
            json={
                "outcome": "needs_evidence",
                "note": "Confirm the producer release payload before any backfill.",
                "trace_id": triage["meta"]["trace_id"],
            },
        )

        self.assertEqual(review.status_code, 200)
        self.assertEqual(review.json()["review"]["outcome"], "needs_evidence")
        self.assertFalse(review.json()["meta"]["automated_action"])
        self.assertTrue(review.json()["review"]["audit_hash"])

        history = self.request("GET", "/api/incidents/INC-2408/reviews")
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.json()["items"][0]["event_type"], "operator_review_recorded")

    def test_review_rejects_an_unknown_outcome(self) -> None:
        response = self.request(
            "POST",
            "/api/incidents/INC-2408/reviews",
            json={"outcome": "execute_now"},
        )

        self.assertEqual(response.status_code, 422)

    def test_unknown_incident_returns_404(self) -> None:
        response = self.request("GET", "/api/incidents/INC-missing")

        self.assertEqual(response.status_code, 404)

    @patch("sillage.app.github_status_snapshot")
    def test_source_sync_is_an_audited_optional_signal(self, mocked_snapshot: object) -> None:
        mocked_snapshot.return_value = {
            "source": "github_status",
            "retrieved_at": "2026-10-01T10:00:00Z",
            "ok": True,
            "indicator": "none",
            "description": "All Systems Operational",
            "source_url": "https://www.githubstatus.com/api/v2/summary.json",
        }

        response = self.request("POST", "/api/sources/github-status/sync")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["snapshot"]["ok"])
