from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from .repository import canonical_hash, contract_by_id, runbooks, validate_registry


SEVERITY_WEIGHT = {"SEV-1": 1.0, "SEV-2": 0.72, "SEV-3": 0.45}
MINIMUM_ROUTING_SCORE = 0.80
TRIAGE_POLICY_VERSION = "triage-policy-v2"


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    source_type: str
    source_id: str
    title: str
    excerpt: str
    source_version: str
    observed_at: str
    source_snapshot_id: str
    content_hash: str


@dataclass(frozen=True)
class Impact:
    consumer: str
    tier: str
    reason: str
    recommended_action: str


@dataclass(frozen=True)
class QualityCheck:
    id: str
    label: str
    status: str
    detail: str


@dataclass(frozen=True)
class TriageReport:
    incident_id: str
    generated_at: str
    decision_code: str
    decision: str
    gate_state: str
    match_score: float
    impact: list[Impact]
    impact_summary: str
    hypothesis: str
    first_actions: list[str]
    escalation: str
    safety_note: str
    evidence: list[Evidence]
    ranking: dict[str, Any]
    quality_gate: dict[str, Any]
    provenance: dict[str, Any]

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


def _rank_runbook(incident: dict[str, Any], runbook: dict[str, Any]) -> dict[str, Any]:
    incident_terms = _tokens(_incident_text(incident))
    symptom_terms = {str(term).lower() for term in runbook["symptoms"]}
    matched_terms = sorted(incident_terms & symptom_terms)
    lexical_overlap = len(matched_terms) / max(len(symptom_terms), 1)
    contract_match = incident["contract_id"] == runbook["contract_id"]
    contract_score = 0.64 if contract_match else 0.0
    lexical_score = lexical_overlap * 0.20
    severity_score = SEVERITY_WEIGHT.get(incident["severity"], 0.4) * 0.16
    score = contract_score + lexical_score + severity_score
    eligible = contract_match and bool(matched_terms) and score >= MINIMUM_ROUTING_SCORE
    return {
        "runbook_id": runbook["id"],
        "title": runbook["title"],
        "version": runbook["version"],
        "score": round(score, 2),
        "contract_match": contract_match,
        "matched_terms": matched_terms,
        "components": {
            "contract_affinity": round(contract_score, 2),
            "symptom_overlap": round(lexical_score, 2),
            "severity_context": round(severity_score, 2),
        },
        "eligible": eligible,
    }


def _hypothesis(incident: dict[str, Any], grounded: bool) -> str:
    if not grounded:
        return (
            "The available signals do not match an active runbook strongly enough. "
            "Keep the current control in place and ask the contract owner for the missing context."
        )

    text = _incident_text(incident).lower()
    if "duplicate" in text or "replay" in text:
        return "A replay reached the aggregation path without a confirmed idempotency boundary."
    if "schema" in text or "payload" in text or "occurred_at" in text:
        return "A producer release introduced a payload that is incompatible with the published event contract."
    if "null" in text or "key" in text:
        return "The upstream extract is incomplete and a required business key is missing at source."
    return "The evidence supports a gated investigation, but not a single root cause."


def _decision(incident: dict[str, Any], grounded: bool) -> tuple[str, str, str]:
    if not grounded:
        return (
            "INSUFFICIENT_EVIDENCE",
            "review_required",
            "Keep the current quality control in place and gather contract-owner context before any replay or release.",
        )
    if incident["severity"] == "SEV-1":
        return (
            "CONTAIN_AND_REVIEW",
            "blocked",
            "Contain publication and investigate with the owning team.",
        )
    return (
        "HOLD_FOR_REVIEW",
        "review_required",
        "Keep the quality gate active and investigate before replay or release.",
    )


def _impact(contract: dict[str, Any], gate_state: str) -> list[Impact]:
    if gate_state == "blocked":
        action = "Do not publish a new affected asset until the contract owner confirms a safe correction."
    else:
        action = "Keep this consumer on review until the contract checks and owner decision are complete."
    return [
        Impact(
            consumer=consumer["id"],
            tier=consumer["tier"],
            reason=consumer["reason"],
            recommended_action=action,
        )
        for consumer in contract["consumers"]
    ]


def _signal_evidence(incident: dict[str, Any]) -> list[Evidence]:
    evidence: list[Evidence] = []
    for signal in incident["signals"]:
        evidence.append(
            Evidence(
                evidence_id=f"evidence.signal.{incident['id']}.{canonical_hash(signal)[:10]}",
                source_type="signal",
                source_id=f"{incident['id']}:{signal['name']}",
                title=signal["name"],
                excerpt=f"Observed {signal['value']}; expected {signal['threshold']}.",
                source_version="incident-signal-v1",
                observed_at=signal["observed_at"],
                source_snapshot_id=signal["source_snapshot_id"],
                content_hash=canonical_hash(signal),
            )
        )
    return evidence


def _quality_gate(
    contract: dict[str, Any], selected_runbook: dict[str, Any] | None, evidence: list[Evidence], grounded: bool
) -> dict[str, Any]:
    checks = [
        QualityCheck(
            id="contract_resolved",
            label="Contract resolved",
            status="pass",
            detail=f"{contract['id']} {contract['version']} is owned by {contract['owner']}.",
        ),
        QualityCheck(
            id="runbook_alignment",
            label="Runbook alignment",
            status="pass" if grounded else "needs_review",
            detail=(
                f"{selected_runbook['id']} {selected_runbook['version']} matches the contract and observed symptoms."
                if grounded and selected_runbook
                else "No active runbook met the contract plus symptom evidence threshold."
            ),
        ),
        QualityCheck(
            id="observable_signals",
            label="Observable signals",
            status="pass" if any(item.source_type == "signal" for item in evidence) else "needs_review",
            detail=f"{sum(item.source_type == 'signal' for item in evidence)} timestamped signals are attached.",
        ),
        QualityCheck(
            id="provenance_complete",
            label="Provenance receipt",
            status="pass" if all(item.content_hash for item in evidence) else "needs_review",
            detail="Every cited record carries a version or snapshot identifier and a content hash.",
        ),
        QualityCheck(
            id="human_gate",
            label="Human decision gate",
            status="pass",
            detail="Sillage cannot replay data, change a gate, or notify an owner automatically.",
        ),
    ]
    return {
        "status": "ready_for_human_review" if grounded else "needs_operator_context",
        "all_passed": all(check.status == "pass" for check in checks),
        "checks": [asdict(check) for check in checks],
    }


def build_triage_report(incident: dict[str, Any]) -> TriageReport:
    """Produce a deterministic, evidence-bound triage report.

    The scoring method is a transparent route selector, not a probability model.
    It deliberately abstains when the contract and symptom evidence do not agree.
    """

    registry = validate_registry()
    contract = contract_by_id(incident["contract_id"])
    if contract is None:
        raise LookupError(f"No contract found for {incident['contract_id']}")

    ranked_pairs = sorted(
        ((runbook, _rank_runbook(incident, runbook)) for runbook in runbooks()),
        key=lambda item: item[1]["score"],
        reverse=True,
    )
    if not ranked_pairs:
        raise LookupError("No runbooks available for grounded triage")

    candidate, top_ranking = ranked_pairs[0]
    selected_runbook = candidate if top_ranking["eligible"] else None
    grounded = selected_runbook is not None
    decision_code, gate_state, decision = _decision(incident, grounded)

    contract_evidence = Evidence(
        evidence_id=f"evidence.contract.{contract['id']}.{contract['version']}",
        source_type="data_contract",
        source_id=contract["id"],
        title=f"{contract['dataset']} contract {contract['version']}",
        excerpt=(
            f"Tier {contract['tier']}; owner {contract['owner']}; SLA {contract['sla_minutes']} min; "
            f"authority {contract['authority']}."
        ),
        source_version=contract["version"],
        observed_at=contract["updated_at"],
        source_snapshot_id=f"contract-registry:{contract['id']}:{contract['version']}",
        content_hash=canonical_hash(contract),
    )
    evidence = [contract_evidence]
    if selected_runbook:
        evidence.append(
            Evidence(
                evidence_id=f"evidence.runbook.{selected_runbook['id']}.{selected_runbook['version']}",
                source_type="runbook",
                source_id=selected_runbook["id"],
                title=selected_runbook["title"],
                excerpt=selected_runbook["risk"],
                source_version=selected_runbook["version"],
                observed_at=selected_runbook["updated_at"],
                source_snapshot_id=f"runbook-registry:{selected_runbook['id']}:{selected_runbook['version']}",
                content_hash=canonical_hash(selected_runbook),
            )
        )
    evidence.extend(_signal_evidence(incident))

    evidence_hash = canonical_hash([asdict(item) for item in evidence])
    source_snapshot_ids = [item.source_snapshot_id for item in evidence]
    trace_seed = {
        "incident_id": incident["id"],
        "policy": TRIAGE_POLICY_VERSION,
        "evidence_hash": evidence_hash,
        "registry_fingerprint": registry["registry_fingerprint"],
    }
    trace_id = f"triage-{canonical_hash(trace_seed)[:16]}"
    ranking = {
        "method": "contract affinity + symptom overlap + severity context",
        "policy_version": TRIAGE_POLICY_VERSION,
        "minimum_routing_score": MINIMUM_ROUTING_SCORE,
        "selected_runbook": selected_runbook["id"] if selected_runbook else None,
        "selected_score": top_ranking["score"] if grounded else None,
        "margin": (
            round(top_ranking["score"] - ranked_pairs[1][1]["score"], 2)
            if grounded and len(ranked_pairs) > 1
            else None
        ),
        "candidates": [ranking for _, ranking in ranked_pairs],
    }
    quality_gate = _quality_gate(contract, selected_runbook, evidence, grounded)
    impact = _impact(contract, gate_state)
    impact_summary = selected_runbook["risk"] if selected_runbook else "Downstream impact is known, but no runbook is sufficiently grounded yet."
    first_actions = (
        selected_runbook["steps"]
        if selected_runbook
        else [
            "Preserve the current gate and the raw incident evidence.",
            f"Ask {contract['owner']} to confirm the relevant runbook or provide the missing operational context.",
            "Do not replay, backfill, publish or override a quality control from this recommendation.",
        ]
    )
    escalation = (
        selected_runbook["escalation"]
        if selected_runbook
        else f"Escalate to {contract['owner']} because the evidence threshold was not met."
    )

    return TriageReport(
        incident_id=incident["id"],
        generated_at=datetime.now(timezone.utc).isoformat(),
        decision_code=decision_code,
        decision=decision,
        gate_state=gate_state,
        # The best candidate's routing score, uncapped. It is a sum of visible
        # components (see ranking.candidates), not a probability.
        match_score=top_ranking["score"],
        impact=impact,
        impact_summary=impact_summary,
        hypothesis=_hypothesis(incident, grounded),
        first_actions=first_actions,
        escalation=escalation,
        safety_note=(
            "Sillage proposes a grounded triage plan. It does not change data, trigger a replay, "
            "change a quality gate, or notify an owner automatically."
        ),
        evidence=evidence,
        ranking=ranking,
        quality_gate=quality_gate,
        provenance={
            "trace_id": trace_id,
            "incident_id": incident["id"],
            "incident_opened_at": incident["opened_at"],
            "contract_id": contract["id"],
            "contract_version": contract["version"],
            "contract_owner": contract["owner"],
            "runbook_id": selected_runbook["id"] if selected_runbook else None,
            "runbook_version": selected_runbook["version"] if selected_runbook else None,
            "source_snapshot_id": f"evidence-bundle:{evidence_hash[:16]}",
            "source_snapshot_ids": source_snapshot_ids,
            "evidence_hash": evidence_hash,
            "registry_fingerprint": registry["registry_fingerprint"],
        },
    )
