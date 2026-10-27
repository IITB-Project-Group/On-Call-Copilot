"""In-memory semantic and SQLite persistence for incidents."""

from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path
from typing import Sequence

from knowledge.retrieval.index import EmbeddingEncoder

from .models import Incident, IncidentMatch

DEFAULT_DATABASE_PATH = Path(__file__).with_name("incidents.sqlite3")


class SQLiteIncidentStore:
    """Persist incident records as the durable source of truth."""

    def __init__(self, database_path: str | Path = DEFAULT_DATABASE_PATH) -> None:
        self.database_path = Path(database_path)
        if str(self.database_path) == ":memory:":
            raise ValueError("database_path must be a file-backed SQLite path")

    def save(self, incident: Incident) -> None:
        """Insert an incident into SQLite."""
        self.database_path.parent.mkdir(parents=True, exist_ok=True)

        with sqlite3.connect(str(self.database_path)) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS incidents (
                    id TEXT PRIMARY KEY,
                    service TEXT NOT NULL,
                    symptom TEXT NOT NULL,
                    root_cause TEXT NOT NULL,
                    preconditions TEXT NOT NULL,
                    lesson TEXT NOT NULL,
                    fix TEXT NOT NULL,
                    reviewed_by TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT INTO incidents (
                    id, service, symptom, root_cause, preconditions,
                    lesson, fix, reviewed_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    incident.id,
                    incident.service,
                    incident.symptom,
                    incident.root_cause,
                    json.dumps(incident.preconditions),
                    incident.lesson,
                    incident.fix,
                    incident.reviewed_by,
                ),
            )

    def load_all(self) -> list[Incident]:
        """Load all saved incidents in insertion order."""
        if not self.database_path.exists():
            return []

        with sqlite3.connect(str(self.database_path)) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS incidents (
                    id TEXT PRIMARY KEY,
                    service TEXT NOT NULL,
                    symptom TEXT NOT NULL,
                    root_cause TEXT NOT NULL,
                    preconditions TEXT NOT NULL,
                    lesson TEXT NOT NULL,
                    fix TEXT NOT NULL,
                    reviewed_by TEXT NOT NULL
                )
                """
            )
            rows = connection.execute(
                """
                SELECT id, service, symptom, root_cause, preconditions,
                       lesson, fix, reviewed_by
                FROM incidents
                ORDER BY rowid
                """
            ).fetchall()

        return [
            Incident(
                id=row[0],
                service=row[1],
                symptom=row[2],
                root_cause=row[3],
                preconditions=tuple(json.loads(row[4])),
                lesson=row[5],
                fix=row[6],
                reviewed_by=row[7],
            )
            for row in rows
        ]


class MemoryStore:
    """Hold incidents and their embeddings for in-process semantic search."""

    def __init__(self, encoder: EmbeddingEncoder) -> None:
        self._encoder = encoder
        self._entries: dict[str, tuple[Incident, list[float]]] = {}

    def embed_incident(self, incident: Incident) -> list[float]:
        """Encode and validate an incident before adding it to the store."""
        encode_documents = getattr(self._encoder, "encode_documents", self._encoder.encode)
        embeddings = encode_documents([incident.embedding_text()])
        if len(embeddings) != 1:
            raise ValueError("Encoder must return one embedding per incident")
        return self._validate_embedding(embeddings[0])

    def add(self, incident: Incident, embedding: Sequence[float]) -> None:
        """Add or replace an incident with a previously computed embedding."""
        vector = self._validate_embedding(embedding)
        if self._entries:
            expected_dimensions = len(next(iter(self._entries.values()))[1])
            if len(vector) != expected_dimensions:
                raise ValueError("Incident embeddings must have a consistent dimension")
        self._entries[incident.id] = (incident, vector)

    def replace_all(self, incidents: Sequence[Incident]) -> None:
        """Rebuild the in-memory index from persisted incident records."""
        if not incidents:
            self._entries = {}
            return

        encode_documents = getattr(self._encoder, "encode_documents", self._encoder.encode)
        embeddings = encode_documents([incident.embedding_text() for incident in incidents])
        if len(embeddings) != len(incidents):
            raise ValueError("Encoder must return one embedding per incident")

        replacement: dict[str, tuple[Incident, list[float]]] = {}
        dimensions: int | None = None
        for incident, embedding in zip(incidents, embeddings):
            vector = self._validate_embedding(embedding)
            if dimensions is None:
                dimensions = len(vector)
            elif len(vector) != dimensions:
                raise ValueError("Incident embeddings must have a consistent dimension")
            replacement[incident.id] = (incident, vector)
        self._entries = replacement

    def search(self, query: str, top_k: int = 5) -> list[IncidentMatch]:
        """Return the most similar incidents ranked by cosine similarity."""
        if not query.strip():
            raise ValueError("Search query must not be empty")
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        if not self._entries:
            return []

        encode_queries = getattr(self._encoder, "encode_queries", self._encoder.encode)
        query_embeddings = encode_queries([query])
        if len(query_embeddings) != 1:
            raise ValueError("Encoder must return one embedding per query")
        query_vector = self._validate_embedding(query_embeddings[0])
        scored: list[tuple[float, Incident]] = []
        for incident, vector in self._entries.values():
            if len(vector) != len(query_vector):
                raise ValueError("Query and incident embeddings must have matching dimensions")
            score = self._cosine_similarity(query_vector, vector)
            scored.append((score, incident))
        scored.sort(key=lambda result: (-result[0], result[1].id))
        return [
            IncidentMatch(incident=incident, score=score)
            for score, incident in scored[:top_k]
        ]

    @staticmethod
    def _validate_embedding(embedding: Sequence[float]) -> list[float]:
        vector = [float(value) for value in embedding]
        if not vector or any(not math.isfinite(value) for value in vector):
            raise ValueError("Embedding must contain finite numeric values")
        if not any(vector):
            raise ValueError("Embedding must not be a zero vector")
        return vector

    @staticmethod
    def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if left_norm == 0 or right_norm == 0:
            raise ValueError("Cannot calculate similarity for a zero vector")
        return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)
