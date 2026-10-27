"""In-process orchestration between the runbooks-kb tool and retrieval index."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Protocol, Sequence

from .contracts import (
    RetrievalRequest,
    RetrievalResponse,
    RetrievedPassage,
    RetrievedRunbook,
)
from .index import RetrievalCandidate
from .ingest import IngestedDocument


class RerankedSearchIndex(Protocol):
    """Index interface required by the retrieval orchestration service."""

    def search_reranked(self, query: str) -> Sequence[RetrievalCandidate]:
        """Return ranked passages for a query using the configured pipeline."""


class RetrievalService:
    """Turn incident context into a contract response for the runbooks-kb tool."""

    def __init__(
        self,
        search_index: RerankedSearchIndex,
        documents: Sequence[IngestedDocument],
    ) -> None:
        """Receive a ready-to-use index and source documents without owning setup."""
        self._search_index = search_index
        self._documents_by_source = {
            self._normalize_source(document.source): document for document in documents
        }

    def retrieve(self, request: RetrievalRequest) -> RetrievalResponse:
        """Search RAG and shape ranked runbook/postmortem evidence for the caller."""
        query = request.query.strip()
        if not query:
            raise ValueError("RetrievalRequest.query must not be empty")
        ranked_candidates = self._search_index.search_reranked(query)
        passages: list[RetrievedPassage] = []
        postmortem_passages: list[RetrievedPassage] = []
        runbooks_by_source: dict[str, RetrievedRunbook] = {}

        for candidate in ranked_candidates:
            chunk = candidate.chunk
            source = self._normalize_source(str(chunk.get("source") or ""))
            source_parts = PurePosixPath(source).parts
            if len(source_parts) < 2 or source_parts[0] not in {"runbooks", "postmortems"}:
                continue

            document_type = "runbook" if source_parts[0] == "runbooks" else "postmortem"
            document = self._documents_by_source.get(source)
            if document_type == "runbook" and document is None:
                raise ValueError(f"No source document loaded for retrieved runbook: {source}")

            doc_id = str(chunk.get("doc_id") or (document.doc_id if document else PurePosixPath(source).stem))
            title = chunk.get("title") or (document.title if document else None)
            raw_metadata = chunk.get("metadata", {})
            metadata = dict(raw_metadata) if isinstance(raw_metadata, dict) else {}
            passage = RetrievedPassage(
                rank=candidate.rank,
                chunk_id=str(chunk.get("chunk_id") or ""),
                doc_id=doc_id,
                document_type=document_type,
                title=str(title) if title is not None else None,
                source=source,
                source_date=(
                    str(chunk["source_date"])
                    if chunk.get("source_date") is not None
                    else (document.source_date if document else None)
                ),
                service=(
                    str(chunk["service"])
                    if chunk.get("service") is not None
                    else (document.service if document else None)
                ),
                failure_family=(
                    str(chunk["failure_family"])
                    if chunk.get("failure_family") is not None
                    else (document.failure_family if document else None)
                ),
                text=str(chunk.get("text") or ""),
                metadata=metadata,
            )
            passages.append(passage)

            if document_type == "postmortem":
                postmortem_passages.append(passage)
                continue

            assert document is not None
            if source not in runbooks_by_source:
                runbooks_by_source[source] = RetrievedRunbook(
                    id=document.doc_id,
                    title=document.title or document.doc_id,
                    source=source,
                    source_date=document.source_date,
                    service=document.service,
                    failure_family=document.failure_family,
                    text=document.body,
                    metadata=dict(document.metadata),
                )
            runbooks_by_source[source].matched_passages.append(passage)

        runbooks = list(runbooks_by_source.values())
        return RetrievalResponse(
            runbook_ids=[runbook.id for runbook in runbooks],
            postmortem_ids=list(dict.fromkeys(passage.doc_id for passage in postmortem_passages)),
            query=query,
            passages=passages,
            runbooks=runbooks,
            postmortem_passages=postmortem_passages,
        )

    @staticmethod
    def _normalize_source(source: str) -> str:
        """Normalize source separators for matching on-disk document paths."""
        normalized = PurePosixPath(source.replace("\\", "/")).as_posix()
        return normalized[2:] if normalized.startswith("./") else normalized
