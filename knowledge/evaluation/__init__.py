"""Offline retrieval-evaluation datasets, validation, and metrics."""

from .loader import GoldenQuery, QueryKind, QuerySplit, load_golden_queries
from .metrics import (
    AggregateScore,
    QueryScore,
    aggregate_scores,
    score_query,
    unique_documents_in_rank_order,
)

__all__ = [
    "AggregateScore",
    "GoldenQuery",
    "QueryKind",
    "QueryScore",
    "QuerySplit",
    "aggregate_scores",
    "load_golden_queries",
    "score_query",
    "unique_documents_in_rank_order",
]
