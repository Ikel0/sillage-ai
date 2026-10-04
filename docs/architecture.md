# Architecture

## Runtime view

```text
Browser triage desk
        |
        v
FastAPI API
  |       |       |
  |       |       +--> optional GitHub public status adapter
  |       |
  |       +----------> deterministic grounded triage engine
  |
  +------------------> local JSON knowledge fixtures
  |
  +------------------> SQLite append-only audit trail
```

## Components

### API layer

`src/sillage/app.py` exposes the incident queue, triage workflow, operator-review receipts, audit events and service checks. It validates the local registry at startup, attaches a request identifier to every response and prevents API responses from being cached by browsers or proxies.

### Decision-support engine

`src/sillage/engine.py` selects a runbook with an explicit, inspectable score:

- 0.64 for a matching data contract
- up to 0.20 for observable symptom overlap
- up to 0.16 based on incident severity

The engine requires both a matching contract and at least one matching symptom before a route can be selected. A score below the minimum routing threshold, or a missing symptom match, produces an explicit abstention with `INSUFFICIENT_EVIDENCE` rather than a plausible-looking runbook. The deliberately simple model makes the demo reviewable. In a production setting, retrieval quality would be measured on a larger benchmark, thresholded with held-out incident data and improved with lineage, ownership, recency and time-window features.

Each selected report carries a provenance receipt: contract and runbook versions, timestamped source snapshots, content hashes, a deterministic evidence bundle hash and a trace id. The score is only a transparent route priority; it is not a calibrated probability of root cause. The report exposes the best candidate's score as `match_score`, uncapped, and the interface shows it next to its three components.

### Narrative provider boundary

`src/sillage/narrative.py` produces local wording from the already retrieved evidence. It includes a `NarrativeProvider` protocol to show where an optional external model could be added later. The provider boundary is downstream of retrieval, not a substitute for it.

### Audit store

`src/sillage/audit.py` stores compact JSON audit events in SQLite. The current implementation uses WAL mode, bounded event retrieval and a local hash link between receipts to suit a single-instance demo. A real service would use a managed, immutable audit sink and propagate verified identity, trace context, retention controls and access policy.

### Registry boundary

`src/sillage/repository.py` treats the JSON fixtures as a small governed registry. It rejects missing owners, versions, consumer impact metadata, unknown contract references, inactive runbooks and malformed timestamped signals. That keeps the demo honest: an unavailable or malformed operating source is a readiness failure, not a reason to improvise a recommendation.

### Public source adapter

`src/sillage/sources.py` fetches GitHub's publicly available status summary. A timeout or network failure returns a structured unavailable state, so the local engine remains usable. This models a practical principle: contextual sources should not become a single point of failure for incident response.

## Data boundaries

The repository ships with representative, non-sensitive fixtures. There are no customer records, credentials, embedded API keys or production identifiers. The public source is fetched only after an explicit action in the UI or API.

## Deployment

The Docker image runs as a non-root user. `render.yaml` includes a health check against `/api/health`. The app's file-backed fixtures are immutable at runtime and the local audit database is excluded from git.
