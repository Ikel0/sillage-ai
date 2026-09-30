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


def _selected_runbook(report: dict[str, Any]) -> str | None:
    return next(
        (evidence["source_id"] for evidence in report["evidence"] if evidence["source_type"] == "runbook"),
        None,
    )


def evaluate_grounded_triage() -> dict[str, Any]:
    """Run a small offline regression suite against known, representative incidents."""
    fixtures = [EvaluationCase(**item) for item in load_collection("golden_cases.json")]
    outcomes: list[dict[str, Any]] = []

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
        is_expected_runbook = selected == fixture.expected_runbook
        has_expected_decision = fixture.expected_decision_fragment.lower() in report["decision"].lower()
        outcomes.append(
            {
                "incident_id": fixture.incident_id,
                "passed": is_expected_runbook and has_expected_decision,
                "expected_runbook": fixture.expected_runbook,
                "selected_runbook": selected,
                "expected_decision_fragment": fixture.expected_decision_fragment,
                "decision": report["decision"],
            }
        )

    passed = sum(1 for outcome in outcomes if outcome["passed"])
    return {
        "suite": "grounded-triage-v1",
        "passed": passed,
        "total": len(outcomes),
        "score": round(passed / len(outcomes), 2) if outcomes else 0.0,
        "cases": outcomes,
    }
