from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR = ROOT / "runtime"
DATABASE = RUNTIME_DIR / "sillage.db"


def _connection() -> sqlite3.Connection:
    RUNTIME_DIR.mkdir(exist_ok=True)
    connection = sqlite3.connect(DATABASE, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("pragma journal_mode = WAL")
    connection.execute("pragma busy_timeout = 5000")
    connection.execute(
        """
        create table if not exists audit_events (
            id integer primary key autoincrement,
            occurred_at text not null,
            event_type text not null,
            incident_id text,
            payload text not null
        )
        """
    )
    return connection


def record(event_type: str, payload: dict[str, Any], incident_id: str | None = None) -> int:
    """Persist a compact, append-only audit event and return its local id."""
    connection = _connection()
    try:
        with connection:
            cursor = connection.execute(
                "insert into audit_events (occurred_at, event_type, incident_id, payload) values (?, ?, ?, ?)",
                (
                    datetime.now(timezone.utc).isoformat(),
                    event_type,
                    incident_id,
                    json.dumps(payload, sort_keys=True, separators=(",", ":")),
                ),
            )
        return int(cursor.lastrowid)
    finally:
        connection.close()


def recent_events(limit: int = 12) -> list[dict[str, Any]]:
    connection = _connection()
    try:
        rows = connection.execute(
            "select id, occurred_at, event_type, incident_id, payload from audit_events order by id desc limit ?", (limit,)
        ).fetchall()
    finally:
        connection.close()
    return [
        {
            "id": row["id"],
            "occurred_at": row["occurred_at"],
            "event_type": row["event_type"],
            "incident_id": row["incident_id"],
            "payload": json.loads(row["payload"]),
        }
        for row in rows
    ]
