from __future__ import annotations

import json
from hashlib import sha256
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"


class RegistryValidationError(ValueError):
    """Raised when the local contract and runbook registry is not safe to use."""


def canonical_hash(value: object) -> str:
    """Create a stable content hash for a provenance receipt.

    The project intentionally hashes the exact local fixture used for a decision.
    This is not a substitute for a signed production registry, but it makes the
    provenance chain inspectable and regression-testable in this prototype.
    """

    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return sha256(encoded.encode("utf-8")).hexdigest()


@lru_cache(maxsize=3)
def _load_collection(name: str) -> tuple[dict[str, Any], ...]:
    with (DATA_DIR / name).open(encoding="utf-8") as source:
        payload = json.load(source)

    if not isinstance(payload, list):
        raise ValueError(f"Expected a list in {name}")
    return tuple(payload)


def load_collection(name: str) -> list[dict[str, Any]]:
    """Return an isolated copy so callers cannot mutate the cached fixtures."""
    return deepcopy(list(_load_collection(name)))


def contracts() -> list[dict[str, Any]]:
    return load_collection("contracts.json")


def incidents() -> list[dict[str, Any]]:
    return load_collection("incidents.json")


def runbooks() -> list[dict[str, Any]]:
    return load_collection("runbooks.json")


def _require_fields(record: dict[str, Any], fields: set[str], label: str) -> None:
    missing = sorted(field for field in fields if record.get(field) in (None, "", []))
    if missing:
        raise RegistryValidationError(f"{label} is missing required fields: {', '.join(missing)}")


def _require_unique_ids(records: list[dict[str, Any]], label: str) -> None:
    ids = [str(record.get("id", "")) for record in records]
    duplicate_ids = sorted({record_id for record_id in ids if ids.count(record_id) > 1})
    if duplicate_ids:
        raise RegistryValidationError(f"{label} contains duplicate ids: {', '.join(duplicate_ids)}")


def validate_registry() -> dict[str, Any]:
    """Validate the prototype registry before it is used for a recommendation.

    A triage assistant should fail closed when it cannot establish ownership,
    version, contract references or downstream impact. The function has no side
    effects, which makes it useful both at application startup and in tests.
    """

    contract_records = contracts()
    incident_records = incidents()
    runbook_records = runbooks()

    _require_unique_ids(contract_records, "contracts")
    _require_unique_ids(incident_records, "incidents")
    _require_unique_ids(runbook_records, "runbooks")

    required_contract_fields = {
        "id",
        "version",
        "dataset",
        "domain",
        "owner",
        "tier",
        "sla_minutes",
        "updated_at",
        "authority",
        "controls",
        "consumers",
    }
    for contract in contract_records:
        _require_fields(contract, required_contract_fields, f"contract {contract.get('id', '<unknown>')}")
        if not isinstance(contract["consumers"], list):
            raise RegistryValidationError(f"contract {contract['id']} consumers must be a list")
        for consumer in contract["consumers"]:
            if not isinstance(consumer, dict):
                raise RegistryValidationError(f"contract {contract['id']} has a consumer without metadata")
            _require_fields(
                consumer,
                {"id", "tier", "reason"},
                f"consumer for contract {contract['id']}",
            )

    contract_ids = {contract["id"] for contract in contract_records}
    required_runbook_fields = {
        "id",
        "version",
        "title",
        "contract_id",
        "owner",
        "updated_at",
        "status",
        "symptoms",
        "steps",
        "risk",
    }
    for runbook in runbook_records:
        _require_fields(runbook, required_runbook_fields, f"runbook {runbook.get('id', '<unknown>')}")
        if runbook["contract_id"] not in contract_ids:
            raise RegistryValidationError(
                f"runbook {runbook['id']} references unknown contract {runbook['contract_id']}"
            )
        if runbook["status"] != "active":
            raise RegistryValidationError(f"runbook {runbook['id']} is not active")

    runbook_contract_ids = {runbook["contract_id"] for runbook in runbook_records}
    missing_runbooks = sorted(contract_ids - runbook_contract_ids)
    if missing_runbooks:
        raise RegistryValidationError(f"contracts without an active runbook: {', '.join(missing_runbooks)}")

    required_incident_fields = {
        "id",
        "title",
        "contract_id",
        "severity",
        "status",
        "opened_at",
        "summary",
        "signals",
    }
    for incident in incident_records:
        _require_fields(incident, required_incident_fields, f"incident {incident.get('id', '<unknown>')}")
        if incident["contract_id"] not in contract_ids:
            raise RegistryValidationError(
                f"incident {incident['id']} references unknown contract {incident['contract_id']}"
            )
        if incident["severity"] not in {"SEV-1", "SEV-2", "SEV-3"}:
            raise RegistryValidationError(f"incident {incident['id']} has an unsupported severity")
        if not isinstance(incident["signals"], list):
            raise RegistryValidationError(f"incident {incident['id']} signals must be a list")
        for signal in incident["signals"]:
            if not isinstance(signal, dict):
                raise RegistryValidationError(f"incident {incident['id']} has a malformed signal")
            _require_fields(
                signal,
                {"kind", "name", "value", "threshold", "observed_at", "source_snapshot_id"},
                f"signal for incident {incident['id']}",
            )

    registry_fingerprint = canonical_hash(
        {
            "contracts": contract_records,
            "incidents": incident_records,
            "runbooks": runbook_records,
        }
    )
    return {
        "status": "ready",
        "contracts": len(contract_records),
        "incidents": len(incident_records),
        "runbooks": len(runbook_records),
        "registry_fingerprint": registry_fingerprint,
    }


def incident_by_id(incident_id: str) -> dict[str, Any] | None:
    return next((item for item in incidents() if item["id"] == incident_id), None)


def contract_by_id(contract_id: str) -> dict[str, Any] | None:
    return next((item for item in contracts() if item["id"] == contract_id), None)
