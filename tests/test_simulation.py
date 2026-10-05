from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

import httpx

from sillage import app as app_module
from sillage import audit
from sillage.app import app
from sillage.engine import build_triage_report, simulate_routing
from sillage.repository import incident_by_id


def _incident(incident_id: str) -> dict:
    incident = incident_by_id(incident_id)
    assert incident is not None
    return incident


class SimulationEngineTests(unittest.TestCase):
    def test_unedited_incident_matches_the_triage_of_record(self) -> None:
        for incident_id in ("INC-2407", "INC-2408", "INC-2409"):
            incident = _incident(incident_id)
            simulation = simulate_routing(incident)
            report = build_triage_report(incident)

            self.assertEqual(simulation["match_score"], report.match_score)
            self.assertEqual(simulation["decision_code"], report.decision_code)
            self.assertEqual(simulation["selected_runbook"], report.ranking["selected_runbook"])
            self.assertEqual(simulation["candidates"], report.ranking["candidates"])

    def test_components_add_up_term_by_term(self) -> None:
        simulation = simulate_routing(_incident("INC-2407"))
        top = simulation["candidates"][0]

        self.assertEqual(
            top["components"],
            {"contract_affinity": 0.64, "symptom_overlap": 0.15, "severity_context": 0.16},
        )
        self.assertEqual(simulation["match_score"], 0.95)
        self.assertEqual(simulation["detected_terms"], ["doublons", "event_id", "rejeu"])

    def test_setting_aside_symptoms_lowers_the_score(self) -> None:
        simulation = simulate_routing(_incident("INC-2407"), {"doublons", "event_id"})

        self.assertEqual(simulation["candidates"][0]["matched_terms"], ["rejeu"])
        self.assertEqual(simulation["match_score"], 0.85)
        self.assertEqual(simulation["selected_runbook"], "runbook.orders-duplicate")
        self.assertEqual(simulation["excluded_terms"], ["doublons", "event_id"])

    def test_no_shared_symptom_means_abstention_even_at_the_threshold(self) -> None:
        simulation = simulate_routing(_incident("INC-2407"), {"doublons", "event_id", "rejeu"})

        self.assertEqual(simulation["match_score"], 0.80)
        self.assertIsNone(simulation["selected_runbook"])
        self.assertEqual(simulation["decision_code"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(simulation["gate_state"], "review_required")

    def test_lower_severity_changes_weight_and_decision(self) -> None:
        simulation = simulate_routing({**_incident("INC-2407"), "severity": "SEV-3"})

        self.assertEqual(simulation["candidates"][0]["components"]["severity_context"], 0.07)
        self.assertEqual(simulation["match_score"], 0.86)
        self.assertEqual(simulation["decision_code"], "HOLD_FOR_REVIEW")

    def test_other_contract_moves_the_ranking_and_abstains(self) -> None:
        simulation = simulate_routing({**_incident("INC-2407"), "contract_id": "contract.customer-events.v2"})

        self.assertEqual(simulation["candidates"][0]["runbook_id"], "runbook.events-schema")
        self.assertEqual(simulation["decision_code"], "INSUFFICIENT_EVIDENCE")
        orders = next(c for c in simulation["candidates"] if c["runbook_id"] == "runbook.orders-duplicate")
        self.assertEqual(orders["score"], 0.31)

    def test_edited_signal_text_can_add_a_symptom(self) -> None:
        incident = _incident("INC-2407")
        signals = [dict(signal) for signal in incident["signals"]]
        signals[1]["value"] = "retry sans idempotence"
        simulation = simulate_routing({**incident, "signals": signals})

        self.assertIn("idempotence", simulation["candidates"][0]["matched_terms"])
        self.assertEqual(simulation["match_score"], 1.0)

    def test_unknown_contract_is_refused(self) -> None:
        with self.assertRaises(LookupError):
            simulate_routing({**_incident("INC-2407"), "contract_id": "contract.unknown"})


class SimulationApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.original = (audit.RUNTIME_DIR, audit.DATABASE)
        audit.RUNTIME_DIR = Path(self.temporary_directory.name)
        audit.DATABASE = audit.RUNTIME_DIR / "simulation-audit.db"
        app_module._simulation_calls.clear()

    def tearDown(self) -> None:
        audit.RUNTIME_DIR, audit.DATABASE = self.original
        self.temporary_directory.cleanup()
        app_module._simulation_calls.clear()

    def request(
        self, method: str, path: str, json: object | None = None, content: bytes | None = None, ip: str = "203.0.113.7"
    ) -> httpx.Response:
        async def send() -> httpx.Response:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                return await client.request(
                    method, path, json=json, content=content, headers={"X-Forwarded-For": ip}
                )

        return asyncio.run(send())

    def test_simulation_recomputes_without_writing_to_the_journal(self) -> None:
        response = self.request(
            "POST",
            "/api/incidents/INC-2407/simulate",
            json={"severity": "SEV-2", "excluded_terms": ["doublons"]},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["meta"]["recorded"])
        self.assertEqual(body["simulation"]["severity"], "SEV-2")
        self.assertEqual(body["simulation"]["candidates"][0]["matched_terms"], ["event_id", "rejeu"])
        self.assertEqual(self.request("GET", "/api/audit").json()["total"], 0)

    def test_dropping_signals_removes_their_text(self) -> None:
        response = self.request(
            "POST",
            "/api/incidents/INC-2408/simulate",
            json={"signals": [{"index": 0, "value": "", "included": False},
                              {"index": 1, "value": "", "included": False},
                              {"index": 2, "value": "", "included": False}]},
        )

        self.assertEqual(response.status_code, 200)
        simulation = response.json()["simulation"]
        self.assertLess(simulation["match_score"], simulate_routing(_incident("INC-2408"))["match_score"])

    def test_invalid_edits_are_rejected(self) -> None:
        self.assertEqual(
            self.request("POST", "/api/incidents/INC-2407/simulate", json={"contract_id": "contract.unknown"}).status_code,
            422,
        )
        self.assertEqual(
            self.request("POST", "/api/incidents/INC-2407/simulate",
                         json={"signals": [{"index": 9, "value": "x"}]}).status_code,
            422,
        )
        self.assertEqual(
            self.request("POST", "/api/incidents/INC-2407/simulate", json={"severity": "SEV-9"}).status_code,
            422,
        )
        self.assertEqual(self.request("POST", "/api/incidents/INC-9999/simulate", json={}).status_code, 404)

    def test_visitors_are_isolated_and_the_registry_is_untouched(self) -> None:
        before = self.request("GET", "/api/incidents/INC-2407").json()
        first = self.request(
            "POST", "/api/incidents/INC-2407/simulate",
            json={"contract_id": "contract.inventory.v1", "signals": [{"index": 0, "value": "autre", "included": False}]},
            ip="198.51.100.1",
        ).json()["simulation"]
        second = self.request("POST", "/api/incidents/INC-2407/simulate", json={}, ip="198.51.100.2").json()["simulation"]
        after = self.request("GET", "/api/incidents/INC-2407").json()

        self.assertEqual(first["decision_code"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(second["match_score"], 0.95)
        self.assertEqual(second["selected_runbook"], "runbook.orders-duplicate")
        self.assertEqual(before, after)

    def test_visitor_text_is_never_echoed_back(self) -> None:
        payload = '<img src=x onerror="alert(1)"><script>alert(2)</script> idempotence'
        response = self.request(
            "POST", "/api/incidents/INC-2407/simulate",
            json={"signals": [{"index": 1, "value": payload}]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("<script", response.text)
        self.assertNotIn("onerror", response.text)
        # The text still goes through the real scoring: the known symptom counts.
        self.assertIn("idempotence", response.json()["simulation"]["candidates"][0]["matched_terms"])

    def test_size_limits(self) -> None:
        too_long = self.request(
            "POST", "/api/incidents/INC-2407/simulate", json={"signals": [{"index": 0, "value": "x" * 201}]}
        )
        too_big = self.request(
            "POST", "/api/incidents/INC-2407/simulate", content=b'{"excluded_terms": []}' + b" " * 20_000
        )
        too_many = self.request(
            "POST", "/api/incidents/INC-2407/simulate", json={"excluded_terms": ["rejeu"] * 33}
        )

        self.assertEqual(too_long.status_code, 422)
        self.assertEqual(too_big.status_code, 413)
        self.assertEqual(too_many.status_code, 422)

    def test_rate_limit_is_per_address(self) -> None:
        original = app_module.SIMULATION_RATE_LIMIT
        app_module.SIMULATION_RATE_LIMIT = 3
        try:
            codes = [
                self.request("POST", "/api/incidents/INC-2407/simulate", json={}, ip="192.0.2.10").status_code
                for _ in range(4)
            ]
            other = self.request("POST", "/api/incidents/INC-2407/simulate", json={}, ip="192.0.2.11").status_code
        finally:
            app_module.SIMULATION_RATE_LIMIT = original

        self.assertEqual(codes, [200, 200, 200, 429])
        self.assertEqual(other, 200)


if __name__ == "__main__":
    unittest.main()
