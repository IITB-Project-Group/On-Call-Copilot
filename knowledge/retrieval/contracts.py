from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Literal, Sequence


@dataclass
class RetrievalRequest:
    """Query string supplied by the runbooks-kb tool for RAG retrieval."""

    query: str


@dataclass
class LessonCandidate:
    """A retrieved memory lesson that was scored for the current incident.

    The lesson contains the basic metadata needed to decide whether it is
    applicable, as well as a score and human-readable reason for why it was
    selected.
    """

    id: str
    service: str
    failure_family: str
    preconditions: List[str] = field(default_factory=list)
    score: float = 0.0
    reason: str = ""


@dataclass(frozen=True)
class RetrievedPassage:
    """A ranked runbook or postmortem passage with its citation metadata."""

    rank: int
    chunk_id: str
    doc_id: str
    document_type: Literal["runbook", "postmortem"]
    title: str | None
    source: str
    source_date: str | None
    service: str | None
    failure_family: str | None
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievedRunbook:
    """A complete runbook plus the ranked passages that matched the query."""

    id: str
    title: str
    source: str
    source_date: str
    service: str | None
    failure_family: str | None
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    matched_passages: List[RetrievedPassage] = field(default_factory=list)


@dataclass
class RetrievalResponse:
    """Result set returned by the retrieval service for a single incident.

    Passage records preserve the reranked order. Runbooks include their complete
    source text and matched passages; postmortems remain clearly labeled as
    historical context. Memory lesson retrieval uses a separate contract.
    """

    runbook_ids: List[str] = field(default_factory=list)
    postmortem_ids: List[str] = field(default_factory=list)
    query: str = ""
    passages: List[RetrievedPassage] = field(default_factory=list)
    runbooks: List[RetrievedRunbook] = field(default_factory=list)
    postmortem_passages: List[RetrievedPassage] = field(default_factory=list)


def _normalize_text(value: str) -> str:
    """Standardize incoming text before matching it against evidence.

    This keeps string comparisons stable and reduces false mismatches caused by
    case or surrounding whitespace differences.
    """
    return value.lower().strip()


def _matches_preconditions(preconditions: Sequence[str], evidence: Sequence[str]) -> bool:
    """Check whether the lesson preconditions are reflected by the current evidence.

    The logic is intentionally conservative: it compares token overlap rather
    than exact string equality so semantically similar evidence still matches,
    while a misleading lesson remains rejected when the required evidence is not
    present.
    """
    evidence_tokens = set()
    for item in evidence:
        evidence_tokens.update(_normalize_text(item).split())

    for item in preconditions:
        precondition_tokens = set(_normalize_text(item).split())
        if not precondition_tokens:
            continue

        overlap = len(precondition_tokens & evidence_tokens)
        if overlap < 2 and len(precondition_tokens) > 1:
            return False

    return True


def check_lesson_policy(
    *,
    lesson_service: str,
    lesson_failure_family: str,
    lesson_preconditions: Sequence[str],
    incident_service: str,
    incident_failure_family: str,
    incident_evidence: Sequence[str],
) -> str:
    """Return whether a lesson is safe to apply for the current incident.

    The memory policy follows the README's guardrail: a lesson is only reusable
    when the service, failure family, and evidence-backed preconditions all line
    up. Otherwise the system must reject the lesson instead of applying it.
    """
    if lesson_service != incident_service:
        return "reject"

    if lesson_failure_family != incident_failure_family:
        return "reject"

    if _matches_preconditions(lesson_preconditions, incident_evidence):
        return "apply"

    return "reject"
