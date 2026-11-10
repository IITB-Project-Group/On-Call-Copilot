"""Long-term lessons in a LangGraph store, recalled only when their preconditions match.

Each lesson states the observations under which it applies, such as
``{"cpu_ratio.ad": {"op": "gte", "value": 0.9}}``. Recall runs ``InputGuardrails.check_lesson``
against the incident's observations: an unreviewed, stale, poisoned or non-matching lesson is
returned as rejected with the reason, never applied. Writes pass ``validate_memory_write`` and
are refused while the playbook is frozen for the held-out run.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from output_guardrails import validate_memory_write

PLAYBOOK_DIR = Path(__file__).resolve().parents[2] / "knowledge" / "playbook"
SEED_LESSONS = PLAYBOOK_DIR / "seed-lessons.yaml"


class LessonStore:
    def __init__(
        self, store=None, *, guardrails, namespace: tuple[str, ...] = ("lessons",), frozen: bool = False
    ):
        if store is None:
            from langgraph.store.memory import InMemoryStore

            store = InMemoryStore()
        self.store, self.guardrails, self.namespace, self.frozen = store, guardrails, namespace, frozen

    def put(self, lesson: dict, *, incident_outcome: str = "verified_failure") -> str:
        check = validate_memory_write(lesson, frozen=self.frozen, incident_outcome=incident_outcome)
        if check.blocked:
            raise ValueError("lesson refused: " + ",".join(sorted(check.codes)))
        record = {**lesson, "created_at": lesson.get("created_at") or datetime.now(timezone.utc).isoformat()}
        record["id"] = str(
            record.get("id")
            or "lesson-" + hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()[:10]
        )
        self.store.put(self.namespace, record["id"], record)
        return record["id"]

    def all(self) -> list[dict]:
        return [item.value for item in self.store.search(self.namespace, limit=1000)]

    def recall(
        self, context: dict, *, service: str | None = None, fault_type: str | None = None
    ) -> list[dict]:
        out = []
        for lesson in self.all():
            if service and lesson.get("service") != service:
                continue
            if fault_type and lesson.get("fault_type") != fault_type:
                continue
            check = self.guardrails.check_lesson(lesson, context)
            reasons = [f.message for f in check.findings if f.action.value == "block"]
            out.append(
                {
                    "id": lesson["id"],
                    "service": lesson["service"],
                    "fault_type": lesson["fault_type"],
                    "lesson": lesson["lesson"],
                    "applies_when": lesson.get("applies_when", ""),
                    "applicable": not check.blocked,
                    "reason": "; ".join(reasons) or "preconditions match",
                }
            )
        return out

    def applicable(self, context: dict) -> list[dict]:
        return [lesson for lesson in self.recall(context) if lesson["applicable"]]

    def load(self, path: Path) -> int:
        """Load reviewed lessons from a YAML or JSON playbook file. Returns how many were loaded."""
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        lessons = data.get("lessons", []) if isinstance(data, dict) else data
        for lesson in lessons:
            self.store.put(self.namespace, lesson["id"], lesson)
        return len(lessons)


def playbook_hash(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def open_store(path: str | None = None):
    """A persistent LangGraph SqliteStore, or an in-memory store when no path is given."""
    if not path:
        from langgraph.store.memory import InMemoryStore

        return InMemoryStore()
    import sqlite3

    from langgraph.store.sqlite import SqliteStore

    store = SqliteStore(sqlite3.connect(path, check_same_thread=False, isolation_level=None))
    store.setup()
    return store


def lesson_store(
    guardrails: Any, *, memory: bool, playbook: str | None, frozen: bool, path: str | None = None
):
    """The lesson store for one experiment: seed lessons from past postmortems, plus the playbook."""
    if not memory:
        return None
    store = LessonStore(open_store(path), guardrails=guardrails, frozen=frozen)
    store.load(SEED_LESSONS)
    if playbook:
        store.load(Path(playbook))
    return store
