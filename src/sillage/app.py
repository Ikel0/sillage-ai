from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from .audit import event_by_id, recent_events, record
from .engine import build_triage_report, simulate_routing
from .evaluation import evaluate_grounded_triage
from .narrative import compose_grounded_narrative
from .repository import (
    RegistryValidationError,
    contract_by_id,
    contracts,
    incident_by_id,
    incidents,
    validate_registry,
)
from .sources import github_status_snapshot


ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = ROOT / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Refuse to start if the local decision registry is incomplete."""
    validate_registry()
    yield


app = FastAPI(
    title="Sillage",
    summary="Triage d'incidents data fondé sur des preuves, sans action automatique.",
    version="0.3.0",
    docs_url="/docs",
    redoc_url=None,
    lifespan=lifespan,
)
app.add_middleware(GZipMiddleware, minimum_size=500)
app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")


class ReviewInput(BaseModel):
    outcome: Literal["accepted", "needs_evidence", "rejected"]
    note: str = Field(default="", max_length=420)
    trace_id: str | None = Field(default=None, max_length=96)


class SignalEdit(BaseModel):
    index: int = Field(ge=0, lt=32)
    value: str = Field(max_length=200)
    included: bool = True


class SimulationInput(BaseModel):
    severity: Literal["SEV-1", "SEV-2", "SEV-3"] | None = None
    contract_id: str | None = Field(default=None, max_length=96)
    signals: list[SignalEdit] = Field(default_factory=list, max_length=32)
    excluded_terms: list[Annotated[str, Field(max_length=40)]] = Field(default_factory=list, max_length=32)


# The public demo runs as one shared instance. A simulation is stateless (the
# visitor's edits travel with each request and nothing is stored), so visitors
# never see each other's scenarios; the limits below only bound the cost.
SIMULATION_MAX_BODY_BYTES = 16_384
SIMULATION_RATE_LIMIT = 90
SIMULATION_RATE_WINDOW_SECONDS = 60.0
_simulation_calls: dict[str, deque[float]] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        # Render appends the address it saw last; earlier entries are client-supplied.
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def _check_simulation_rate(request: Request) -> None:
    now = time.monotonic()
    if len(_simulation_calls) > 5_000:
        _simulation_calls.clear()
    calls = _simulation_calls[_client_ip(request)]
    while calls and now - calls[0] > SIMULATION_RATE_WINDOW_SECONDS:
        calls.popleft()
    if len(calls) >= SIMULATION_RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Trop de recalculs en une minute ; réessayez dans un instant.")
    calls.append(now)


@app.middleware("http")
async def add_request_id(request: Request, call_next) -> Response:
    request_id = request.headers.get("X-Request-ID", str(uuid4()))
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api/") else "public, max-age=300"
    return response


def _incident_summary(incident: dict[str, object]) -> dict[str, object]:
    return {
        "id": incident["id"],
        "title": incident["title"],
        "severity": incident["severity"],
        "status": incident["status"],
        "opened_at": incident["opened_at"],
        "contract_id": incident["contract_id"],
    }


def _get_incident_or_404(incident_id: str) -> dict[str, object]:
    incident = incident_by_id(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} introuvable")
    return incident


@app.get("/", include_in_schema=False)
async def landing_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health", tags=["Service"])
async def health() -> dict[str, object]:
    try:
        registry = validate_registry()
    except RegistryValidationError as error:
        raise HTTPException(status_code=503, detail=f"Registre incomplet : {error}") from error
    return {
        "status": "ok",
        "readiness": "ready",
        "version": app.version,
        "mode": "evidence-first-decision-support",
        "autonomous_actions": False,
        "registry": registry,
        "audit_store": "local SQLite demo store",
        "data_assets": {
            "incidents": len(incidents()),
            "contracts": len(contracts()),
        },
    }


@app.get("/api/incidents", tags=["Incidents"])
async def list_incidents() -> dict[str, object]:
    severity_order = {"SEV-1": 1, "SEV-2": 2, "SEV-3": 3}
    items = sorted(
        (_incident_summary(incident) for incident in incidents()),
        key=lambda incident: (severity_order.get(str(incident["severity"]), 9), str(incident["opened_at"])),
    )
    return {"items": items, "total": len(items)}


@app.get("/api/incidents/{incident_id}", tags=["Incidents"])
async def get_incident(incident_id: str) -> dict[str, object]:
    incident = _get_incident_or_404(incident_id)
    contract_id = str(incident["contract_id"])
    contract = contract_by_id(contract_id)
    if contract is None:
        raise HTTPException(status_code=500, detail=f"Contrat {contract_id} manquant")
    return {"incident": incident, "contract": contract}


@app.post("/api/incidents/{incident_id}/analyze", tags=["Triage"])
async def analyze_incident(incident_id: str, request: Request) -> dict[str, object]:
    """Build a grounded recommendation. This endpoint never performs a corrective action."""
    incident = _get_incident_or_404(incident_id)
    try:
        report = build_triage_report(incident)
    except RegistryValidationError as error:
        raise HTTPException(status_code=503, detail=f"Registre de triage incomplet : {error}") from error
    narrative = compose_grounded_narrative(report)
    report_payload = report.as_dict()
    audit_event_id = record(
        "triage_generated",
        {
            "mode": "evidence-first-decision-support",
            "request_id": request.state.request_id,
            "trace_id": report.provenance["trace_id"],
            "match_score": report.match_score,
            "decision_code": report.decision_code,
            "gate_state": report.gate_state,
            "provider": narrative.provider,
            "evidence_ids": narrative.citations,
            "evidence_hash": report.provenance["evidence_hash"],
            "contract": {
                "id": report.provenance["contract_id"],
                "version": report.provenance["contract_version"],
                "owner": report.provenance["contract_owner"],
            },
            "runbook": {
                "id": report.provenance["runbook_id"],
                "version": report.provenance["runbook_version"],
            },
            "impact_consumers": [item.consumer for item in report.impact],
            "automated_action": False,
        },
        incident_id=incident_id,
    )
    return {
        "report": report_payload,
        "narrative": {
            "provider": narrative.provider,
            "text": narrative.text,
            "citations": narrative.citations,
        },
        "meta": {
            "mode": "evidence-first-decision-support",
            "automated_action": False,
            "audit_event_id": audit_event_id,
            "trace_id": report.provenance["trace_id"],
        },
    }


@app.post("/api/incidents/{incident_id}/simulate", tags=["Triage"])
async def simulate_incident(incident_id: str, request: Request) -> dict[str, object]:
    """Recompute the routing score on an edited copy of the incident.

    Nothing is written: no audit event, no change to the registry. A simulation
    cannot be reviewed; only a triage produced by /analyze can.
    """
    _check_simulation_rate(request)
    body = await request.body()
    if len(body) > SIMULATION_MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Scénario trop volumineux")
    try:
        edits = SimulationInput.model_validate_json(body or b"{}")
    except ValidationError as error:
        raise HTTPException(status_code=422, detail="Scénario invalide") from error
    incident = _get_incident_or_404(incident_id)
    edited = {**incident, "signals": [dict(signal) for signal in incident["signals"]]}
    if edits.severity:
        edited["severity"] = edits.severity
    if edits.contract_id:
        if contract_by_id(edits.contract_id) is None:
            raise HTTPException(status_code=422, detail=f"Contrat {edits.contract_id} inconnu")
        edited["contract_id"] = edits.contract_id
    excluded_signals: set[int] = set()
    for edit in edits.signals:
        if edit.index >= len(edited["signals"]):
            raise HTTPException(status_code=422, detail=f"Signal n° {edit.index} absent de l'incident")
        edited["signals"][edit.index]["value"] = edit.value
        if not edit.included:
            excluded_signals.add(edit.index)
    edited["signals"] = [signal for index, signal in enumerate(edited["signals"]) if index not in excluded_signals]
    simulation = simulate_routing(edited, set(edits.excluded_terms))
    return {"simulation": simulation, "meta": {"recorded": False, "automated_action": False}}


@app.post("/api/incidents/{incident_id}/reviews", tags=["Review"])
async def record_operator_review(
    incident_id: str, review: ReviewInput, request: Request
) -> dict[str, object]:
    """Record an operator's judgement. It does not execute the proposed plan."""
    _get_incident_or_404(incident_id)
    event_id = record(
        "operator_review_recorded",
        {
            "request_id": request.state.request_id,
            "outcome": review.outcome,
            "note": review.note.strip(),
            "trace_id": review.trace_id,
            "automated_action": False,
        },
        incident_id=incident_id,
    )
    receipt = event_by_id(event_id)
    if receipt is None:
        raise HTTPException(status_code=500, detail="Le reçu de revue n'a pas pu être relu")
    return {
        "review": {
            "review_id": receipt["id"],
            "incident_id": incident_id,
            "outcome": review.outcome,
            "note": review.note.strip(),
            "trace_id": review.trace_id,
            "recorded_at": receipt["occurred_at"],
            "audit_hash": receipt["event_hash"],
        },
        "meta": {
            "automated_action": False,
            "request_id": request.state.request_id,
        },
    }


@app.get("/api/incidents/{incident_id}/reviews", tags=["Review"])
async def list_operator_reviews(incident_id: str, limit: int = 12) -> dict[str, object]:
    _get_incident_or_404(incident_id)
    bounded_limit = max(1, min(limit, 100))
    items = recent_events(bounded_limit, incident_id=incident_id, event_type="operator_review_recorded")
    return {"items": items, "total": len(items)}


@app.get("/api/contracts", tags=["Contracts"])
async def list_contracts() -> dict[str, object]:
    return {"items": contracts(), "total": len(contracts())}


@app.get("/api/audit", tags=["Audit"])
async def audit_log(limit: int = 12) -> dict[str, object]:
    bounded_limit = max(1, min(limit, 100))
    items = recent_events(bounded_limit)
    return {"items": items, "total": len(items)}


@app.get("/api/evaluation", tags=["Quality"])
async def evaluation_suite() -> dict[str, object]:
    return evaluate_grounded_triage()


@app.post("/api/sources/github-status/sync", tags=["Sources"])
async def sync_github_status(request: Request) -> dict[str, object]:
    """Fetch a small public operational signal without making it a dependency of triage."""
    snapshot = await asyncio.to_thread(github_status_snapshot)
    audit_event_id = record(
        "public_source_synced",
        {
            "source": snapshot["source"],
            "request_id": request.state.request_id,
            "ok": snapshot["ok"],
            "indicator": snapshot["indicator"],
        },
    )
    return {"snapshot": snapshot, "audit_event_id": audit_event_id}
