# Architecture

## Runtime view

```text
Browser control room
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

`src/sillage/app.py` exposes the incident queue, triage workflow, audit events and service checks. It attaches a request identifier to every response and prevents API responses from being cached by browsers or proxies.

### Decision-support engine

`src/sillage/engine.py` selects a runbook with an explicit, inspectable score:

- 0.64 for a matching data contract
- up to 0.20 for observable symptom overlap
- up to 0.16 based on incident severity

The deliberately simple model makes the demo reviewable. In a production setting, retrieval quality would be measured on a larger benchmark, thresholded by confidence and improved with lineage, ownership and time-window features.

### Narrative provider boundary

`src/sillage/narrative.py` produces local wording from the already retrieved evidence. It includes a `NarrativeProvider` protocol to show where an optional external model could be added later. The provider boundary is downstream of retrieval, not a substitute for it.

### Audit store

`src/sillage/audit.py` stores compact JSON audit events in SQLite. The current implementation uses WAL mode and bounded event retrieval to suit a single-instance demo. A real service would use a managed, immutable audit sink and propagate identity and trace context.

### Public source adapter

`src/sillage/sources.py` fetches GitHub's publicly available status summary. A timeout or network failure returns a structured unavailable state, so the local engine remains usable. This models a practical principle: contextual sources should not become a single point of failure for incident response.

## Data boundaries

The repository ships with representative, non-sensitive fixtures. There are no customer records, credentials, embedded API keys or production identifiers. The public source is fetched only after an explicit action in the UI or API.

## Deployment

The Docker image runs as a non-root user. `render.yaml` includes a health check against `/api/health`. The app's file-backed fixtures are immutable at runtime and the local audit database is excluded from git.
