"""In-process runbook and lesson review for one incident.

This does not save a lesson. Saving waits until a person reviews the note.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Sequence

from knowledge.retrieval.contracts import check_lesson_policy


def review_incident_knowledge(
    query: str,
    *,
    incident_service: str,
    incident_failure_family: str,
    incident_evidence: Sequence[str],
    runbooks_kb=None,
    find_incidents=None,
) -> dict[str, Any]:
    """Return runbooks, postmortems, and an apply-or-reject decision for each lesson."""
    text = query.strip()
    if not text:
        raise ValueError("query must not be empty")
    tool = runbooks_kb if runbooks_kb is not None else _default_runbooks()
    find = find_incidents if find_incidents is not None else _default_find_incidents()
    retrieval_error = None
    try:
        response = tool(text)
    except (RuntimeError, ValueError) as exc:
        response = None
        retrieval_error = str(exc)
    memory_error = None
    try:
        matches = find(text)
    except (RuntimeError, ValueError) as exc:
        matches = []
        memory_error = str(exc)
    lessons = [
        _lesson_decision(match, incident_service, incident_failure_family, incident_evidence)
        for match in matches
    ]
    return {
        "query": text,
        "runbook_ids": [] if response is None else list(response.runbook_ids),
        "postmortem_ids": [] if response is None else list(response.postmortem_ids),
        "runbooks": [] if response is None else [asdict(runbook) for runbook in response.runbooks],
        "postmortem_passages": (
            [] if response is None else [asdict(passage) for passage in response.postmortem_passages]
        ),
        "lessons": lessons,
        "retrieval_error": retrieval_error,
        "memory_error": memory_error,
    }


def _lesson_decision(match, service: str, failure_family: str, evidence: Sequence[str]) -> dict[str, Any]:
    incident = match.incident
    decision = check_lesson_policy(
        lesson_service=incident.service,
        lesson_failure_family=incident.failure_family,
        lesson_preconditions=incident.preconditions,
        incident_service=service,
        incident_failure_family=failure_family,
        incident_evidence=evidence,
    )
    return {
        "id": incident.id,
        "service": incident.service,
        "failure_family": incident.failure_family,
        "decision": decision,
        "lesson": incident.lesson,
        "score": match.score,
    }


def _default_runbooks():
    from knowledge.retrieval.runbooks_kb_tool import create_runbooks_kb_tool

    return create_runbooks_kb_tool()


def _default_find_incidents():
    from knowledge.memory.incidents import search_incidents

    return search_incidents
