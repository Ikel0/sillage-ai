# Working paper: Evidence-first data incident intelligence

**Project:** Sillage AI

**Author:** Ikel Ouedraogo

**Status:** Applied research prototype
**Scope:** Reliable operator decision support for data quality incidents

## Abstract

Data platforms increasingly combine contracts, orchestration, quality checks, lineage and a growing body of operational knowledge. During an incident, this information is often distributed across tools and owned by different teams. Sillage investigates a narrow but useful question: can a data incident assistant shorten the path to a defensible first decision without hiding the evidence or taking action on behalf of an operator?

The prototype provides an evidence-first workflow. It takes a known incident, retrieves the governing data contract and ranks a runbook using explicit signals. It returns a recommendation, a hypothesis, first actions, escalation guidance and a complete list of evidence identifiers. A local audit record captures every recommendation. The product deliberately avoids automatic replay, data modification and notifications.

## Research question

How can an incident assistant improve the speed and consistency of initial data-incident triage while preserving reviewability, ownership and human control?

## Design thesis

The core design choice is to make retrieval visible before making reasoning persuasive. A useful recommendation must answer four questions:

1. Which contract governs the affected dataset?
2. Which observed signals support the interpretation?
3. Which runbook was selected, and why?
4. What action remains explicitly owned by a human operator?

This framing is more useful for an on-call setting than an ungrounded conversational answer. The operator can reject a recommendation, inspect its inputs and continue with the team's established incident process.

## Prototype method

The current implementation uses three representative incident families:

| Incident family | Contract concern | First safety posture |
| --- | --- | --- |
| Duplicate order events after replay | Idempotency and revenue reconciliation | Contain publication of the derived mart |
| Customer event schema drift | Compatibility and event completeness | Keep the quality gate active |
| Incomplete inventory keys | Source completeness and trusted snapshots | Stop unsafe snapshot replacement |

For each incident, Sillage:

1. Resolves the referenced contract.
2. Scores available runbooks using contract match, symptom overlap and severity.
3. Produces an evidence pack containing contract, runbook and raw signals.
4. Produces a short deterministic narrative from that evidence pack.
5. Writes a compact audit event with evidence identifiers and `automated_action: false`.

The score is intentionally simple and inspectable. It is not presented as a machine-learning model or a universal root-cause detector.

## Evaluation protocol

The prototype includes a small golden suite with one expected retrieval outcome for each incident family. The regression test checks that:

- the expected runbook is selected;
- the expected safety posture appears in the recommended decision;
- the result is generated without an external model or API key.

This benchmark is limited by design. It protects against accidental regressions in the scenarios represented by the product but does not prove general performance. A production evaluation would need a versioned incident corpus, domain-owner labels, retrieval recall metrics, abstention tests, citation-validity checks and human-on-call feedback.

## System boundaries

The current product is a single-instance prototype:

- JSON fixtures represent contracts, incidents and runbooks.
- SQLite provides a local append-only audit trail.
- An optional GitHub Status adapter demonstrates how public operational context can be integrated without becoming a dependency.
- No customer data, API key or production credential is bundled.

The Docker image runs as a non-root user, exposes a health endpoint and can be deployed with the included Render Blueprint.

## LLM composition point

Sillage has a narrow provider interface for future language-model use. The application currently uses only a credential-free deterministic provider. A future model provider should receive a bounded evidence pack, return citations and be rejected if those citations are not part of the retrieval result. It should not be given access to an action tool by default.

This boundary matters because prose quality is not a substitute for operational truth. A better sentence is only valuable if the operator can trace it to approved evidence.

## Production path

Moving from prototype to production would require:

1. Alert-webhook ingestion with schema validation and idempotent event handling.
2. A governed contract and runbook registry with owner metadata and version history.
3. A durable audit store, identity propagation and retention controls.
4. Retrieval evaluation on real, privacy-reviewed incident records.
5. Role-aware access controls before indexing internal lineage or operational documents.
6. Feature flags and approval gates for any external model provider.
7. Explicit human confirmation for high-impact operations such as replays or gate changes.

## Conclusion

Sillage does not try to automate incident command. Its value is the disciplined first step: connect a data incident to its contract, runbook and signals, explain what is known, record the recommendation and keep the next action with the responsible person.

For the project architecture, see [architecture.md](architecture.md). For product goals and non-goals, see [product-brief.md](product-brief.md). For guardrails and evaluation details, see [ai-safety.md](ai-safety.md).
