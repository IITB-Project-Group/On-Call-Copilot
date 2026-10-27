"""One-time startup composition for the in-process runbooks-kb service."""

from __future__ import annotations

from pathlib import Path

from .build_index import load_retrieval_documents
from .chunker import chunk_markdown_documents
from .index import (
    ChromaPassageStore,
    EmbeddingEncoder,
    HybridCandidateIndex,
    RetrievalCandidate,
    create_embedding_encoder,
)
from .service import RetrievalService

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class _RewriteCountOverride:
    """Pin the query rewrite count for one service without editing the YAML config."""

    def __init__(self, index: HybridCandidateIndex, query_rewrite_count: int) -> None:
        self._index = index
        self._query_rewrite_count = query_rewrite_count

    def search_reranked(self, query: str) -> list[RetrievalCandidate]:
        return self._index.search_reranked(query, query_rewrite_count=self._query_rewrite_count)


def initialize_retrieval_service(
    *,
    knowledge_dir: str | Path | None = None,
    persist_directory: str | Path | None = None,
    collection_name: str = "knowledge_passages",
    encoder: EmbeddingEncoder | None = None,
    query_rewrite_count: int | None = None,
) -> RetrievalService:
    """Load source documents and create the reusable Chroma-backed service once.

    The corpus must already be indexed with ``knowledge.retrieval.build_index``.
    This initializer does not embed or write corpus passages, so startup cannot
    unexpectedly trigger a batch of embedding charges.
    """
    source_directory = Path(knowledge_dir or (_REPOSITORY_ROOT / "knowledge"))
    documents = load_retrieval_documents(source_directory)
    if not documents:
        raise RuntimeError(f"No runbook or postmortem documents found under {source_directory}")

    chunks = chunk_markdown_documents(documents)
    if not chunks:
        raise RuntimeError("Runbook and postmortem documents produced no passage chunks")

    selected_encoder = encoder or create_embedding_encoder()
    vector_store = ChromaPassageStore(
        selected_encoder,
        persist_directory=persist_directory,
        collection_name=collection_name,
    )
    if vector_store.count == 0:
        raise RuntimeError(
            "The Chroma passage index is empty. Build it with "
            "python -m knowledge.retrieval.build_index before starting runbooks-kb."
        )

    search_index = HybridCandidateIndex(
        chunks,
        selected_encoder,
        vector_store=vector_store,
    )
    if query_rewrite_count is not None:
        return RetrievalService(_RewriteCountOverride(search_index, query_rewrite_count), documents)
    return RetrievalService(search_index, documents)
