"""SQLite record of alerts and the engineer's decision."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path


DECISIONS = ("approve", "edit", "reject")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class IncidentStore:
    def __init__(self, path: str) -> None:
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS incidents (
                    id TEXT PRIMARY KEY,
                    alert_name TEXT NOT NULL,
                    service TEXT NOT NULL,
                    starts_at TEXT NOT NULL,
                    expression TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    command_text TEXT NOT NULL,
                    decision TEXT,
                    approved_text TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS incidents_alert_start
                ON incidents(alert_name, starts_at)
                """
            )

    def create(
        self,
        *,
        alert_name: str,
        service: str,
        starts_at: str,
        expression: str,
        payload: str,
    ) -> tuple[dict, bool]:
        command_text = _note(alert_name, service, starts_at, payload)
        incident_id = uuid.uuid4().hex
        now = utc_now()
        with self._lock, self._connect() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO incidents (
                        id, alert_name, service, starts_at, expression, payload,
                        command_text, decision, approved_text, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?)
                    """,
                    (
                        incident_id,
                        alert_name,
                        service,
                        starts_at,
                        expression,
                        payload,
                        command_text,
                        now,
                    ),
                )
            except sqlite3.IntegrityError:
                row = connection.execute(
                    """
                    SELECT * FROM incidents
                    WHERE alert_name = ? AND starts_at = ?
                    """,
                    (alert_name, starts_at),
                ).fetchone()
                return _row_to_dict(row), False
        created = self.get(incident_id)
        assert created is not None
        return created, True

    def get(self, incident_id: str) -> dict | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM incidents WHERE id = ?",
                (incident_id,),
            ).fetchone()
        if row is None:
            return None
        return _row_to_dict(row)

    def list_incidents(self) -> list[dict]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM incidents ORDER BY starts_at DESC"
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def decide(self, incident_id: str, decision: str, text: str) -> dict | None:
        if decision not in DECISIONS:
            raise ValueError(f"decision must be one of {DECISIONS}")
        current = self.get(incident_id)
        if current is None:
            return None
        if decision == "edit":
            if not text.strip():
                raise ValueError("edit requires text")
            command_text = text.strip()
            approved_text = None
        elif decision == "approve":
            command_text = text.strip() or current["command_text"]
            approved_text = command_text
        else:
            command_text = current["command_text"]
            approved_text = None
        now = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE incidents
                SET command_text = ?, decision = ?, approved_text = ?, updated_at = ?
                WHERE id = ?
                """,
                (command_text, decision, approved_text, now, incident_id),
            )
        return self.get(incident_id)


def _note(alert_name: str, service: str, starts_at: str, payload: str) -> str:
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        parsed = {}
    summary = str((parsed.get("annotations") or {}).get("summary") or "").strip()
    if summary:
        return summary
    return f"{alert_name} on {service}, started {starts_at}."


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "alert_name": row["alert_name"],
        "service": row["service"],
        "starts_at": row["starts_at"],
        "expression": row["expression"],
        "payload": row["payload"],
        "command_text": row["command_text"],
        "decision": row["decision"],
        "approved_text": row["approved_text"],
        "updated_at": row["updated_at"],
    }
