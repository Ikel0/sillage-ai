# Sillage AI

> Evidence-first decision support for data incidents.

Sillage AI is a compact incident intelligence desk for data teams. It connects an incident to an explicit data contract, a relevant runbook and observed signals, then produces a recommendation that an operator can inspect and challenge.

It is intentionally not an autonomous remediation tool. It never replays data, changes a quality gate, edits a contract or notifies an owner on its own.

## Why this exists

Data incidents are rarely hard because information is absent. They are hard because the right information is spread across contracts, runbooks, operational signals and team context. Sillage brings those elements into one decision trail:

```text
incident + observed signals
          |
          v
contract and runbook retrieval
          |
          v
evidence-bound recommendation
          |
          v
human decision and local audit trail
```

The project demonstrates production-minded habits that matter in a data platform role: clear ownership, versioned operating knowledge, safe abstention, deterministic fallbacks, downstream impact, auditability and regression checks.

## What is working

- FastAPI service with an interactive control room and generated OpenAPI documentation.
- Offline deterministic triage for three realistic data quality incidents.
- Startup validation for the local contract, incident and runbook registry. Missing ownership, version, references or downstream metadata blocks readiness.
- Explicit evidence pack: versioned contract, selected runbook, timestamped signals, source snapshots and stable content hashes.
- Safe abstention when the contract and symptoms do not ground a runbook strongly enough.
- Machine-readable decision code, gate state and consumer-level impact for each recommendation.
- Operator review receipt with accepted, needs-evidence and rejected outcomes. Reviews are recorded but never execute a remediation.
- SQLite append-only audit trail with a simple hash link between local receipts.
- Offline golden-case suite that checks runbook selection, decision alignment, provenance completeness and the no-action safety guard.
- Optional public GitHub Status signal. It is informative only and never blocks local triage.
- Docker, Render Blueprint and GitHub Actions configuration.

## Quick start

Python 3.11 or newer is required.

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
.venv/bin/uvicorn sillage.app:app --app-dir src --reload
```

Open [http://localhost:8000](http://localhost:8000) for the incident desk. The OpenAPI contract is available at [http://localhost:8000/docs](http://localhost:8000/docs).

For a containerized run:

```bash
docker build -t sillage-ai .
docker run --rm -p 10000:10000 -e PORT=10000 sillage-ai
```

## API surface

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Liveness and safety posture |
| `GET` | `/api/incidents` | Incident queue |
| `GET` | `/api/incidents/{id}` | Incident plus governing contract |
| `POST` | `/api/incidents/{id}/analyze` | Evidence-first triage, no corrective action |
| `POST` | `/api/incidents/{id}/reviews` | Record an operator decision, never execute a plan |
| `GET` | `/api/incidents/{id}/reviews` | Read recorded operator-review receipts |
| `GET` | `/api/contracts` | Data contract catalogue |
| `GET` | `/api/audit` | Recent local audit events |
| `GET` | `/api/evaluation` | Offline retrieval regression suite |
| `POST` | `/api/sources/github-status/sync` | Optional public operational signal |

Every API response includes an `X-Request-ID` header so an operator can connect an observation to a request in a future logging stack.

## How a recommendation is built

1. The service validates the local registry, then resolves the versioned contract referenced by the incident.
2. It ranks active runbooks with visible components: contract affinity, symptom overlap and severity context.
3. It abstains if the best route does not meet both the contract and symptom evidence threshold.
4. It presents the decision, gate posture, downstream consumer impact and raw evidence together.
5. It emits a provenance receipt containing version identifiers, source snapshots, a trace id and an evidence hash.
6. An operator accepts, requests more evidence or rejects the triage. That judgement becomes another auditable receipt.

The recommendation is useful because the operator can see exactly what it relies on. The engine does not pretend to know a root cause when the evidence does not support one.

## The AI boundary

The local demo uses a deterministic evidence-bound narrative provider. It requires no API key, so the project works in an offline review or interview setting.

`src/sillage/narrative.py` exposes a small provider interface for a future LLM layer. A real provider must receive only the retrieved evidence pack and return citations that can be validated against it. The application intentionally has no autonomous tool execution path. The recommendation is still generated locally and deterministically, so it stays inspectable when no external model is available.

Read the detailed guardrails in [docs/ai-safety.md](docs/ai-safety.md).

## Project map

```text
data/                  Representative contracts, incidents, runbooks and golden cases
src/sillage/           FastAPI application and decision-support engine
static/                Interactive incident intelligence desk
tests/                 Offline API, audit, retrieval and source tests
docs/                  Product, architecture and operating notes
render.yaml            Render Blueprint
```

## Deployment

The included [render.yaml](render.yaml) deploys the Docker image as a Render web service and checks `/api/health`. The local SQLite database and its hash link are deliberately demo mechanisms, not an immutable production ledger. For a multi-instance production deployment, replace them with a managed audit store and add identity, retention, durable job execution, a governed retrieval index and role-aware permissions.

## Documentation

- [Product brief](docs/product-brief.md)
- [Working paper](docs/working-paper.md)
- [Architecture](docs/architecture.md)
- [Operating model](docs/operating-model.md)
- [AI safety and evaluation](docs/ai-safety.md)

## License

MIT
