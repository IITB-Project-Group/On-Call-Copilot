import json
import math
import sys
from unittest.mock import patch

import pytest

from knowledge.retrieval import index as retrieval_index
from knowledge.retrieval.index import (
    ChromaPassageStore,
    HybridCandidateIndex,
    OpenAICompatibleEmbeddingEncoder,
    OpenRouterReranker,
    RetrievalCandidate,
    _cosine_similarity,
    _fuse_rankings,
)

ENV_NAMES = (
    "EMBEDDING_API_KEY",
    "EMBEDDING_MODEL",
    "EMBEDDING_BASE_URL",
    "EMBEDDING_PROVIDER",
    "OPENROUTER_API_KEY",
    "RERANKER_MODEL",
    "RERANK_BASE_URL",
)


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(retrieval_index, "_DOTENV_PATH", tmp_path / "missing.env")
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


class StubEncoder:
    """Deterministic encoder whose behavior can be broken on demand."""

    def __init__(self, model=None):
        self.model = model
        self.broken = False

    def encode(self, texts):
        if self.broken:
            return []
        return [[float(len(text) % 5 + 1), 1.0] for text in texts]


def _chunk(chunk_id, text, **extra):
    return {"chunk_id": chunk_id, "doc_id": "doc", "source": "runbooks/doc.md", "text": text, **extra}


def _candidates(*texts):
    return [
        RetrievalCandidate(
            chunk={"chunk_id": f"c{number}", "text": text}, score=0.1, rank=number, channel="hybrid"
        )
        for number, text in enumerate(texts, start=1)
    ]


def _respond(mocked_urlopen, payload):
    raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
    mocked_urlopen.return_value.__enter__.return_value.read.return_value = raw


def _encode_with(payload, texts=("one",)):
    encoder = OpenAICompatibleEmbeddingEncoder(api_key="key", model="model")
    with patch("knowledge.retrieval.index.urlopen") as mocked_urlopen:
        _respond(mocked_urlopen, payload)
        return encoder.encode(list(texts))


def _rerank_with(payload, candidates=None, top_n=2):
    reranker = OpenRouterReranker(api_key="key", model="model")
    with patch("knowledge.retrieval.index.urlopen") as mocked_urlopen:
        _respond(mocked_urlopen, payload)
        return reranker.rerank("query", candidates or _candidates("a", "b"), top_n=top_n)


def test_embedding_encoder_requires_api_key_and_model():
    with pytest.raises(ValueError, match="EMBEDDING_API_KEY"):
        OpenAICompatibleEmbeddingEncoder(model="model")
    with pytest.raises(ValueError, match="EMBEDDING_MODEL"):
        OpenAICompatibleEmbeddingEncoder(api_key="key")


def test_embedding_encoder_returns_nothing_for_no_texts():
    encoder = OpenAICompatibleEmbeddingEncoder(api_key="key", model="model")

    with patch("knowledge.retrieval.index.urlopen") as mocked_urlopen:
        assert encoder.encode([]) == []
    mocked_urlopen.assert_not_called()


@pytest.mark.parametrize(
    "payload", [{}, {"data": "nope"}, {"data": [{"embedding": [1.0]}, {"embedding": [1.0]}]}]
)
def test_embedding_encoder_requires_one_vector_per_text(payload):
    with pytest.raises(ValueError, match="one vector per input text"):
        _encode_with(payload)


@pytest.mark.parametrize("embedding", [[], None, "abc"])
def test_embedding_encoder_rejects_invalid_vectors(embedding):
    with pytest.raises(ValueError, match="invalid vector"):
        _encode_with({"data": [{"index": 0, "embedding": embedding}]})


def test_reranker_requires_credentials_and_model():
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        OpenRouterReranker(model="model")
    with pytest.raises(ValueError, match="RERANKER_MODEL"):
        OpenRouterReranker(api_key="key")


def test_reranker_validates_its_inputs_without_calling_the_api():
    reranker = OpenRouterReranker(api_key="key", model="model")

    with patch("knowledge.retrieval.index.urlopen") as mocked_urlopen:
        with pytest.raises(ValueError, match="top_n must be positive"):
            reranker.rerank("query", _candidates("a"), top_n=0)
        assert reranker.rerank("   ", _candidates("a"), top_n=1) == []
        assert reranker.rerank("query", [], top_n=1) == []
    mocked_urlopen.assert_not_called()


def test_reranker_requires_a_results_list():
    with pytest.raises(ValueError, match="results list"):
        _rerank_with({"results": "nope"})


def test_reranker_rejects_non_mapping_results():
    with pytest.raises(ValueError, match="invalid result"):
        _rerank_with({"results": ["not a dict"]})


@pytest.mark.parametrize("index", [True, "0", -1, 2, None])
def test_reranker_rejects_invalid_candidate_indexes(index):
    with pytest.raises(ValueError, match="invalid candidate index"):
        _rerank_with({"results": [{"index": index, "relevance_score": 0.5}]})


@pytest.mark.parametrize("score", [True, "high", None])
def test_reranker_rejects_invalid_relevance_scores(score):
    with pytest.raises(ValueError, match="invalid relevance score"):
        _rerank_with({"results": [{"index": 0, "relevance_score": score}]})


@pytest.mark.parametrize("literal", [b"NaN", b"Infinity"])
def test_reranker_rejects_non_finite_scores(literal):
    payload = b'{"results": [{"index": 0, "relevance_score": ' + literal + b"}]}"

    with pytest.raises(ValueError, match="non-finite"):
        _rerank_with(payload)


def test_reranker_ignores_repeated_candidate_indexes():
    results = _rerank_with(
        {
            "results": [
                {"index": 1, "relevance_score": 0.9},
                {"index": 1, "relevance_score": "ignored because it repeats an index"},
                {"index": 0, "relevance_score": 0.3},
            ]
        }
    )

    assert [result.chunk["chunk_id"] for result in results] == ["c2", "c1"]
    assert [result.rank for result in results] == [1, 2]


def test_chroma_store_requires_chromadb_and_a_positive_batch_size(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="batch_size must be positive"):
        ChromaPassageStore(StubEncoder(), tmp_path / "chroma", batch_size=0)

    monkeypatch.setitem(sys.modules, "chromadb", None)
    with pytest.raises(ImportError, match="Install chromadb"):
        ChromaPassageStore(StubEncoder(), tmp_path / "chroma")


def test_chroma_store_refuses_a_collection_built_with_another_embedding_model(tmp_path):
    ChromaPassageStore(StubEncoder("model-a"), tmp_path / "chroma")

    with pytest.raises(ValueError, match="embedding model 'model-a'.*'model-b'"):
        ChromaPassageStore(StubEncoder("model-b"), tmp_path / "chroma")


def test_chroma_store_validates_chunk_ids_before_indexing(tmp_path):
    store = ChromaPassageStore(StubEncoder(), tmp_path / "chroma")

    with pytest.raises(ValueError, match="must have a chunk_id"):
        store.index_chunks([{"text": "no id"}])
    with pytest.raises(ValueError, match="must be unique"):
        store.index_chunks([_chunk("same", "one"), _chunk("same", "two")])


def test_chroma_store_rejects_encoders_that_drop_embeddings(tmp_path):
    encoder = StubEncoder()
    encoder.broken = True
    store = ChromaPassageStore(encoder, tmp_path / "chroma")

    with pytest.raises(ValueError, match="one embedding per passage"):
        store.index_chunks([_chunk("a", "text")])


def test_chroma_store_updates_metadata_without_reembedding_and_removes_stale_passages(tmp_path):
    encoder = StubEncoder()
    store = ChromaPassageStore(encoder, tmp_path / "chroma", batch_size=1)
    assert store.sync_chunks([_chunk("a", "alpha text", service="cart"), _chunk("b", "beta text")]) == 2

    encoder.broken = True
    changed = store.sync_chunks([_chunk("a", "alpha text", service="payment")])

    assert changed == 1
    assert store.count == 1
    found = store._restore_chunk("a", "alpha text", store._collection.get(ids=["a"])["metadatas"][0])
    assert found["service"] == "payment"
    assert store.sync_chunks([_chunk("a", "alpha text", service="payment")]) == 0


def test_chroma_search_validates_arguments_and_handles_empty_inputs(tmp_path):
    encoder = StubEncoder()
    store = ChromaPassageStore(encoder, tmp_path / "chroma")

    with pytest.raises(ValueError, match="top_k must be positive"):
        store.search_many(["query"], 0)
    assert store.search_many(["query"], 3) == [[]]

    store.index_chunks([_chunk("a", "alpha text")])
    assert store.search_many(["  ", ""], 3) == [[], []]
    assert [candidate.chunk["chunk_id"] for candidate in store.search("alpha text", 3)] == ["a"]

    encoder.broken = True
    with pytest.raises(ValueError, match="one embedding per query"):
        store.search("alpha text")


@pytest.mark.parametrize("metadata", [{"metadata_json": "{broken"}, {"metadata_json": None}])
def test_restore_chunk_tolerates_corrupt_metadata_json(metadata):
    restored = ChromaPassageStore._restore_chunk("id", "text", metadata)

    assert restored["metadata"] == {}
    assert restored["chunk_id"] == "id"


def test_cosine_similarity_validates_dimensions_and_handles_zero_vectors():
    with pytest.raises(ValueError, match="same dimensions"):
        _cosine_similarity([1.0], [1.0, 2.0])
    assert _cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0
    assert math.isclose(_cosine_similarity([1.0, 0.0], [1.0, 0.0]), 1.0)


def test_fusion_requires_chunk_ids():
    with pytest.raises(ValueError, match="must include a chunk_id"):
        _fuse_rankings([[RetrievalCandidate({"text": "x"}, 0.1, 1, "bm25")]], 5, 60)


def test_hybrid_index_validates_embeddings_at_construction():
    class Wrong:
        def __init__(self, vectors):
            self.vectors = vectors

        def encode(self, texts):
            return self.vectors

    chunks = [_chunk("a", "alpha"), _chunk("b", "beta")]
    with pytest.raises(ValueError, match="one embedding per chunk"):
        HybridCandidateIndex(chunks, Wrong([[1.0]]))
    with pytest.raises(ValueError, match="consistent, non-zero dimension"):
        HybridCandidateIndex(chunks, Wrong([[1.0], [1.0, 2.0]]))
    with pytest.raises(ValueError, match="consistent, non-zero dimension"):
        HybridCandidateIndex(chunks, Wrong([[], []]))


def test_hybrid_index_search_validates_top_k_and_query_embeddings():
    encoder = StubEncoder()
    index = HybridCandidateIndex([_chunk("a", "alpha")], encoder)

    with pytest.raises(ValueError, match="top_k must be positive"):
        index.search_bm25("alpha", 0)
    with pytest.raises(ValueError, match="top_k must be positive"):
        index.search_semantic("alpha", 0)
    encoder.broken = True
    with pytest.raises(ValueError, match="one embedding for the query"):
        index.search_semantic("alpha", 1)


def test_hybrid_many_validates_settings_and_returns_nothing_for_blank_queries():
    index = HybridCandidateIndex([], StubEncoder())

    with pytest.raises(ValueError, match="top_k must be positive"):
        index.search_hybrid_many(["q"], top_k=0)
    with pytest.raises(ValueError, match="candidate_k must be positive"):
        index.search_hybrid_many(["q"], candidate_k=0)
    with pytest.raises(ValueError, match="rrf_k must be positive"):
        index.search_hybrid_many(["q"], rrf_k=0)
    assert index.search_hybrid_many(["", "   "]) == []


def test_search_reranked_validates_settings_and_returns_nothing_for_blank_queries():
    index = HybridCandidateIndex([], StubEncoder())

    with pytest.raises(ValueError, match="top_k must be positive"):
        index.search_reranked("q", top_k=0)
    with pytest.raises(ValueError, match="reranker_candidate_k must be positive"):
        index.search_reranked("q", reranker_candidate_k=0)
    assert index.search_reranked("   ") == []


def test_search_reranked_skips_blank_and_repeated_rewrites(monkeypatch):
    index = HybridCandidateIndex([], StubEncoder())
    searched = []

    class Rewriter:
        def rewrite(self, query, count):
            return ["  ", "PAYMENT FAILING", "new variant", "New Variant"]

    monkeypatch.setattr(
        index, "search_hybrid_many", lambda queries, **options: searched.append(list(queries)) or []
    )

    assert index.search_reranked("payment failing", query_rewriter=Rewriter(), query_rewrite_count=3) == []
    assert searched == [["payment failing", "new variant"]]
