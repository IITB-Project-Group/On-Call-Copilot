"""Lexical and semantic candidate retrieval for knowledge passages."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv
from rank_bm25 import BM25Okapi

from .config_loader import load_retrieval_config
from .query_rewriter import OpenRouterQueryRewriter, QueryRewriter

_DOTENV_PATH = Path(__file__).resolve().parents[2] / ".env"
_LOGGER = logging.getLogger(__name__)


class OpenRouterError(RuntimeError):
    """OpenRouter rejected a request or could not be reached."""


class EmbeddingEncoder(Protocol):
    """Encode input text as dense semantic vectors."""

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one embedding vector for each input text."""


def _e5_prefixes(model_name: str) -> tuple[str, str]:
    """Return query and passage prefixes for E5 models, or empty prefixes otherwise."""
    normalized_name = model_name.lower()
    if "multilingual-e5" in normalized_name or normalized_name.startswith("intfloat/e5-"):
        return "query: ", "passage: "
    return "", ""


def _with_prefix(texts: Sequence[str], prefix: str) -> list[str]:
    """Apply a model-specific instruction prefix to a batch of texts."""
    return [f"{prefix}{text}" for text in texts]


def _openrouter_error_detail(error: HTTPError) -> str:
    """Pull a single-line provider message out of an HTTP error body."""
    raw = error.read().decode("utf-8", errors="replace").strip()
    message = ""
    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        parsed = {}
    if isinstance(parsed, dict):
        nested = parsed.get("error")
        if isinstance(nested, dict) and isinstance(nested.get("message"), str):
            message = nested["message"].strip()
    if not message:
        message = " ".join(raw.split())
    if not message:
        reason = error.reason
        message = reason.strip() if isinstance(reason, str) else ""
    return message[:500] or "the provider returned an empty error"


def _call_openrouter(request: Request, timeout: float, *, what: str) -> Any:
    """Send one OpenRouter request and raise a readable error when it fails."""
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = _openrouter_error_detail(error)
        raise OpenRouterError(f"{what} failed (HTTP {error.code}): {detail}") from error
    except URLError as error:
        raise OpenRouterError(f"{what} failed: {error.reason}") from error
    except TimeoutError as error:
        raise OpenRouterError(f"{what} timed out after {timeout:g} seconds") from error
    except json.JSONDecodeError as error:
        raise OpenRouterError(f"{what} returned a response that is not JSON") from error


class OpenAICompatibleEmbeddingEncoder:
    """Call an OpenAI-compatible embeddings endpoint such as OpenRouter."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        """Read embedding configuration from arguments or environment variables."""
        load_dotenv(_DOTENV_PATH, override=False)
        self.api_key = api_key or os.environ.get("EMBEDDING_API_KEY")
        self.model = model or os.environ.get("EMBEDDING_MODEL")
        self.base_url = (
            base_url or os.environ.get("EMBEDDING_BASE_URL", "https://openrouter.ai/api/v1")
        ).rstrip("/")
        self.timeout_seconds = timeout_seconds
        if not self.api_key:
            raise ValueError("Set EMBEDDING_API_KEY or pass api_key")
        if not self.model:
            raise ValueError("Set EMBEDDING_MODEL or pass model")
        self.query_prefix, self.document_prefix = _e5_prefixes(self.model)

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        """Request embeddings and return vectors in input order."""
        if not texts:
            return []

        payload = json.dumps({"model": self.model, "input": list(texts)}).encode("utf-8")
        request = Request(
            f"{self.base_url}/embeddings",
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        response_body = _call_openrouter(
            request,
            self.timeout_seconds,
            what=f"OpenRouter embeddings request for model {self.model}",
        )
        data = response_body.get("data")
        if not isinstance(data, list) or len(data) != len(texts):
            raise ValueError("Embedding response must contain one vector per input text")

        ordered_data = sorted(data, key=lambda item: item.get("index", -1))
        vectors = [item.get("embedding") for item in ordered_data]
        if any(not isinstance(vector, list) or not vector for vector in vectors):
            raise ValueError("Embedding response contains an invalid vector")
        return [[float(value) for value in vector] for vector in vectors]

    def encode_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Encode passages, applying an E5 passage prefix when required."""
        return self.encode(_with_prefix(texts, self.document_prefix))

    def encode_queries(self, texts: Sequence[str]) -> list[list[float]]:
        """Encode queries, applying an E5 query prefix when required."""
        return self.encode(_with_prefix(texts, self.query_prefix))


class HashedTokenEncoder:
    """Build deterministic local embeddings from token hashes.

    This encoder does not call OpenRouter. It keeps indexing and semantic search
    available when an API key is limited to chat models and cannot call an
    embedding model. Rankings still include BM25, which carries most of the
    match for this runbook corpus.
    """

    def __init__(self, *, model: str = "local/hashed-tokens", dimensions: int = 256) -> None:
        """Select the stored model name and the fixed hash dimension."""
        if dimensions <= 0:
            raise ValueError("dimensions must be positive")
        self.model = model
        self.dimensions = dimensions

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one L2-normalized hashed vector per text."""
        return [_hash_embedding(text, self.dimensions) for text in texts]

    def encode_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Encode passages with the same local hash used for queries."""
        return self.encode(texts)

    def encode_queries(self, texts: Sequence[str]) -> list[list[float]]:
        """Encode queries with the same local hash used for passages."""
        return self.encode(texts)


def _hash_embedding(text: str, dimensions: int) -> list[float]:
    """Hash tokens into a fixed vector so cosine similarity reflects term overlap."""
    tokens = _tokenize(text)
    if not tokens:
        return [1.0, *([0.0] * (dimensions - 1))]

    vector = [0.0] * dimensions
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:4], "little") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[bucket] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        vector[0] = 1.0
        return vector
    return [value / norm for value in vector]


def create_embedding_encoder(
    provider: str | None = None,
    *,
    model_name: str | None = None,
) -> EmbeddingEncoder:
    """Create an OpenRouter encoder, or a local hashed encoder when requested."""
    load_dotenv(_DOTENV_PATH, override=False)
    selected_provider = (provider or os.environ.get("EMBEDDING_PROVIDER", "openrouter")).lower()
    if selected_provider == "local":
        return HashedTokenEncoder(model=model_name or "local/hashed-tokens")
    if selected_provider != "openrouter":
        raise ValueError("EMBEDDING_PROVIDER must be 'openrouter' or 'local'")
    selected_model = model_name or os.environ.get("EMBEDDING_MODEL")
    return OpenAICompatibleEmbeddingEncoder(model=selected_model)


@dataclass(frozen=True)
class RetrievalCandidate:
    """A ranked passage returned by one retrieval channel."""

    chunk: dict[str, Any]
    score: float
    rank: int
    channel: str


class CandidateReranker(Protocol):
    """Rerank retrieved passages against their original query."""

    def rerank(
        self,
        query: str,
        candidates: Sequence[RetrievalCandidate],
        top_n: int,
    ) -> list[RetrievalCandidate]:
        """Return up to top_n candidates in relevance order."""


class OpenRouterReranker:
    """Rerank passage candidates through OpenRouter's dedicated rerank API."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        """Load OpenRouter credentials and the configured reranker model."""
        load_dotenv(_DOTENV_PATH, override=False)
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY") or os.environ.get("EMBEDDING_API_KEY")
        self.model = model or os.environ.get("RERANKER_MODEL")
        self.base_url = (
            base_url
            or os.environ.get("RERANK_BASE_URL")
            or os.environ.get("EMBEDDING_BASE_URL", "https://openrouter.ai/api/v1")
        ).rstrip("/")
        self.timeout_seconds = timeout_seconds
        if not self.api_key:
            raise ValueError("Set OPENROUTER_API_KEY or EMBEDDING_API_KEY")
        if not self.model:
            raise ValueError("Set RERANKER_MODEL or pass model")

    def rerank(
        self,
        query: str,
        candidates: Sequence[RetrievalCandidate],
        top_n: int,
    ) -> list[RetrievalCandidate]:
        """Send passage text to OpenRouter and map ranked indexes back to chunks."""
        if top_n <= 0:
            raise ValueError("top_n must be positive")
        if not query.strip() or not candidates:
            return []

        payload = json.dumps(
            {
                "model": self.model,
                "query": query,
                "documents": [candidate.chunk.get("text", "") for candidate in candidates],
                "top_n": min(top_n, len(candidates)),
            }
        ).encode("utf-8")
        request = Request(
            f"{self.base_url}/rerank",
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        response_body = _call_openrouter(
            request,
            self.timeout_seconds,
            what=f"OpenRouter rerank request for model {self.model}",
        )
        results = response_body.get("results")
        if not isinstance(results, list):
            raise ValueError("Rerank response must contain a results list")

        ranked: list[tuple[float, int, int]] = []
        seen_indices: set[int] = set()
        for response_order, result in enumerate(results):
            if not isinstance(result, dict):
                raise ValueError("Rerank response contains an invalid result")
            candidate_index = result.get("index")
            relevance_score = result.get("relevance_score")
            if (
                isinstance(candidate_index, bool)
                or not isinstance(candidate_index, int)
                or not 0 <= candidate_index < len(candidates)
            ):
                raise ValueError("Rerank response contains an invalid candidate index")
            if candidate_index in seen_indices:
                continue
            if isinstance(relevance_score, bool) or not isinstance(relevance_score, (int, float)):
                raise ValueError("Rerank response contains an invalid relevance score")
            score = float(relevance_score)
            if not math.isfinite(score):
                raise ValueError("Rerank response contains a non-finite relevance score")
            seen_indices.add(candidate_index)
            ranked.append((score, response_order, candidate_index))

        ranked.sort(key=lambda item: (-item[0], item[1]))
        return [
            RetrievalCandidate(
                chunk=candidates[candidate_index].chunk,
                score=score,
                rank=rank,
                channel="reranker",
            )
            for rank, (score, _, candidate_index) in enumerate(ranked[:top_n], start=1)
        ]


class ChromaPassageStore:
    """Persist passage text, embeddings, and citation metadata in Chroma."""

    def __init__(
        self,
        encoder: EmbeddingEncoder,
        persist_directory: str | Path | None = None,
        collection_name: str = "knowledge_passages",
        batch_size: int = 32,
    ) -> None:
        """Open a persistent Chroma collection for the configured embedding model."""
        try:
            import chromadb
        except ImportError as error:
            raise ImportError("Install chromadb from requirements.txt to use persistent storage") from error

        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        self.encoder = encoder
        self.batch_size = batch_size
        self.persist_directory = Path(persist_directory or (_DOTENV_PATH.parent / ".chroma"))
        self.persist_directory.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(self.persist_directory))
        embedding_model = getattr(encoder, "model", None)
        collection_metadata: dict[str, str] = {"hnsw:space": "cosine"}
        if embedding_model:
            collection_metadata["embedding_model"] = embedding_model
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata=collection_metadata,
        )
        stored_model = (self._collection.metadata or {}).get("embedding_model")
        if embedding_model and stored_model and stored_model != embedding_model:
            raise ValueError(
                f"Chroma collection uses embedding model {stored_model!r}, "
                f"but the configured model is {embedding_model!r}"
            )

    @property
    def count(self) -> int:
        """Return the number of passages currently persisted in the collection."""
        return self._collection.count()

    def index_chunks(self, chunks: Sequence[dict[str, Any]]) -> int:
        """Upsert changed passages and return the number of modified records."""
        encode_documents = getattr(self.encoder, "encode_documents", self.encoder.encode)
        modified_count = 0
        for offset in range(0, len(chunks), self.batch_size):
            batch = chunks[offset : offset + self.batch_size]
            ids = [str(chunk.get("chunk_id", "")) for chunk in batch]
            if any(not chunk_id for chunk_id in ids):
                raise ValueError("Every indexed passage must have a chunk_id")
            if len(set(ids)) != len(ids):
                raise ValueError("Passage chunk_id values must be unique")
            texts = [str(chunk.get("text", "")) for chunk in batch]
            metadata = [self._serialize_metadata(chunk) for chunk in batch]
            existing = self._collection.get(
                ids=ids,
                include=["documents", "metadatas"],
            )
            existing_by_id = {
                chunk_id: (document, stored_metadata)
                for chunk_id, document, stored_metadata in zip(
                    existing["ids"], existing["documents"], existing["metadatas"]
                )
            }
            changed_chunks: list[tuple[str, str, dict[str, str | int | float | bool]]] = []
            for chunk_id, text, chunk_metadata in zip(ids, texts, metadata):
                stored = existing_by_id.get(chunk_id)
                if stored is not None and stored[0] == text:
                    if stored[1] != chunk_metadata:
                        self._collection.update(ids=[chunk_id], metadatas=[chunk_metadata])
                        modified_count += 1
                    continue
                changed_chunks.append((chunk_id, text, chunk_metadata))

            if not changed_chunks:
                continue
            embeddings = encode_documents([text for _, text, _ in changed_chunks])
            if len(embeddings) != len(changed_chunks):
                raise ValueError("Encoder must return one embedding per passage")
            self._collection.upsert(
                ids=[chunk_id for chunk_id, _, _ in changed_chunks],
                embeddings=embeddings,
                documents=[text for _, text, _ in changed_chunks],
                metadatas=[chunk_metadata for _, _, chunk_metadata in changed_chunks],
            )
            modified_count += len(changed_chunks)
        return modified_count

    def sync_chunks(self, chunks: Sequence[dict[str, Any]]) -> int:
        """Upsert current passages and remove stored IDs absent from the corpus."""
        indexed_count = self.index_chunks(chunks)
        desired_ids = {str(chunk.get("chunk_id", "")) for chunk in chunks}
        stored_ids = set(self._collection.get(include=[])["ids"])
        stale_ids = sorted(stored_ids - desired_ids)
        if stale_ids:
            self._collection.delete(ids=stale_ids)
        return indexed_count

    def search(self, query: str, top_k: int = 10) -> list[RetrievalCandidate]:
        """Search persisted passages by cosine distance and restore their metadata."""
        return self.search_many([query], top_k)[0]

    def search_many(
        self,
        queries: Sequence[str],
        top_k: int = 10,
    ) -> list[list[RetrievalCandidate]]:
        """Batch query embeddings and return a separate semantic ranking per query."""
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        query_results: list[list[RetrievalCandidate]] = [[] for _ in queries]
        active_queries = [(index, query.strip()) for index, query in enumerate(queries) if query.strip()]
        if not active_queries or self._collection.count() == 0:
            return query_results

        encode_queries = getattr(self.encoder, "encode_queries", self.encoder.encode)
        query_embeddings = encode_queries([query for _, query in active_queries])
        if len(query_embeddings) != len(active_queries):
            raise ValueError("Encoder must return one embedding per query")
        results = self._collection.query(
            query_embeddings=query_embeddings,
            n_results=min(top_k, self._collection.count()),
            include=["documents", "metadatas", "distances"],
        )
        for result_index, (original_index, _) in enumerate(active_queries):
            result_ids = results["ids"][result_index]
            documents = results["documents"][result_index]
            metadatas = results["metadatas"][result_index]
            distances = results["distances"][result_index]
            query_results[original_index] = [
                RetrievalCandidate(
                    chunk=self._restore_chunk(chunk_id, document, metadata),
                    score=1.0 - float(distance),
                    rank=rank,
                    channel="semantic",
                )
                for rank, (chunk_id, document, metadata, distance) in enumerate(
                    zip(result_ids, documents, metadatas, distances),
                    start=1,
                )
            ]
        return query_results

    @staticmethod
    def _serialize_metadata(chunk: dict[str, Any]) -> dict[str, str | int | float | bool]:
        """Convert passage metadata into Chroma-supported scalar fields."""
        result: dict[str, str | int | float | bool] = {}
        for field in ("doc_id", "source", "source_date", "service", "failure_family", "title"):
            value = chunk.get(field)
            if value is not None:
                result[field] = value if isinstance(value, (str, int, float, bool)) else str(value)
        extra_metadata = chunk.get("metadata", {})
        result["metadata_json"] = json.dumps(
            extra_metadata if isinstance(extra_metadata, dict) else {},
            default=str,
        )
        return result

    @staticmethod
    def _restore_chunk(chunk_id: str, text: str, metadata: dict[str, Any]) -> dict[str, Any]:
        """Reconstruct the original passage shape from Chroma results."""
        try:
            extra_metadata = json.loads(metadata.get("metadata_json", "{}"))
        except (TypeError, json.JSONDecodeError):
            extra_metadata = {}
        return {
            "chunk_id": chunk_id,
            "doc_id": metadata.get("doc_id"),
            "source": metadata.get("source"),
            "source_date": metadata.get("source_date"),
            "service": metadata.get("service"),
            "failure_family": metadata.get("failure_family"),
            "title": metadata.get("title"),
            "text": text,
            "metadata": extra_metadata,
        }


def _tokenize(text: str) -> list[str]:
    """Normalize text into terms for BM25 indexing and query matching."""
    return re.findall(r"\b\w+\b", text.lower())


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    """Compute cosine similarity for two equally sized embedding vectors."""
    if len(left) != len(right):
        raise ValueError("Query and passage embeddings must have the same dimensions")
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)


def _fuse_rankings(
    rankings: Sequence[Sequence[RetrievalCandidate]],
    top_k: int,
    rrf_k: int,
) -> list[RetrievalCandidate]:
    """Merge ranked lists with RRF and return unique chunks in fused order."""
    fused_scores: dict[str, float] = {}
    fused_chunks: dict[str, dict[str, Any]] = {}
    first_seen: dict[str, int] = {}

    for ranking in rankings:
        for candidate in ranking:
            chunk_id = str(candidate.chunk.get("chunk_id", ""))
            if not chunk_id:
                raise ValueError("RRF candidates must include a chunk_id")
            if chunk_id not in fused_scores:
                fused_scores[chunk_id] = 0.0
                fused_chunks[chunk_id] = candidate.chunk
                first_seen[chunk_id] = len(first_seen)
            fused_scores[chunk_id] += 1.0 / (rrf_k + candidate.rank)

    ranked_ids = sorted(
        fused_scores,
        key=lambda chunk_id: (-fused_scores[chunk_id], first_seen[chunk_id], chunk_id),
    )
    return [
        RetrievalCandidate(
            chunk=fused_chunks[chunk_id],
            score=fused_scores[chunk_id],
            rank=rank,
            channel="hybrid",
        )
        for rank, chunk_id in enumerate(ranked_ids[:top_k], start=1)
    ]


class HybridCandidateIndex:
    """Build independent BM25 and embedding rankings over passage chunks."""

    def __init__(
        self,
        chunks: Sequence[dict[str, Any]],
        encoder: EmbeddingEncoder,
        vector_store: ChromaPassageStore | None = None,
    ) -> None:
        """Index lexical terms and optionally use persistent Chroma for vectors."""
        self.chunks = list(chunks)
        self.encoder = encoder
        self.vector_store = vector_store
        self._tokenized_chunks = [_tokenize(str(chunk.get("text", ""))) for chunk in self.chunks]
        self._bm25 = BM25Okapi(self._tokenized_chunks) if any(self._tokenized_chunks) else None
        if vector_store is None:
            document_texts = [str(chunk.get("text", "")) for chunk in self.chunks]
            encode_documents = getattr(encoder, "encode_documents", encoder.encode)
            self._embeddings = encode_documents(document_texts)
        else:
            self._embeddings = []

        if vector_store is None and len(self._embeddings) != len(self.chunks):
            raise ValueError("Encoder must return one embedding per chunk")
        dimensions = {len(vector) for vector in self._embeddings}
        if vector_store is None and (
            len(dimensions) > 1 or (self._embeddings and not next(iter(dimensions)))
        ):
            raise ValueError("Passage embeddings must have a consistent, non-zero dimension")

    def search_bm25(self, query: str, top_k: int | None = None) -> list[RetrievalCandidate]:
        """Return lexical candidates ranked by BM25 relevance."""
        top_k = load_retrieval_config().top_k if top_k is None else top_k
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        query_terms = _tokenize(query)
        if not query_terms or self._bm25 is None:
            return []

        scores = self._bm25.get_scores(query_terms)
        query_term_set = set(query_terms)
        matching_indices = [
            index for index, terms in enumerate(self._tokenized_chunks) if query_term_set.intersection(terms)
        ]
        ranked_indices = sorted(matching_indices, key=lambda index: scores[index], reverse=True)
        return [
            RetrievalCandidate(self.chunks[index], float(scores[index]), rank, "bm25")
            for rank, index in enumerate(ranked_indices[:top_k], start=1)
        ]

    def search_semantic(self, query: str, top_k: int | None = None) -> list[RetrievalCandidate]:
        """Return semantic candidates ranked by cosine similarity."""
        top_k = load_retrieval_config().top_k if top_k is None else top_k
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        if self.vector_store is not None:
            return self.vector_store.search(query, top_k)
        if not self.chunks or not query.strip():
            return []

        encode_queries = getattr(self.encoder, "encode_queries", self.encoder.encode)
        query_embeddings = encode_queries([query])
        if len(query_embeddings) != 1:
            raise ValueError("Encoder must return one embedding for the query")
        query_embedding = query_embeddings[0]
        scored = [
            (_cosine_similarity(query_embedding, embedding), index)
            for index, embedding in enumerate(self._embeddings)
        ]
        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            RetrievalCandidate(self.chunks[index], score, rank, "semantic")
            for rank, (score, index) in enumerate(scored[:top_k], start=1)
        ]

    def search_hybrid(
        self,
        query: str,
        top_k: int | None = None,
        candidate_k: int | None = None,
        rrf_k: int | None = None,
    ) -> list[RetrievalCandidate]:
        """Fuse BM25 and semantic rankings using reciprocal rank fusion."""
        return self.search_hybrid_many(
            [query],
            top_k=top_k,
            candidate_k=candidate_k,
            rrf_k=rrf_k,
        )

    def search_hybrid_many(
        self,
        queries: Sequence[str],
        top_k: int | None = None,
        candidate_k: int | None = None,
        rrf_k: int | None = None,
    ) -> list[RetrievalCandidate]:
        """Retrieve each query through BM25 and Chroma, then fuse all rankings."""
        config = load_retrieval_config()
        top_k = config.top_k if top_k is None else top_k
        candidate_k = config.candidate_k if candidate_k is None else candidate_k
        rrf_k = config.rrf_k if rrf_k is None else rrf_k
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        if candidate_k <= 0:
            raise ValueError("candidate_k must be positive")
        if rrf_k <= 0:
            raise ValueError("rrf_k must be positive")

        unique_queries = list(dict.fromkeys(query.strip() for query in queries if query.strip()))
        if not unique_queries:
            return []

        lexical_rankings = [self.search_bm25(query, candidate_k) for query in unique_queries]
        if self.vector_store is not None:
            semantic_rankings = self.vector_store.search_many(unique_queries, candidate_k)
        else:
            semantic_rankings = [self.search_semantic(query, candidate_k) for query in unique_queries]

        all_rankings: list[Sequence[RetrievalCandidate]] = []
        for lexical_ranking, semantic_ranking in zip(lexical_rankings, semantic_rankings):
            all_rankings.extend((lexical_ranking, semantic_ranking))
        return _fuse_rankings(all_rankings, top_k, rrf_k)

    def search_reranked(
        self,
        query: str,
        top_k: int | None = None,
        candidate_k: int | None = None,
        rrf_k: int | None = None,
        reranker_candidate_k: int | None = None,
        reranker: CandidateReranker | None = None,
        query_rewriter: QueryRewriter | None = None,
        query_rewrite_count: int | None = None,
    ) -> list[RetrievalCandidate]:
        """RRF-fuse a broad pool, rerank it through OpenRouter, then return top_k."""
        config = load_retrieval_config()
        rewrite_count = config.query_rewrite_count if query_rewrite_count is None else query_rewrite_count
        if rewrite_count < 0:
            raise ValueError("query_rewrite_count must be non-negative")
        original_query = query.strip()
        final_top_k = config.top_k if top_k is None else top_k
        rerank_pool_size = (
            config.reranker_candidate_k if reranker_candidate_k is None else reranker_candidate_k
        )
        if final_top_k <= 0:
            raise ValueError("top_k must be positive")
        if rerank_pool_size <= 0:
            raise ValueError("reranker_candidate_k must be positive")
        if not original_query:
            return []

        queries = [original_query]
        if rewrite_count > 0:
            try:
                selected_rewriter = query_rewriter or OpenRouterQueryRewriter()
                rewrites = selected_rewriter.rewrite(
                    original_query,
                    rewrite_count,
                )
            except Exception as error:
                _LOGGER.warning(
                    "Query rewriting failed; continuing with the original query (%s)",
                    type(error).__name__,
                )
                rewrites = []

            seen_queries = {original_query.casefold()}
            for rewrite in rewrites:
                normalized_rewrite = rewrite.strip()
                if normalized_rewrite and normalized_rewrite.casefold() not in seen_queries:
                    queries.append(normalized_rewrite)
                    seen_queries.add(normalized_rewrite.casefold())

        fused_candidates = self.search_hybrid_many(
            queries,
            top_k=rerank_pool_size,
            candidate_k=candidate_k,
            rrf_k=rrf_k,
        )
        if not fused_candidates:
            return []

        try:
            selected_reranker = reranker or OpenRouterReranker()
            return selected_reranker.rerank(original_query, fused_candidates, top_n=final_top_k)
        except OpenRouterError as error:
            _LOGGER.warning(
                "Reranking failed; returning the fused BM25 and semantic ranking (%s)",
                type(error).__name__,
            )
            return [
                RetrievalCandidate(candidate.chunk, candidate.score, rank, candidate.channel)
                for rank, candidate in enumerate(fused_candidates[:final_top_k], start=1)
            ]
