"""Public retrieval API for the knowledge layer.

The retrieval package is intentionally small and explicit: it exposes the
incident request/response contract and the lesson policy gate that decides when
past experience can safely apply to a new alert. This keeps the higher-level
agent logic simple and ensures memory usage follows the project guardrails.
"""

from .chunker import chunk_markdown_documents
from .config_loader import RetrievalConfig, load_retrieval_config
from .contracts import (
    LessonCandidate,
    RetrievalRequest,
    RetrievalResponse,
    RetrievedPassage,
    RetrievedRunbook,
    check_lesson_policy,
)
from .ingest import IngestedDocument, load_markdown_documents
from .service import RetrievalService
from .query_rewriter import OpenRouterQueryRewriter, QueryRewriter
from .index import (
    CandidateReranker,
    ChromaPassageStore,
    EmbeddingEncoder,
    HashedTokenEncoder,
    HybridCandidateIndex,
    OpenAICompatibleEmbeddingEncoder,
    OpenRouterError,
    OpenRouterReranker,
    RetrievalCandidate,
    create_embedding_encoder,
)

__all__ = [
    "LessonCandidate",
    "RetrievalRequest",
    "RetrievalResponse",
    "RetrievedPassage",
    "RetrievedRunbook",
    "check_lesson_policy",
    "IngestedDocument",
    "load_markdown_documents",
    "chunk_markdown_documents",
    "RetrievalConfig",
    "load_retrieval_config",
    "EmbeddingEncoder",
    "CandidateReranker",
    "ChromaPassageStore",
    "HashedTokenEncoder",
    "HybridCandidateIndex",
    "OpenAICompatibleEmbeddingEncoder",
    "OpenRouterError",
    "OpenRouterReranker",
    "RetrievalCandidate",
    "create_embedding_encoder",
    "RetrievalService",
    "QueryRewriter",
    "OpenRouterQueryRewriter",
]
