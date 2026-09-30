from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from .repository import contract_by_id, runbooks


SEVERITY_WEIGHT = {"SEV-1": 1.0, "SEV-2": 0.72, "SEV-3": 0.45}


@dataclass(frozen=True)
class Evidence:
    source_type: str
    source_id: str
    title: str
    excerpt: str
    confidence: float


@dataclass(frozen=True)
class TriageReport:
    incident_id: str
    generated_at: str
    decision: str
    confidence: float
    impact: str
    hypothesis: str
    first_actions: list[str]
    escalation: str
    safety_note: str
    evidence: list[Evidence]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _tokens(value: str) -> set[str]:
    return {
        token.strip(".,:;()[]{}\"'/%").lower()
        for token in value.split()
        if len(token.strip(".,:;()[]{}\"'/%")) > 2
    }


def _incident_text(incident: dict[str, Any]) -> str:
    signal_text = " ".join(
        f"{signal['name']} {signal['value']} {signal['threshold']}" for signal in incident["signals"]
    )
    return f"{incident['title']} {incident['summary']} {signal_text}"


def _rank_runbook(incident: dict[str, Any], runbook: dict[str, Any]) -> float:
    incident_terms = _tokens(_incident_text(incident))
    symptom_terms = set(runbook["symptoms"])
    lexical_overlap = len(incident_terms & symptom_terms) / max(len(symptom_terms), 1)
    contract_bonus = 0.64 if incident["contract_id"] == runbook["contract_id"] else 0
    severity_bonus = SEVERITY_WEIGHT.get(incident["severity"], 0.4) * 0.16
    return min(contract_bonus + (lexical_overlap * 0.20) + severity_bonus, 0.99)


def _hypothesis(incident: dict[str, Any]) -> str:
    text = _incident_text(incident).lower()
    if "duplicate" in text or "replay" in text:
        return "A replay reached the aggregation path without a confirmed idempotency boundary."
    if "schema" in text or "payload" in text or "occurred_at" in text:
        return "A producer release introduced a payload that is incompatible with the published event contract."
    if "null" in text or "key" in text:
        return "The upstream extract is incomplete and a required business key is missing at source."
    return "The evidence is insufficient to identify one root cause. Preserve the current gate and continue triage."


def _decision(incident: dict[str, Any]) -> str:
    if incident["severity"] == "SEV-1":
        return "Contain publication and investigate with the owning team."
    return "Keep the quality gate active and investigate before replay or release."


def build_triage_report(incident: dict[str, Any]) -> TriageReport:
    contract = contract_by_id(incident["contract_id"])
    if contract is None:
        raise LookupError(f"No contract found for {incident['contract_id']}")

    ranked = sorted(
        ((runbook, _rank_runbook(incident, runbook)) for runbook in runbooks()),
        key=lambda item: item[1],
        reverse=True,
    )
    if not ranked:
        raise LookupError("No runbooks available for grounded triage")

    selected_runbook, runbook_score = ranked[0]
    signal_evidence = [
        Evidence(
            source_type="signal",
            source_id=f"{incident['id']}:{signal['name']}",
            title=signal["name"],
            excerpt=f"Observed {signal['value']}; expected {signal['threshold']}.",
            confidence=0.92,
        )
        for signal in incident["signals"]
    ]
    contract_evidence = Evidence(
        source_type="data_contract",
        source_id=contract["id"],
        title=f"{contract['dataset']} contract",
        excerpt=f"Tier {contract['tier']}; owner {contract['owner']}; SLA {contract['sla_minutes']} min.",
        confidence=0.98,
    )
    runbook_evidence = Evidence(
        source_type="runbook",
        source_id=selected_runbook["id"],
        title=selected_runbook["title"],
        excerpt=selected_runbook["risk"],
        confidence=round(runbook_score, 2),
    )
    confidence = round(min(0.97, (runbook_score + 0.22)), 2)

    return TriageReport(
        incident_id=incident["id"],
        generated_at=datetime.now(timezone.utc).isoformat(),
        decision=_decision(incident),
        confidence=confidence,
        impact=selected_runbook["risk"],
        hypothesis=_hypothesis(incident),
        first_actions=selected_runbook["steps"],
        escalation=selected_runbook["escalation"],
        safety_note=(
            "Sillage proposes a grounded triage plan. It does not change data, trigger a replay, "
            "or notify an owner automatically."
        ),
        evidence=[contract_evidence, runbook_evidence, *signal_evidence],
    )
