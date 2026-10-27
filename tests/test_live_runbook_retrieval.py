"""Opt-in live retrieval test using OpenRouter and the persisted Chroma index.

Run with RUN_LIVE_RETRIEVAL_TESTS=1 to make a query-rewrite request, one batched
query-embedding request, and one rerank request. Set LIVE_RETRIEVAL_QUERY to
choose the incident query. Normal test-suite runs skip this integration test.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from knowledge.retrieval import (
    CandidateReranker,
    ChromaPassageStore,
    HybridCandidateIndex,
    OpenRouterReranker,
    RetrievalCandidate,
    chunk_markdown_documents,
    create_embedding_encoder,
    load_retrieval_config,
)
from knowledge.retrieval.build_index import load_retrieval_documents

_RUN_LIVE_TESTS = os.environ.get("RUN_LIVE_RETRIEVAL_TESTS") == "1"


class _RecordingReranker:
    """Record the actual candidate pool and delegate to OpenRouter."""

    def __init__(self) -> None:
        """Create the real OpenRouter reranker from local environment settings."""
        self._reranker: CandidateReranker = OpenRouterReranker()
        self.candidates: list[RetrievalCandidate] = []
        self.top_n: int | None = None

    def rerank(
        self,
        query: str,
        candidates: list[RetrievalCandidate],
        top_n: int,
    ) -> list[RetrievalCandidate]:
        """Record inputs and return OpenRouter's actual reranked results."""
        self.candidates = list(candidates)
        self.top_n = top_n
        return self._reranker.rerank(query, candidates, top_n)


@pytest.mark.skipif(
    not _RUN_LIVE_TESTS,
    reason="Set RUN_LIVE_RETRIEVAL_TESTS=1 to call OpenRouter",
)
def test_live_query_returns_full_reranked_passages():
    """Run a supplied incident query through Chroma, RRF, and OpenRouter reranking."""
    query = os.environ.get("LIVE_RETRIEVAL_QUERY", "").strip()
    if not query:
        pytest.fail("Set LIVE_RETRIEVAL_QUERY to the incident query you want to test")

    repository_root = Path(__file__).resolve().parents[1]
    documents = load_retrieval_documents(repository_root / "knowledge")
    chunks = chunk_markdown_documents(documents)
    encoder = create_embedding_encoder()
    store = ChromaPassageStore(encoder)
    index = HybridCandidateIndex(chunks, encoder, vector_store=store)
    reranker = _RecordingReranker()
    config = load_retrieval_config()

    results = index.search_reranked(query, reranker=reranker)

    assert store.count > 0
    assert 0 < len(reranker.candidates) <= config.reranker_candidate_k
    assert reranker.top_n == config.top_k
    assert len(results) == config.top_k
    assert all(result.channel == "reranker" for result in results)

    input_chunks = {candidate.chunk["chunk_id"]: candidate.chunk for candidate in reranker.candidates}
    assert all(result.chunk == input_chunks[result.chunk["chunk_id"]] for result in results)
    assert all(
        result.chunk.get("chunk_id") and result.chunk.get("text") and result.chunk.get("source")
        for result in results
    )

    print(f"Query: {query}")
    print(f"Persisted passages: {store.count}")
    print(f"Candidates reranked: {len(reranker.candidates)}")
    print(f"Final results: {len(results)}")
    for result in results:
        chunk = result.chunk
        print(
            f"\nRank {result.rank} | score={result.score:.4f} "
            f"| chunk_id={chunk['chunk_id']} | source={chunk['source']}"
        )
        print(chunk["text"])
