"""Offline document-level retrieval metrics (Recall@k, Hit@k)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .loader import GoldenQuery


@dataclass(frozen=True)
class QueryScore:
    """Per-query result at a fixed cutoff."""

    query_id: str
    retrieved_docs: tuple[str, ...]
    found_docs: tuple[str, ...]
    missed_docs: tuple[str, ...]
    recall: float
    hit: bool


@dataclass(frozen=True)
class AggregateScore:
    """Macro-averaged scores over a set of queries."""

    k: int
    query_count: int
    mean_recall: float
    hit_rate: float


def unique_documents_in_rank_order(doc_ids: Iterable[str]) -> list[str]:
    """Collapse ranked passage doc IDs to unique documents, keeping first-seen order."""
    return list(dict.fromkeys(doc_ids))


def score_query(
    query: GoldenQuery,
    ranked_passage_doc_ids: Sequence[str],
    k: int = 5,
) -> QueryScore:
    """Score one query on the top-k unique documents of a ranked passage list."""
    if k < 1:
        raise ValueError("k must be at least 1")

    top_docs = unique_documents_in_rank_order(ranked_passage_doc_ids)[:k]
    relevant = set(query.relevant_docs)
    found = tuple(doc for doc in query.relevant_docs if doc in top_docs)
    missed = tuple(doc for doc in query.relevant_docs if doc not in top_docs)

    return QueryScore(
        query_id=query.id,
        retrieved_docs=tuple(top_docs),
        found_docs=found,
        missed_docs=missed,
        recall=len(found) / len(relevant),
        hit=bool(found),
    )


def aggregate_scores(scores: Sequence[QueryScore], k: int = 5) -> AggregateScore:
    """Macro-average Recall@k and Hit@k across queries."""
    if not scores:
        raise ValueError("scores must not be empty")

    return AggregateScore(
        k=k,
        query_count=len(scores),
        mean_recall=sum(score.recall for score in scores) / len(scores),
        hit_rate=sum(score.hit for score in scores) / len(scores),
    )
