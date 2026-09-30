# Operating model

## Operator responsibilities

Sillage supports an operator. The operator remains responsible for deciding whether to pause publication, request a replay, contact an owner or change a contract. The service is intentionally incapable of taking those actions.

## Incident response loop

1. Verify the alert and affected dataset.
2. Read the governing contract and identify downstream consumers.
3. Generate the evidence-first triage report.
4. Review the selected runbook and its confidence against the raw signals.
5. Execute approved actions in the team's normal incident tooling.
6. Add the resulting decision to the organization’s incident record.

## Service signals

| Signal | Meaning | Operator response |
| --- | --- | --- |
| `/api/health` is healthy | The local service and fixture catalogue are available. | Continue normal use. |
| Public source sync is unavailable | An optional contextual source could not be fetched. | Continue triage with local evidence. |
| Evaluation score is below 1.0 | A known retrieval case has regressed. | Stop trusting recommendations until the fixture or retrieval logic is reviewed. |
| Audit write fails | Decision traceability is compromised. | Record the decision in the primary incident system and investigate storage. |

## Failure posture

The intended safe failure is simple: return fewer contextual signals rather than fabricate a conclusion. An unavailable public API has no effect on a local triage. A missing contract or runbook produces an explicit failure rather than a fallback recommendation.
