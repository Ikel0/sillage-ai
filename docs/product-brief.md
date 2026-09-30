# Product brief

## Problem

When a data quality alert fires, the first minutes matter. Analysts often need to reconcile a fragmented set of facts: which dataset is affected, who owns it, which checks govern it, what downstream teams consume it and which runbook should be used. A generic chat interface adds very little if it cannot show its evidence or preserve the decision path.

## Product position

Sillage is an incident intelligence desk for data platforms. It is designed as decision support for an on-call engineer, analytics engineer or platform owner. It does not claim to replace incident command or automate remediation.

## Core workflow

1. An operator selects an active incident.
2. Sillage shows the incident signals beside the applicable data contract.
3. The operator requests grounded triage.
4. Sillage ranks the most relevant runbook and returns first actions, escalation path, impact statement and evidence identifiers.
5. The service records that triage event in an append-only local audit trail.

## Example value

For a duplicated orders incident, the operator sees that the data contract requires a unique `event_id`, that finance and merchant KPIs are consumers, and that a replay-related runbook is recommended. The resulting action sequence tells the team to stop publication of the derived mart while preserving raw ingestion, verify idempotency and reconcile before reopening the SLA.

The point is not a polished answer. The point is a safer first decision with enough context to be reviewed by another engineer.

## Non-goals for the demo

- Autonomous replays, corrections or notification workflows.
- A claim that a language model has inferred root cause.
- Hidden vector search or opaque confidence scores.
- A production IAM model represented as a static demo feature.

## Roadmap to a production service

| Horizon | Work |
| --- | --- |
| Foundation | Connect alert webhooks, a governed contract registry and a managed audit store. |
| Retrieval | Index approved runbooks and lineage metadata with document-level access controls. |
| Assisted reasoning | Add a citation-validated LLM provider behind feature flags and evaluation gates. |
| Operations | Add SSO, per-domain authorization, alerting, retention policies and incident command integration. |
