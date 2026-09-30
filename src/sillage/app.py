from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .audit import recent_events, record
from .engine import build_triage_report
from .evaluation import evaluate_grounded_triage
from .narrative import compose_grounded_narrative
from .repository import contract_by_id, contracts, incident_by_id, incidents
from .sources import github_status_snapshot


ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = ROOT / "static"

app = FastAPI(
    title="Sillage AI",
    summary="Evidence-first decision support for data incidents.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url=None,
)
app.add_middleware(GZipMiddleware, minimum_size=500)
app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")


@app.middleware("http")
async def add_request_id(request: Request, call_next) -> Response:
    request_id = request.headers.get("X-Request-ID", str(uuid4()))
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
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} was not found")
    return incident


@app.get("/", include_in_schema=False)
async def landing_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health", tags=["Service"])
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "mode": "evidence-first-decision-support",
        "autonomous_actions": False,
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
        raise HTTPException(status_code=500, detail=f"Contract {contract_id} is missing")
    return {"incident": incident, "contract": contract}


@app.post("/api/incidents/{incident_id}/analyze", tags=["Triage"])
async def analyze_incident(incident_id: str) -> dict[str, object]:
    """Build a grounded recommendation. This endpoint never performs a corrective action."""
    incident = _get_incident_or_404(incident_id)
    report = build_triage_report(incident)
    narrative = compose_grounded_narrative(report)
    report_payload = report.as_dict()
    audit_event_id = record(
        "triage_generated",
        {
            "mode": "evidence-first-decision-support",
            "confidence": report.confidence,
            "provider": narrative.provider,
            "evidence_ids": narrative.citations,
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
        },
    }


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
async def sync_github_status() -> dict[str, object]:
    """Fetch a small public operational signal without making it a dependency of triage."""
    snapshot = await asyncio.to_thread(github_status_snapshot)
    audit_event_id = record(
        "public_source_synced",
        {
            "source": snapshot["source"],
            "ok": snapshot["ok"],
            "indicator": snapshot["indicator"],
        },
    )
    return {"snapshot": snapshot, "audit_event_id": audit_event_id}
