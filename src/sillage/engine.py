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
            "Les signaux disponibles ne correspondent pas assez à un runbook actif. "
            "Garder le contrôle actuel en place et demander le contexte manquant au responsable du contrat."
        )

    text = _incident_text(incident).lower()
    if "doublon" in text or "rejeu" in text:
        return "Un rejeu a atteint l'agrégation sans frontière d'idempotence confirmée."
    if "schéma" in text or "payload" in text or "occurred_at" in text:
        return "Une release du producteur a introduit un payload incompatible avec le contrat d'événements publié."
    if "null" in text or "clé" in text:
        return "L'extrait amont est incomplet : une clé métier obligatoire manque à la source."
    return "Les éléments justifient une investigation sous contrôle, sans désigner une cause unique."


def _decision(incident: dict[str, Any], grounded: bool) -> tuple[str, str, str]:
    if not grounded:
        return (
            "INSUFFICIENT_EVIDENCE",
            "review_required",
            "Garder le contrôle qualité actuel et obtenir le contexte du responsable du contrat avant tout rejeu ou publication.",
        )
    if incident["severity"] == "SEV-1":
        return (
            "CONTAIN_AND_REVIEW",
            "blocked",
            "Contenir la publication et investiguer avec l'équipe responsable.",
        )
    return (
        "HOLD_FOR_REVIEW",
        "review_required",
        "Garder le contrôle qualité actif et investiguer avant tout rejeu ou publication.",
    )


def _impact(contract: dict[str, Any], gate_state: str) -> list[Impact]:
    if gate_state == "blocked":
        action = "Ne publier aucun actif concerné avant que le responsable du contrat confirme une correction sûre."
    else:
        action = "Garder ce consommateur en revue jusqu'aux contrôles du contrat et à la décision du responsable."
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
                excerpt=f"Observé : {signal['value']} ; attendu : {signal['threshold']}.",
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
            label="Contrat résolu",
            status="pass",
            detail=f"{contract['id']} {contract['version']}, responsable : {contract['owner']}.",
        ),
        QualityCheck(
            id="runbook_alignment",
            label="Runbook aligné",
            status="pass" if grounded else "needs_review",
            detail=(
                f"{selected_runbook['id']} {selected_runbook['version']} porte sur ce contrat et partage des symptômes observés."
                if grounded and selected_runbook
                else "Aucun runbook actif n'atteint le seuil (même contrat, symptôme commun, score ≥ 0,80)."
            ),
        ),
        QualityCheck(
            id="observable_signals",
            label="Signaux observés",
            status="pass" if any(item.source_type == "signal" for item in evidence) else "needs_review",
            detail=f"{sum(item.source_type == 'signal' for item in evidence)} signaux horodatés sont joints.",
        ),
        QualityCheck(
            id="provenance_complete",
            label="Reçu de provenance",
            status="pass" if all(item.content_hash for item in evidence) else "needs_review",
            detail="Chaque élément cité porte un identifiant de version ou de snapshot et une empreinte de contenu.",
        ),
        QualityCheck(
            id="human_gate",
            label="Décision humaine",
            status="pass",
            detail="Sillage ne peut ni rejouer des données, ni modifier un contrôle, ni notifier un responsable.",
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
        title=f"Contrat {contract['dataset']} {contract['version']}",
        excerpt=(
            f"Niveau {contract['tier']} ; responsable {contract['owner']} ; SLA {contract['sla_minutes']} min ; "
            f"source {contract['authority']}."
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
        "method": "même contrat + part des symptômes retrouvés + poids de sévérité",
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
    impact_summary = selected_runbook["risk"] if selected_runbook else "L'impact aval est connu, mais aucun runbook n'est encore assez étayé."
    first_actions = (
        selected_runbook["steps"]
        if selected_runbook
        else [
            "Conserver le contrôle actuel et les éléments bruts de l'incident.",
            f"Demander à {contract['owner']} de confirmer le runbook pertinent ou d'apporter le contexte manquant.",
            "Ne pas rejouer, recharger, publier ni contourner un contrôle qualité sur la base de cette proposition.",
        ]
    )
    escalation = (
        selected_runbook["escalation"]
        if selected_runbook
        else f"Escalader vers {contract['owner']} : le seuil de correspondance n'est pas atteint."
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
            "Sillage propose un triage. Il ne modifie aucune donnée, ne déclenche aucun rejeu, "
            "ne change aucun contrôle qualité et ne notifie personne."
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
