from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from sillage import audit
from sillage.app import app


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.original_runtime_dir = audit.RUNTIME_DIR
        self.original_database = audit.DATABASE
        audit.RUNTIME_DIR = Path(self.temporary_directory.name)
        audit.DATABASE = audit.RUNTIME_DIR / "api-audit.db"
    def tearDown(self) -> None:
        audit.RUNTIME_DIR = self.original_runtime_dir
        audit.DATABASE = self.original_database
        self.temporary_directory.cleanup()

    def request(self, method: str, path: str) -> httpx.Response:
        async def send() -> httpx.Response:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                return await client.request(method, path)

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
        self.assertIn("data incident intelligence", response.text)

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

        audit_response = self.request("GET", "/api/audit")
        self.assertEqual(audit_response.json()["items"][0]["event_type"], "triage_generated")

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
