"""Data contracts for incident memory."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class Incident:
    """A reviewed incident and the conditions under which its lesson applies."""

    service: str
    symptom: str
    root_cause: str
    preconditions: tuple[str, ...]
    lesson: str
    fix: str
    reviewed_by: str
    id: str = field(default_factory=lambda: str(uuid4()))

    def embedding_text(self) -> str:
        """Return the incident content used for semantic indexing."""
        preconditions = "; ".join(self.preconditions) or "None recorded"
        return (
            f"Service: {self.service}\n"
            f"Symptom: {self.symptom}\n"
            f"Root cause: {self.root_cause}\n"
            f"Preconditions: {preconditions}\n"
            f"Lesson: {self.lesson}\n"
            f"Fix: {self.fix}"
        )


@dataclass(frozen=True)
class IncidentMatch:
    """A semantically ranked incident and its cosine similarity score."""

    incident: Incident
    score: float
