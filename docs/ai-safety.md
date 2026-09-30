# AI safety and evaluation

## Current behavior

Sillage is an evidence-first decision-support product. Its current recommendation engine is deterministic and works without a model provider or API key. The word AI describes the intended assisted-reasoning direction, not an unsupported claim of autonomous diagnosis.

## Grounding rules

1. A report must include its contract, runbook and observed signal evidence.
2. A recommendation can only cite identifiers from its evidence pack.
3. The service does not expose a tool that modifies a dataset, starts a replay, changes a quality gate or sends a message.
4. The audit event records the evidence identifiers, provider name and `automated_action: false`.
5. Missing contracts or missing runbooks fail explicitly instead of producing a generic answer.

## Optional model provider design

An external model can be useful for compressing a long, approved evidence pack into an operator-friendly explanation. It must be optional. A provider should receive a bounded prompt made from retrieved evidence and return both narrative text and source identifiers. Before display, the service should reject citations that are not part of the retrieval result.

The demo keeps this interface in `src/sillage/narrative.py` but intentionally does not ship credentials, a model client or a hidden dependency on an external endpoint.

## Evaluation

`GET /api/evaluation` executes three offline golden cases. Each case verifies two things:

- the selected runbook is the expected runbook for the known incident;
- the recommended decision contains the expected safety posture.

This is a small regression gate, not a claim of broad model evaluation. It is useful because it prevents a retrieval change from silently selecting the wrong operational procedure for the scenarios included in the product.

## Before a production launch

- Build a representative, versioned incident benchmark with domain owners.
- Measure retrieval recall, citation validity, abstention quality and unsafe-action rate.
- Add feature flags, approval gates and structured feedback from on-call teams.
- Apply access controls before indexing any runbooks or lineage that contain sensitive information.
- Route audit events to a durable system with retention and privacy controls.
