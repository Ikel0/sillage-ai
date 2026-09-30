from __future__ import annotations

import json
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"


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


def incident_by_id(incident_id: str) -> dict[str, Any] | None:
    return next((item for item in incidents() if item["id"] == incident_id), None)


def contract_by_id(contract_id: str) -> dict[str, Any] | None:
    return next((item for item in contracts() if item["id"] == contract_id), None)
