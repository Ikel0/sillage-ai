from __future__ import annotations

import asyncio
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from sillage import app as app_module
from sillage import audit
from sillage.app import app

ALICE = "session-alice-0000000001"
BOB = "session-bob-00000000000002"
NOTE = "<b>contexte</b> transmis à Plateforme revenus, voir ticket 4412"


class SessionIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.original = (audit.RUNTIME_DIR, audit.DATABASE)
        audit.RUNTIME_DIR = Path(self.temporary_directory.name)
        audit.DATABASE = audit.RUNTIME_DIR / "sessions.db"
        app_module._write_calls.clear()

    def tearDown(self) -> None:
        audit.RUNTIME_DIR, audit.DATABASE = self.original
        app_module._write_calls.clear()
        self.temporary_directory.cleanup()

    def request(
        self, method: str, path: str, session: str | None, json: object | None = None, ip: str = "203.0.113.20"
    ) -> httpx.Response:
        headers = {"X-Forwarded-For": ip}
        if session:
            headers["X-Sillage-Session"] = session

        async def send() -> httpx.Response:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                return await client.request(method, path, json=json, headers=headers)

        return asyncio.run(send())

    def decide(self, session: str, note: str = NOTE, ip: str = "203.0.113.20") -> httpx.Response:
        trace = self.request("POST", "/api/incidents/INC-2407/analyze", session, ip=ip).json()["meta"]["trace_id"]
        return self.request(
            "POST", "/api/incidents/INC-2407/reviews", session,
            json={"outcome": "needs_evidence", "note": note, "trace_id": trace}, ip=ip,
        )

    def test_two_sessions_never_see_each_other(self) -> None:
        self.assertEqual(self.decide(ALICE).status_code, 200)

        alice = self.request("GET", "/api/audit", ALICE).json()
        bob = self.request("GET", "/api/audit", BOB).json()
        bob_reviews = self.request("GET", "/api/incidents/INC-2407/reviews", BOB).json()

        self.assertEqual([e["event_type"] for e in alice["items"]], ["operator_review_recorded", "triage_generated"])
        self.assertEqual(bob["total"], 0)
        self.assertEqual(bob_reviews["total"], 0)

    def test_receipts_are_numbered_per_session_without_global_ids(self) -> None:
        self.decide(ALICE)
        bob_review = self.decide(BOB).json()["review"]
        alice = self.request("GET", "/api/audit", ALICE).json()["items"]
        bob = self.request("GET", "/api/audit", BOB).json()["items"]
        bob_history = self.request("GET", "/api/incidents/INC-2407/reviews", BOB).json()["items"]

        self.assertEqual([event["receipt"] for event in alice], [2, 1])
        self.assertEqual([event["receipt"] for event in bob], [2, 1])
        self.assertEqual(bob_review["receipt"], 2)
        self.assertEqual(bob_history[0]["receipt"], 2)
        for event in alice + bob + bob_history:
            self.assertNotIn("id", event)
        self.assertNotIn("review_id", bob_review)
        triage = self.request("POST", "/api/incidents/INC-2408/analyze", BOB).json()["meta"]
        self.assertEqual(triage["receipt"], 3)
        self.assertNotIn("audit_event_id", triage)

    def test_request_without_session_reads_nothing(self) -> None:
        self.decide(ALICE)

        self.assertEqual(self.request("GET", "/api/audit", None).json()["total"], 0)
        self.assertEqual(self.request("GET", "/api/audit", "short").json()["total"], 0)

    def test_note_text_is_never_stored_or_returned(self) -> None:
        review = self.decide(ALICE).json()["review"]
        journal = self.request("GET", "/api/audit", ALICE)

        self.assertNotIn("ticket 4412", journal.text)
        self.assertNotIn("<b>", journal.text)
        self.assertNotIn("note", review)
        self.assertEqual(len(review["note_sha256"]), 64)
        payload = journal.json()["items"][0]["payload"]
        self.assertEqual(payload["note_sha256"], review["note_sha256"])
        self.assertEqual(payload["note_length"], len(NOTE))

        connection = sqlite3.connect(audit.DATABASE)
        try:
            stored = " ".join(row[0] for row in connection.execute("select payload from audit_events"))
            sessions = [row[0] for row in connection.execute("select distinct session_key from audit_events")]
        finally:
            connection.close()
        self.assertNotIn("ticket 4412", stored)
        self.assertNotIn(ALICE, sessions)

    def test_each_session_has_its_own_hash_chain(self) -> None:
        self.decide(ALICE)
        self.decide(BOB)

        bob = self.request("GET", "/api/audit", BOB).json()["items"]
        self.assertIsNone(bob[-1]["previous_hash"])
        self.assertEqual(bob[0]["previous_hash"], bob[1]["event_hash"])

    def test_receipts_expire_after_an_hour(self) -> None:
        self.decide(ALICE)
        old = (datetime.now(timezone.utc) - timedelta(hours=1, minutes=1)).isoformat()
        connection = sqlite3.connect(audit.DATABASE)
        try:
            with connection:
                connection.execute("update audit_events set occurred_at = ?", (old,))
        finally:
            connection.close()

        self.assertEqual(self.request("GET", "/api/audit", ALICE).json()["total"], 0)

    def test_recording_is_rate_limited_per_address(self) -> None:
        original = app_module.WRITE_RATE_LIMIT
        app_module.WRITE_RATE_LIMIT = 3
        try:
            codes = [
                self.request("POST", "/api/incidents/INC-2407/reviews", ALICE, json={"outcome": "accepted"},
                             ip="192.0.2.30").status_code
                for _ in range(4)
            ]
            other = self.request("POST", "/api/incidents/INC-2407/reviews", BOB, json={"outcome": "accepted"},
                                 ip="192.0.2.31").status_code
        finally:
            app_module.WRITE_RATE_LIMIT = original

        self.assertEqual(codes, [200, 200, 200, 429])
        self.assertEqual(other, 200)

    def test_rate_limit_reads_the_last_proxy_address(self) -> None:
        original = app_module.WRITE_RATE_LIMIT
        app_module.WRITE_RATE_LIMIT = 2
        try:
            # A visitor rotating a forged left-most address is still counted once.
            codes = [
                self.request("POST", "/api/incidents/INC-2407/reviews", ALICE, json={"outcome": "accepted"},
                             ip=f"10.0.0.{n}, 198.51.100.40").status_code
                for n in range(3)
            ]
        finally:
            app_module.WRITE_RATE_LIMIT = original

        self.assertEqual(codes, [200, 200, 429])


if __name__ == "__main__":
    unittest.main()
