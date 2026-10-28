"""Public functions for saving and searching incident memory."""

from __future__ import annotations

from functools import lru_cache
from typing import Sequence

from knowledge.retrieval.index import create_embedding_encoder

from .models import Incident, IncidentMatch
from .store import DEFAULT_DATABASE_PATH, MemoryStore, SQLiteIncidentStore


@lru_cache(maxsize=1)
def _default_memory_store() -> MemoryStore:
    return MemoryStore(create_embedding_encoder())


def save_incident(
    service: str,
    symptom: str,
    root_cause: str,
    preconditions: Sequence[str],
    lesson: str,
    fix: str,
    reviewed_by: str,
) -> Incident:
    """Save an incident in SQLite and the in-process semantic memory store."""
    incident = Incident(
        service=_required_text(service, "service"),
        symptom=_required_text(symptom, "symptom"),
        root_cause=_required_text(root_cause, "root_cause"),
        preconditions=_preconditions(preconditions),
        lesson=_required_text(lesson, "lesson"),
        fix=_required_text(fix, "fix"),
        reviewed_by=_required_text(reviewed_by, "reviewed_by"),
    )
    store = _default_memory_store()
    embedding = store.embed_incident(incident)
    SQLiteIncidentStore(DEFAULT_DATABASE_PATH).save(incident)
    store.add(incident, embedding)
    return incident


def search_incidents(query: str, top_k: int = 5) -> list[IncidentMatch]:
    """Load saved incidents into MemoryStore and search them semantically."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("Search query must not be empty")
    store = _default_memory_store()
    incidents = SQLiteIncidentStore(DEFAULT_DATABASE_PATH).load_all()
    store.replace_all(incidents)
    return store.search(query, top_k=top_k)


def _required_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value.strip()


def _preconditions(values: Sequence[str]) -> tuple[str, ...]:
    if not isinstance(values, Sequence) or isinstance(values, str):
        raise ValueError("preconditions must be a sequence of strings")
    return tuple(_required_text(value, "precondition") for value in values)
