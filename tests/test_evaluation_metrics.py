import pytest

from knowledge.evaluation import GoldenQuery
from knowledge.evaluation.metrics import (
    aggregate_scores,
    score_query,
    unique_documents_in_rank_order,
)


def _query(*relevant_docs: str, query_id: str = "q") -> GoldenQuery:
    return GoldenQuery(
        id=query_id,
        query="text",
        relevant_docs=tuple(relevant_docs),
        kind="symptom_only",
    )


def test_unique_documents_keep_first_seen_order():
    assert unique_documents_in_rank_order(["a", "b", "a", "c", "b"]) == ["a", "b", "c"]


def test_full_recall_when_all_relevant_docs_in_top_k():
    score = score_query(_query("a", "b"), ["b", "x", "a"])

    assert score.recall == 1.0
    assert score.hit is True
    assert score.missed_docs == ()


def test_partial_recall_reports_missed_docs():
    score = score_query(_query("a", "b"), ["a", "x", "y"])

    assert score.recall == 0.5
    assert score.found_docs == ("a",)
    assert score.missed_docs == ("b",)


def test_zero_recall_and_no_hit_when_nothing_relevant_retrieved():
    score = score_query(_query("a"), ["x", "y"])

    assert score.recall == 0.0
    assert score.hit is False


def test_duplicate_passages_from_one_document_use_one_slot():
    # Five passages from "x" must not push "a" out of a top-5 document cutoff.
    ranked = ["x", "x", "x", "x", "x", "a"]

    assert score_query(_query("a"), ranked, k=5).recall == 1.0


def test_relevant_doc_beyond_cutoff_is_missed():
    ranked = ["d1", "d2", "d3", "d4", "d5", "a"]

    assert score_query(_query("a"), ranked, k=5).recall == 0.0
    assert score_query(_query("a"), ranked, k=6).recall == 1.0


def test_empty_ranking_scores_zero():
    assert score_query(_query("a"), []).recall == 0.0


def test_invalid_k_is_rejected():
    with pytest.raises(ValueError):
        score_query(_query("a"), ["a"], k=0)


def test_aggregate_is_macro_average():
    scores = [
        score_query(_query("a", "b", query_id="q1"), ["a", "b"]),
        score_query(_query("c", "d", query_id="q2"), ["c", "x"]),
        score_query(_query("e", query_id="q3"), ["x"]),
    ]

    aggregate = aggregate_scores(scores)

    assert aggregate.query_count == 3
    assert aggregate.mean_recall == pytest.approx((1.0 + 0.5 + 0.0) / 3)
    assert aggregate.hit_rate == pytest.approx(2 / 3)


def test_aggregate_rejects_empty_scores():
    with pytest.raises(ValueError):
        aggregate_scores([])
