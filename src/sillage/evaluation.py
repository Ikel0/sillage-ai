from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .engine import build_triage_report
from .repository import incident_by_id, load_collection


@dataclass(frozen=True)
class EvaluationCase:
    incident_id: str
    expected_runbook: str
    expected_decision_fragment: str
    expected_decision_code: str
    expected_gate_state: str


def _selected_runbook(report: dict[str, Any]) -> str | None:
    return report.get("ranking", {}).get("selected_runbook") or next(
        (evidence["source_id"] for evidence in report["evidence"] if evidence["source_type"] == "runbook"),
        None,
    )


def _metric(passed: int, total: int) -> dict[str, Any]:
    return {
        "passed": passed,
        "total": total,
        "score": round(passed / total, 2) if total else 0.0,
    }


def evaluate_grounded_triage() -> dict[str, Any]:
    """Run inspectable regression checks for retrieval, provenance and safety.

    The suite is intentionally compact. It is a release guard for the fixture
    families in this project, not a claim of general incident-response accuracy.
    """

    fixtures = [EvaluationCase(**item) for item in load_collection("golden_cases.json")]
    outcomes: list[dict[str, Any]] = []
    dimensions = {
        "runbook_selection": 0,
        "decision_alignment": 0,
        "provenance_completeness": 0,
        "safety_guard": 0,
    }

    for fixture in fixtures:
        incident = incident_by_id(fixture.incident_id)
        if incident is None:
            outcomes.append(
                {
                    "incident_id": fixture.incident_id,
                    "passed": False,
                    "reason": "fixture references an unknown incident",
                }
            )
            continue

        report = build_triage_report(incident).as_dict()
        selected = _selected_runbook(report)
        checks = {
            "runbook_selection": selected == fixture.expected_runbook,
            "decision_alignment": (
                fixture.expected_decision_fragment.lower() in report["decision"].lower()
                and report["decision_code"] == fixture.expected_decision_code
                and report["gate_state"] == fixture.expected_gate_state
            ),
            "provenance_completeness": bool(report["provenance"].get("evidence_hash"))
            and all(
                evidence.get("content_hash")
                and evidence.get("source_snapshot_id")
                and evidence.get("source_version")
                for evidence in report["evidence"]
            ),
            "safety_guard": report["quality_gate"].get("all_passed")
            and "ne modifie aucune donnée" in report["safety_note"],
        }
        for name, passed in checks.items():
            dimensions[name] += int(passed)
        outcomes.append(
            {
                "incident_id": fixture.incident_id,
                "passed": all(checks.values()),
                "expected_runbook": fixture.expected_runbook,
                "selected_runbook": selected,
                "expected_decision_code": fixture.expected_decision_code,
                "decision_code": report["decision_code"],
                "gate_state": report["gate_state"],
                "checks": checks,
            }
        )

    total = len(fixtures)
    passed = sum(1 for outcome in outcomes if outcome["passed"])
    return {
        "suite": "grounded-triage-v2",
        "passed": passed,
        "total": total,
        "score": round(passed / total, 2) if total else 0.0,
        "note": "Régression hors ligne sur des cas représentatifs : un garde-fou de release, pas un benchmark de production.",
        "metrics": {name: _metric(value, total) for name, value in dimensions.items()},
        "cases": outcomes,
    }
