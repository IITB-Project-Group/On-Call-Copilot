import json
from unittest.mock import patch

import pytest

from knowledge.retrieval.index import (
    ChromaPassageStore,
    HybridCandidateIndex,
    OpenAICompatibleEmbeddingEncoder,
    OpenRouterReranker,
    RetrievalCandidate,
    create_embedding_encoder,
)
from knowledge.retrieval.query_rewriter import OpenRouterQueryRewriter
from knowledge.retrieval import index as retrieval_index
from knowledge.retrieval import config_loader as retrieval_config
from knowledge.retrieval.build_index import index_knowledge_corpus
from knowledge.retrieval.config_loader import RetrievalConfig, load_retrieval_config


class FakeEmbeddingEncoder:
    """Provide deterministic vectors for testing semantic retrieval behavior."""

    def __init__(self):
        """Map passage/query text to small test vectors."""
        self.vectors = {
            "payment authorization rejected": [0.9, 0.1],
            "database latency elevated": [0.1, 0.9],
            "card purchase failed": [1.0, 0.0],
            "payment failure flag disabled": [0.8, 0.2],
            "database": [1.0, 0.0],
        }

    def encode(self, texts):
        """Return the configured vector for each text."""
        return [self.vectors.get(text, [0.5, 0.5]) for text in texts]


def test_hybrid_candidate_index_returns_bm25_and_semantic_rankings():
    """Both ranking channels should find passages and preserve their citations."""
    chunks = [
        {
            "chunk_id": "payment-0",
            "doc_id": "payment",
            "source": "runbooks/payment-failure.md",
            "source_date": "2026-10-01",
            "service": "payment",
            "text": "payment authorization rejected",
        },
        {
            "chunk_id": "database-0",
            "doc_id": "database",
            "source": "postmortems/database-latency.md",
            "source_date": "2026-10-02",
            "service": "database",
            "text": "database latency elevated",
        },
    ]
    index = HybridCandidateIndex(chunks, FakeEmbeddingEncoder())

    lexical = index.search_bm25("authorization", top_k=1)
    semantic = index.search_semantic("card purchase failed", top_k=1)

    assert lexical[0].chunk["chunk_id"] == "payment-0"
    assert lexical[0].channel == "bm25"
    assert semantic[0].chunk["chunk_id"] == "payment-0"
    assert semantic[0].channel == "semantic"
    assert semantic[0].chunk["source"] == "runbooks/payment-failure.md"
    assert semantic[0].chunk["source_date"] == "2026-10-01"


def test_hybrid_candidate_index_returns_empty_for_blank_queries():
    """Blank queries should not produce arbitrary candidate results."""
    chunks = [{"chunk_id": "payment-0", "text": "payment authorization rejected"}]
    index = HybridCandidateIndex(chunks, FakeEmbeddingEncoder())

    assert index.search_bm25("   ") == []
    assert index.search_semantic("   ") == []


def test_bm25_returns_no_candidates_when_terms_do_not_match():
    """Queries with no lexical evidence should not return zero-score passages."""
    chunks = [{"chunk_id": "payment-0", "text": "payment authorization rejected"}]
    index = HybridCandidateIndex(chunks, FakeEmbeddingEncoder())

    assert index.search_bm25("unrelatedterm") == []


def test_hybrid_search_fuses_bm25_and_semantic_ranks_by_chunk_id():
    """RRF should reward a candidate returned by both channels and preserve provenance."""
    chunks = [
        {
            "chunk_id": "payment-0",
            "source": "runbooks/payment-failure.md",
            "text": "payment authorization rejected",
        },
        {
            "chunk_id": "database-0",
            "source": "postmortems/database-latency.md",
            "text": "database latency elevated",
        },
        {
            "chunk_id": "payment-1",
            "source": "postmortems/payment-incident.md",
            "text": "payment failure flag disabled",
        },
    ]
    index = HybridCandidateIndex(chunks, FakeEmbeddingEncoder())

    lexical = index.search_bm25("database", top_k=3)
    semantic = index.search_semantic("database", top_k=3)
    hybrid = index.search_hybrid("database", top_k=3, candidate_k=3, rrf_k=60)

    assert lexical[0].chunk["chunk_id"] == "database-0"
    assert semantic[0].chunk["chunk_id"] == "payment-0"
    assert hybrid[0].chunk["chunk_id"] == "database-0"
    assert [candidate.chunk["chunk_id"] for candidate in hybrid] == [
        "database-0",
        "payment-0",
        "payment-1",
    ]
    assert hybrid[0].score == 1 / 61 + 1 / 63
    assert hybrid[0].channel == "hybrid"
    assert hybrid[1].chunk["source"] == "runbooks/payment-failure.md"


def test_retrieval_config_loads_yaml_defaults():
    """The checked-in YAML file should expose all current retrieval settings."""
    config = load_retrieval_config()

    assert config == RetrievalConfig(
        target_words=350,
        overlap_words=75,
        candidate_k=50,
        rrf_k=60,
        query_rewrite_count=0,
        reranker_candidate_k=20,
        top_k=10,
    )


def test_hybrid_search_uses_yaml_defaults_and_keeps_overrides(tmp_path, monkeypatch):
    """Search defaults should come from YAML while explicit query values win."""
    config_path = tmp_path / "retrieval_config.yaml"
    config_path.write_text(
        "target_words: 200\noverlap_words: 30\ncandidate_k: 7\nrrf_k: 11\nquery_rewrite_count: 2\n"
        "reranker_candidate_k: 4\ntop_k: 3\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(retrieval_config, "_CONFIG_PATH", config_path)
    index = HybridCandidateIndex([], FakeEmbeddingEncoder())
    calls = []

    def fake_bm25(query, top_k):
        """Capture the candidate count supplied to lexical retrieval."""
        calls.append(("bm25", query, top_k))
        return []

    def fake_semantic(query, top_k):
        """Capture the candidate count supplied to semantic retrieval."""
        calls.append(("semantic", query, top_k))
        return []

    monkeypatch.setattr(index, "search_bm25", fake_bm25)
    monkeypatch.setattr(index, "search_semantic", fake_semantic)

    assert index.search_hybrid("payment alert") == []
    assert calls == [
        ("bm25", "payment alert", 7),
        ("semantic", "payment alert", 7),
    ]

    calls.clear()
    assert index.search_hybrid("payment alert", top_k=2, candidate_k=4, rrf_k=5) == []
    assert calls == [
        ("bm25", "payment alert", 4),
        ("semantic", "payment alert", 4),
    ]


def test_search_reranked_sends_configured_pool_to_reranker_and_returns_final_top_k(tmp_path, monkeypatch):
    """RRF should yield reranker_candidate_k items before final top_k is applied."""
    config_path = tmp_path / "retrieval_config.yaml"
    config_path.write_text(
        "target_words: 200\noverlap_words: 30\ncandidate_k: 7\nrrf_k: 11\nquery_rewrite_count: 0\n"
        "reranker_candidate_k: 4\ntop_k: 2\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(retrieval_config, "_CONFIG_PATH", config_path)
    index = HybridCandidateIndex([], FakeEmbeddingEncoder())
    fused_candidates = [
        RetrievalCandidate(
            chunk={"chunk_id": f"chunk-{number}", "text": f"passage {number}"},
            score=1.0 / (number + 1),
            rank=number + 1,
            channel="hybrid",
        )
        for number in range(4)
    ]
    calls = []

    def fake_search_hybrid_many(queries, top_k, candidate_k, rrf_k):
        """Capture the queries and fused pool requested for reranking."""
        calls.append((list(queries), top_k, candidate_k, rrf_k))
        return fused_candidates[:top_k]

    class RecordingReranker:
        """Record the candidate pool and return the requested leading results."""

        def rerank(self, query, candidates, top_n):
            """Capture reranker inputs and return the first top_n records."""
            calls.append(("rerank", query, len(candidates), top_n))
            return list(candidates[:top_n])

    monkeypatch.setattr(index, "search_hybrid_many", fake_search_hybrid_many)
    results = index.search_reranked("payment failure", reranker=RecordingReranker())

    assert calls == [
        (["payment failure"], 4, None, None),
        ("rerank", "payment failure", 4, 2),
    ]
    assert len(results) == 2


def test_multi_query_hybrid_search_fuses_and_deduplicates_all_rankings(monkeypatch):
    """RRF should merge BM25 and semantic lists across distinct query variants."""
    shared = RetrievalCandidate(
        chunk={"chunk_id": "shared", "text": "payment failure"},
        score=0.1,
        rank=1,
        channel="bm25",
    )
    lexical_only = RetrievalCandidate(
        chunk={"chunk_id": "lexical-only", "text": "flag disabled"},
        score=0.05,
        rank=2,
        channel="bm25",
    )
    semantic_only = RetrievalCandidate(
        chunk={"chunk_id": "semantic-only", "text": "payment errors"},
        score=0.9,
        rank=1,
        channel="semantic",
    )

    class SearchManyStore:
        """Return one deterministic semantic ranking per unique query."""

        def __init__(self):
            """Track the batch sent to the semantic store."""
            self.queries = []

        def search_many(self, queries, top_k):
            """Return semantic rankings for the supplied query batch."""
            self.queries = list(queries)
            return [[shared, semantic_only], [shared]]

    store = SearchManyStore()
    index = HybridCandidateIndex([], object(), vector_store=store)
    lexical_rankings = {
        "payment errors": [shared, lexical_only],
        "authorization failures": [shared],
    }
    monkeypatch.setattr(index, "search_bm25", lambda query, top_k: lexical_rankings[query])

    results = index.search_hybrid_many(
        ["payment errors", "authorization failures", "payment errors", " "],
        top_k=5,
        candidate_k=5,
        rrf_k=60,
    )

    assert store.queries == ["payment errors", "authorization failures"]
    assert [result.chunk["chunk_id"] for result in results].count("shared") == 1
    assert results[0].chunk["chunk_id"] == "shared"
    assert {result.chunk["chunk_id"] for result in results} == {
        "shared",
        "lexical-only",
        "semantic-only",
    }


def test_search_reranked_rewrites_queries_but_reranks_original(tmp_path, monkeypatch):
    """Configured rewrites should reach multi-query search; reranking uses original query."""
    config_path = tmp_path / "retrieval_config.yaml"
    config_path.write_text(
        "target_words: 200\noverlap_words: 30\ncandidate_k: 7\nrrf_k: 11\n"
        "query_rewrite_count: 2\nreranker_candidate_k: 4\ntop_k: 2\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(retrieval_config, "_CONFIG_PATH", config_path)
    index = HybridCandidateIndex([], object(), vector_store=object())
    original_query = "Payment authorization requests are failing."
    fused_candidates = [
        RetrievalCandidate(
            chunk={"chunk_id": f"chunk-{number}", "text": f"passage {number}"},
            score=0.1,
            rank=number + 1,
            channel="hybrid",
        )
        for number in range(4)
    ]
    search_calls = []
    rerank_calls = []

    class RecordingRewriter:
        """Return two test query variants and record the configured rewrite count."""

        def rewrite(self, query, count):
            """Return distinct rewrites for the original payment query."""
            search_calls.append(("rewrite", query, count))
            return [
                "payment errors during checkout",
                "payment authorization failures",
            ]

    class RecordingReranker:
        """Capture the final query and candidate pool sent for reranking."""

        def rerank(self, query, candidates, top_n):
            """Record reranker inputs and return top_n candidates."""
            rerank_calls.append((query, len(candidates), top_n))
            return list(candidates[:top_n])

    def search_hybrid_many(queries, top_k, candidate_k, rrf_k):
        """Capture generated search variants and return the fused candidate pool."""
        search_calls.append(("search", list(queries), top_k, candidate_k, rrf_k))
        return fused_candidates[:top_k]

    monkeypatch.setattr(index, "search_hybrid_many", search_hybrid_many)

    results = index.search_reranked(
        original_query,
        reranker=RecordingReranker(),
        query_rewriter=RecordingRewriter(),
    )

    assert search_calls == [
        ("rewrite", original_query, 2),
        (
            "search",
            [original_query, "payment errors during checkout", "payment authorization failures"],
            4,
            None,
            None,
        ),
    ]
    assert rerank_calls == [(original_query, 4, 2)]
    assert len(results) == 2


def test_search_reranked_falls_back_to_original_when_rewriting_fails(tmp_path, monkeypatch):
    """A rewrite failure should continue retrieval with only the original query."""
    config_path = tmp_path / "retrieval_config.yaml"
    config_path.write_text(
        "target_words: 200\noverlap_words: 30\ncandidate_k: 7\nrrf_k: 11\n"
        "query_rewrite_count: 2\nreranker_candidate_k: 4\ntop_k: 2\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(retrieval_config, "_CONFIG_PATH", config_path)
    index = HybridCandidateIndex([], object(), vector_store=object())
    search_calls = []

    class FailingRewriter:
        """Simulate a temporarily unavailable rewrite endpoint."""

        def rewrite(self, query, count):
            """Raise a transient error to exercise the original-query fallback."""
            raise TimeoutError("rewrite timeout")

    def search_hybrid_many(queries, top_k, candidate_k, rrf_k):
        """Capture the query list used after rewriting fails."""
        search_calls.append(list(queries))
        return []

    monkeypatch.setattr(index, "search_hybrid_many", search_hybrid_many)

    results = index.search_reranked(
        "Payment authorization requests are failing.",
        query_rewriter=FailingRewriter(),
    )

    assert search_calls == [["Payment authorization requests are failing."]]
    assert results == []


def test_search_reranked_override_beats_configured_rewrite_count(tmp_path, monkeypatch):
    """A run-time rewrite count of 0 skips rewriting even when YAML asks for 2."""
    config_path = tmp_path / "retrieval_config.yaml"
    config_path.write_text(
        "target_words: 200\noverlap_words: 30\ncandidate_k: 7\nrrf_k: 11\n"
        "query_rewrite_count: 2\nreranker_candidate_k: 4\ntop_k: 2\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(retrieval_config, "_CONFIG_PATH", config_path)
    index = HybridCandidateIndex([], object(), vector_store=object())
    searched = []

    class ForbiddenRewriter:
        """Fail the test if rewriting is attempted."""

        def rewrite(self, query, count):
            raise AssertionError("rewriter must not run")

    def search_hybrid_many(queries, top_k, candidate_k, rrf_k):
        searched.append(list(queries))
        return []

    monkeypatch.setattr(index, "search_hybrid_many", search_hybrid_many)

    index.search_reranked(
        "payment failing",
        query_rewriter=ForbiddenRewriter(),
        query_rewrite_count=0,
    )

    assert searched == [["payment failing"]]


def test_search_reranked_rejects_negative_rewrite_count():
    index = HybridCandidateIndex([], object(), vector_store=object())

    with pytest.raises(ValueError):
        index.search_reranked("payment failing", query_rewrite_count=-1)


def test_openrouter_query_rewriter_parses_unique_variants():
    """The rewrite client should parse JSON and discard duplicates of the original."""
    rewriter = OpenRouterQueryRewriter(
        api_key="test-key",
        model="openai/gpt-4.1-mini",
        base_url="https://rewrite.example/v1",
    )
    response_payload = json.dumps(
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "queries": [
                                    "payment processing transactions are being declined",
                                    "checkout payment service errors",
                                    "Payment authorization requests failing",
                                ]
                            }
                        )
                    }
                }
            ]
        }
    ).encode("utf-8")

    with patch("knowledge.retrieval.query_rewriter.urlopen") as mocked_urlopen:
        mocked_urlopen.return_value.__enter__.return_value.read.return_value = response_payload
        rewrites = rewriter.rewrite("Payment authorization requests failing", count=2)

    request = mocked_urlopen.call_args.args[0]
    payload = json.loads(request.data)
    assert request.full_url == "https://rewrite.example/v1/chat/completions"
    assert request.get_header("Authorization") == "Bearer test-key"
    assert payload["model"] == "openai/gpt-4.1-mini"
    assert rewrites == [
        "payment processing transactions are being declined",
        "checkout payment service errors",
    ]


def test_openrouter_reranker_sorts_response_and_preserves_passage_provenance():
    """OpenRouter rerank indexes should map to the original passage chunks."""
    candidates = [
        RetrievalCandidate(
            chunk={"chunk_id": "payment-0", "source": "runbooks/payment.md", "text": "payment errors"},
            score=0.02,
            rank=1,
            channel="hybrid",
        ),
        RetrievalCandidate(
            chunk={"chunk_id": "cart-0", "source": "runbooks/cart.md", "text": "cart errors"},
            score=0.01,
            rank=2,
            channel="hybrid",
        ),
        RetrievalCandidate(
            chunk={"chunk_id": "payment-1", "source": "postmortems/payment.md", "text": "payment timeout"},
            score=0.005,
            rank=3,
            channel="hybrid",
        ),
    ]
    response_payload = json.dumps(
        {
            "results": [
                {"index": 2, "relevance_score": 0.7},
                {"index": 0, "relevance_score": 0.95},
                {"index": 1, "relevance_score": 0.2},
            ]
        }
    ).encode("utf-8")
    reranker = OpenRouterReranker(
        api_key="test-key",
        model="cohere/rerank-v3.5",
        base_url="https://rerank.example/v1",
    )

    with patch("knowledge.retrieval.index.urlopen") as mocked_urlopen:
        mocked_urlopen.return_value.__enter__.return_value.read.return_value = response_payload
        results = reranker.rerank("payment failure", candidates, top_n=2)

    request = mocked_urlopen.call_args.args[0]
    payload = json.loads(request.data)
    assert request.full_url == "https://rerank.example/v1/rerank"
    assert request.get_header("Authorization") == "Bearer test-key"
    assert payload["model"] == "cohere/rerank-v3.5"
    assert payload["query"] == "payment failure"
    assert payload["documents"] == [candidate.chunk["text"] for candidate in candidates]
    assert payload["top_n"] == 2
    assert [result.chunk["chunk_id"] for result in results] == ["payment-0", "payment-1"]
    assert results[0].chunk["source"] == "runbooks/payment.md"
    assert results[0].score == 0.95
    assert results[0].channel == "reranker"


def test_openrouter_reranker_loads_model_from_dotenv(tmp_path, monkeypatch):
    """The reranker should read RERANKER_MODEL from dotenv when not passed directly."""
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text("RERANKER_MODEL=cohere/rerank-v3.5\n", encoding="utf-8")
    monkeypatch.setattr(retrieval_index, "_DOTENV_PATH", dotenv_path)
    monkeypatch.setenv("EMBEDDING_API_KEY", "test-key")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("RERANKER_MODEL", raising=False)

    reranker = OpenRouterReranker()

    assert reranker.model == "cohere/rerank-v3.5"
    assert reranker.api_key == "test-key"


def test_retrieval_config_rejects_invalid_chunk_overlap(tmp_path):
    """Invalid chunk overlap settings should fail with a clear validation error."""
    config_path = tmp_path / "retrieval_config.yaml"
    config_path.write_text(
        "target_words: 10\noverlap_words: 10\ncandidate_k: 5\nrrf_k: 60\n"
        "query_rewrite_count: 0\nreranker_candidate_k: 4\ntop_k: 3\n",
        encoding="utf-8",
    )

    try:
        load_retrieval_config(config_path)
    except ValueError as error:
        assert "overlap_words" in str(error)
    else:
        raise AssertionError("Invalid overlap should be rejected")


def test_openai_compatible_encoder_sorts_vectors_by_response_index():
    """The embedding adapter should preserve input order and authenticate requests."""

    class StubResponse:
        """Mimic the minimal response interface used by urlopen."""

        def __enter__(self):
            """Return the response object for a context manager."""
            return self

        def __exit__(self, exception_type, exception, traceback):
            """Allow the response to be used in a with statement."""
            return False

        def read(self):
            """Return deliberately out-of-order embedding response data."""
            return json.dumps(
                {
                    "data": [
                        {"index": 1, "embedding": [0.0, 1.0]},
                        {"index": 0, "embedding": [1.0, 0.0]},
                    ]
                }
            ).encode("utf-8")

    encoder = OpenAICompatibleEmbeddingEncoder(
        api_key="test-key",
        model="test-model",
        base_url="https://embedding.example/v1",
    )
    with patch("knowledge.retrieval.index.urlopen", return_value=StubResponse()) as mocked_urlopen:
        vectors = encoder.encode(["first passage", "second passage"])

    request = mocked_urlopen.call_args.args[0]
    assert vectors == [[1.0, 0.0], [0.0, 1.0]]
    assert request.full_url == "https://embedding.example/v1/embeddings"
    assert request.get_header("Authorization") == "Bearer test-key"


def test_openrouter_encoder_applies_e5_task_prefixes():
    """OpenRouter E5 requests should distinguish passage text from query text."""
    encoder = OpenAICompatibleEmbeddingEncoder(
        api_key="test-key",
        model="intfloat/multilingual-e5-large",
    )
    response_payload = json.dumps({"data": [{"index": 0, "embedding": [1.0, 0.0]}]}).encode("utf-8")

    with patch("knowledge.retrieval.index.urlopen") as mocked_urlopen:
        mocked_urlopen.return_value.__enter__.return_value.read.return_value = response_payload
        encoder.encode_documents(["payment runbook"])
        encoder.encode_queries(["card payment failed"])

    document_request = mocked_urlopen.call_args_list[0].args[0]
    query_request = mocked_urlopen.call_args_list[1].args[0]
    assert json.loads(document_request.data)["input"] == ["passage: payment runbook"]
    assert json.loads(query_request.data)["input"] == ["query: card payment failed"]


def test_encoder_factory_accepts_openrouter_and_local_hashes():
    """OpenRouter remains the remote encoder, and local hashing needs no API key."""
    with patch.dict(
        "os.environ",
        {
            "EMBEDDING_PROVIDER": "openrouter",
            "EMBEDDING_MODEL": "baai/bge-m3",
            "EMBEDDING_API_KEY": "test-key",
        },
    ):
        encoder = create_embedding_encoder()

    assert isinstance(encoder, OpenAICompatibleEmbeddingEncoder)
    assert encoder.model == "baai/bge-m3"

    local_encoder = create_embedding_encoder(provider="local", model_name="local/hashed-tokens")
    from knowledge.retrieval.index import HashedTokenEncoder

    assert isinstance(local_encoder, HashedTokenEncoder)
    assert local_encoder.model == "local/hashed-tokens"

    with pytest.raises(ValueError, match="openrouter"):
        create_embedding_encoder(provider="sentence-transformers")


def test_encoder_factory_loads_settings_from_dotenv(tmp_path, monkeypatch):
    """The encoder factory should load provider credentials from the configured .env."""
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "EMBEDDING_PROVIDER=openrouter\nEMBEDDING_MODEL=baai/bge-m3\nEMBEDDING_API_KEY=dotenv-test-key\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(retrieval_index, "_DOTENV_PATH", dotenv_path)
    monkeypatch.delenv("EMBEDDING_PROVIDER", raising=False)
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
    monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)

    encoder = create_embedding_encoder()

    assert isinstance(encoder, OpenAICompatibleEmbeddingEncoder)
    assert encoder.model == "baai/bge-m3"
    assert encoder.api_key == "dotenv-test-key"


def test_chroma_passage_store_persists_embeddings_and_metadata(tmp_path):
    """Passage embeddings and citations should remain searchable after reopening Chroma."""
    chunks = [
        {
            "chunk_id": "payment-0",
            "doc_id": "payment",
            "source": "runbooks/payment-failure.md",
            "source_date": "2026-10-01",
            "service": "payment",
            "failure_family": "payment_failure",
            "title": "Payment failure",
            "text": "payment authorization rejected",
            "metadata": {"tags": ["payments", "checkout"], "severity": "sev2"},
        },
        {
            "chunk_id": "database-0",
            "doc_id": "database",
            "source": "postmortems/database-latency.md",
            "source_date": "2026-10-02",
            "service": "database",
            "text": "database latency elevated",
            "metadata": {},
        },
    ]
    encoder = FakeEmbeddingEncoder()
    persist_directory = tmp_path / "chroma"
    initial_store = ChromaPassageStore(
        encoder,
        persist_directory=persist_directory,
        collection_name="test_passages",
    )

    assert initial_store.index_chunks(chunks) == 2

    reopened_store = ChromaPassageStore(
        encoder,
        persist_directory=persist_directory,
        collection_name="test_passages",
    )
    index = HybridCandidateIndex(chunks, encoder, vector_store=reopened_store)
    results = index.search_semantic("card purchase failed", top_k=1)

    assert results[0].chunk["chunk_id"] == "payment-0"
    assert results[0].chunk["source"] == "runbooks/payment-failure.md"
    assert results[0].chunk["source_date"] == "2026-10-01"
    assert results[0].chunk["metadata"] == {"tags": ["payments", "checkout"], "severity": "sev2"}
    assert results[0].channel == "semantic"


def test_index_knowledge_corpus_only_indexes_runbooks_and_postmortems(tmp_path):
    """The corpus builder should exclude retrieval documentation and sync idempotently."""
    knowledge_dir = tmp_path / "knowledge"
    runbook_dir = knowledge_dir / "runbooks"
    postmortem_dir = knowledge_dir / "postmortems"
    retrieval_dir = knowledge_dir / "retrieval"
    runbook_dir.mkdir(parents=True)
    postmortem_dir.mkdir()
    retrieval_dir.mkdir()
    (runbook_dir / "payment-failure.md").write_text(
        "---\nid: payment-1\ntitle: Payment failure\nservice: payment\n---\n\n# Fix\n\nPayment authorization is rejected.\n",
        encoding="utf-8",
    )
    (postmortem_dir / "payment-incident.md").write_text(
        "---\nid: incident-1\ntitle: Payment incident\nservice: payment\n---\n\n# Cause\n\nThe payment provider timed out.\n",
        encoding="utf-8",
    )
    (retrieval_dir / "README.md").write_text("Do not index this setup guide.", encoding="utf-8")

    encoder = FakeEmbeddingEncoder()
    summary = index_knowledge_corpus(
        knowledge_dir=knowledge_dir,
        persist_directory=tmp_path / "chroma",
        collection_name="corpus_test",
        encoder=encoder,
    )

    assert summary.document_count == 2
    assert summary.chunk_count == 2
    assert summary.changed_count == 2
    assert summary.collection_count == 2

    second_summary = index_knowledge_corpus(
        knowledge_dir=knowledge_dir,
        persist_directory=tmp_path / "chroma",
        collection_name="corpus_test",
        encoder=encoder,
    )
    assert second_summary.changed_count == 0
    assert second_summary.collection_count == 2
