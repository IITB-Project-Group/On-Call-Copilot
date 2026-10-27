from knowledge.evaluation import GoldenQuery
from knowledge.evaluation.run_eval import compare, evaluate, format_comparison, format_report
from knowledge.retrieval.contracts import RetrievalResponse, RetrievedPassage


def _response(query: str, doc_ids: list[str]) -> RetrievalResponse:
    passages = [
        RetrievedPassage(
            rank=rank,
            chunk_id=f"{doc_id}#{rank}",
            doc_id=doc_id,
            document_type="runbook",
            title=None,
            source=f"runbooks/{doc_id}.md",
            source_date=None,
            service=None,
            failure_family=None,
            text="",
            metadata={},
        )
        for rank, doc_id in enumerate(doc_ids, start=1)
    ]
    return RetrievalResponse(
        runbook_ids=list(dict.fromkeys(doc_ids)),
        postmortem_ids=[],
        query=query,
        passages=passages,
        runbooks=[],
        postmortem_passages=[],
    )


def _golden(query_id: str, *docs: str, kind="symptom_only", split="dev") -> GoldenQuery:
    return GoldenQuery(id=query_id, query=f"query {query_id}", relevant_docs=docs, kind=kind, split=split)


def test_evaluate_scores_each_query_from_fake_retrieval():
    rankings = {"query q1": ["a", "x"], "query q2": ["x", "y"]}
    queries = [_golden("q1", "a", "b"), _golden("q2", "c", kind="paraphrase", split="heldout")]

    result = evaluate(queries, lambda text: _response(text, rankings[text]))

    assert [score.recall for _, score in result.scored] == [0.5, 0.0]
    assert result.overall.mean_recall == 0.25
    assert result.overall.hit_rate == 0.5
    assert result.aggregate_by("kind")["paraphrase"].mean_recall == 0.0
    assert result.aggregate_by("split")["dev"].hit_rate == 1.0


def test_report_flags_misses_and_lists_missing_documents():
    queries = [_golden("q1", "a"), _golden("q2", "b", "c")]
    rankings = {"query q1": ["a"], "query q2": ["b"]}

    report = format_report(evaluate(queries, lambda text: _response(text, rankings[text])))

    assert "OK   q1" in report
    assert "PART q2" in report and "missed=c" in report
    assert "Recall@5=0.750" in report


def test_compare_runs_same_queries_per_configuration_and_renders_side_by_side():
    queries = [_golden("q1", "a", "b"), _golden("q2", "c")]
    baseline = {"query q1": ["a"], "query q2": ["x"]}
    multi = {"query q1": ["a", "b"], "query q2": ["c"]}

    results = compare(
        queries,
        {
            "rewrite_count=0": lambda text: _response(text, baseline[text]),
            "rewrite_count=2": lambda text: _response(text, multi[text]),
        },
    )
    report = format_comparison(results)

    assert results["rewrite_count=0"].overall.mean_recall == 0.25
    assert results["rewrite_count=2"].overall.mean_recall == 1.0
    assert "rewrite_count=0" in report and "rewrite_count=2" in report
    assert "0.250" in report and "1.000" in report
