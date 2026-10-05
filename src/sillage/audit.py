from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR = ROOT / "runtime"
DATABASE = RUNTIME_DIR / "sillage.db"

# The public demo is one shared instance. Each browser tab gets its own journal
# (keyed by a hash of its session token) and every receipt expires after an hour,
# so no visitor sees another's decisions and nothing outlives the demo session.
SESSION_TTL = timedelta(hours=1)
LOCAL_SESSION = "local"


def session_key(token: str) -> str:
    return hashlib.sha256(f"sillage-session:{token}".encode("utf-8")).hexdigest()[:32]


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _event_hash(
    occurred_at: str,
    event_type: str,
    incident_id: str | None,
    payload: dict[str, Any],
    previous_hash: str | None,
) -> str:
    material = _canonical_json(
        {
            "occurred_at": occurred_at,
            "event_type": event_type,
            "incident_id": incident_id,
            "payload": payload,
            "previous_hash": previous_hash,
        }
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _ensure_columns(connection: sqlite3.Connection) -> None:
    existing = {row["name"] for row in connection.execute("pragma table_info(audit_events)").fetchall()}
    for name, definition in {
        "previous_hash": "text",
        "event_hash": "text",
        "session_key": "text",
    }.items():
        if name not in existing:
            connection.execute(f"alter table audit_events add column {name} {definition}")


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
            payload text not null,
            previous_hash text,
            event_hash text,
            session_key text
        )
        """
    )
    _ensure_columns(connection)
    connection.execute("create index if not exists audit_events_session on audit_events (session_key, id)")
    return connection


def purge_expired(connection: sqlite3.Connection | None = None) -> int:
    """Delete receipts older than SESSION_TTL, including rows from older schemas."""
    own = connection is None
    connection = connection or _connection()
    try:
        cutoff = (datetime.now(timezone.utc) - SESSION_TTL).isoformat()
        with connection:
            cursor = connection.execute(
                "delete from audit_events where occurred_at < ? or session_key is null", (cutoff,)
            )
        return cursor.rowcount
    finally:
        if own:
            connection.close()


def record(
    event_type: str, payload: dict[str, Any], incident_id: str | None = None, session: str = LOCAL_SESSION
) -> int:
    """Persist a compact local receipt with a simple append-only integrity link.

    SQLite is demo storage only. The hash link gives the prototype a visible
    tamper-evidence concept; a production deployment should use a durable,
    access-controlled audit store with retention and operator identity.
    """

    occurred_at = datetime.now(timezone.utc).isoformat()
    key = session_key(session)
    connection = _connection()
    try:
        purge_expired(connection)
        with connection:
            previous = connection.execute(
                "select event_hash from audit_events where session_key = ? and event_hash is not null "
                "order by id desc limit 1",
                (key,),
            ).fetchone()
            previous_hash = str(previous["event_hash"]) if previous else None
            current_hash = _event_hash(occurred_at, event_type, incident_id, payload, previous_hash)
            cursor = connection.execute(
                """
                insert into audit_events
                    (occurred_at, event_type, incident_id, payload, previous_hash, event_hash, session_key)
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    occurred_at,
                    event_type,
                    incident_id,
                    _canonical_json(payload),
                    previous_hash,
                    current_hash,
                    key,
                ),
            )
        return int(cursor.lastrowid)
    finally:
        connection.close()


def recent_events(
    limit: int = 12,
    incident_id: str | None = None,
    event_type: str | None = None,
    session: str = LOCAL_SESSION,
) -> list[dict[str, Any]]:
    connection = _connection()
    try:
        purge_expired(connection)
        clauses: list[str] = ["a.session_key = ?"]
        parameters: list[object] = [session_key(session)]
        if incident_id:
            clauses.append("a.incident_id = ?")
            parameters.append(incident_id)
        if event_type:
            clauses.append("a.event_type = ?")
            parameters.append(event_type)
        where = f"where {' and '.join(clauses)}" if clauses else ""
        parameters.append(limit)
        rows = connection.execute(
            f"""
            select a.id, a.occurred_at, a.event_type, a.incident_id, a.payload, a.previous_hash, a.event_hash,
                   (select count(*) from audit_events b where b.session_key = a.session_key and b.id <= a.id) as receipt
            from audit_events a {where} order by a.id desc limit ?
            """,
            parameters,
        ).fetchall()
    finally:
        connection.close()
    return [_row_to_event(row) for row in rows]


def event_by_id(event_id: int, session: str = LOCAL_SESSION) -> dict[str, Any] | None:
    connection = _connection()
    try:
        row = connection.execute(
            """
            select a.id, a.occurred_at, a.event_type, a.incident_id, a.payload, a.previous_hash, a.event_hash,
                   (select count(*) from audit_events b where b.session_key = a.session_key and b.id <= a.id) as receipt
            from audit_events a where a.id = ? and a.session_key = ?
            """,
            (event_id, session_key(session)),
        ).fetchone()
    finally:
        connection.close()
    return _row_to_event(row) if row else None


def _row_to_event(row: sqlite3.Row) -> dict[str, Any]:
    return {
        # The global row id stays internal; visitors only see their session's receipt number.
        "receipt": row["receipt"],
        "occurred_at": row["occurred_at"],
        "event_type": row["event_type"],
        "incident_id": row["incident_id"],
        "payload": json.loads(row["payload"]),
        "previous_hash": row["previous_hash"],
        "event_hash": row["event_hash"],
    }
