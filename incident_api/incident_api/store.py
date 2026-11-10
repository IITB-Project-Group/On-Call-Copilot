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
            connection.execute("DROP INDEX IF EXISTS incidents_alert_start")
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS incidents_alert_service_start
                ON incidents(alert_name, service, starts_at)
                """
            )
            self._ensure_columns(connection)

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
                    WHERE alert_name = ? AND service = ? AND starts_at = ?
                    """,
                    (alert_name, service, starts_at),
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

    def list_incidents(self, *, state: str | None = None) -> list[dict]:
        query = "SELECT * FROM incidents"
        if state == "open":
            query += " WHERE decision IS NULL OR decision = 'edit'"
        elif state == "closed":
            query += " WHERE decision IN ('approve', 'reject')"
        query += " ORDER BY starts_at DESC"
        with self._lock, self._connect() as connection:
            rows = connection.execute(query).fetchall()
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

    def set_proposal(
        self,
        incident_id: str,
        *,
        request_id: str,
        code: str,
        command: str,
    ) -> dict | None:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE incidents
                SET approval_request_id = ?, confirmation_code = ?, proposed_command = ?
                WHERE id = ?
                """,
                (request_id, code, command, incident_id),
            )
            if cursor.rowcount == 0:
                return None
        return self.get(incident_id)

    def set_agent(self, incident_id: str, view: dict) -> None:
        """Store what the agent graph shows for this incident: plan, hypotheses, pending decision."""
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE incidents SET agent_json = ? WHERE id = ?",
                (json.dumps(view, default=str), incident_id),
            )

    def _ensure_columns(self, connection: sqlite3.Connection) -> None:
        present = {row[1] for row in connection.execute("PRAGMA table_info(incidents)")}
        for name in (
            "approval_request_id",
            "confirmation_code",
            "proposed_command",
            "agent_json",
            "tickets_json",
        ):
            if name not in present:
                connection.execute(f"ALTER TABLE incidents ADD COLUMN {name} TEXT")

    def set_tickets(self, incident_id: str, record: dict) -> None:
        """Copy comms drafts and published notes from the agent ticket sink."""
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE incidents SET tickets_json = ? WHERE id = ?",
                (json.dumps(record, default=str), incident_id),
            )


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
        "approval_request_id": row["approval_request_id"],
        "confirmation_code": row["confirmation_code"],
        "proposed_command": row["proposed_command"],
        "agent": json.loads(row["agent_json"]) if row["agent_json"] else None,
        "tickets": json.loads(row["tickets_json"]) if row["tickets_json"] else None,
    }
