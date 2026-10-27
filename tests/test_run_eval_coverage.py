import runpy
import sys

import pytest

from knowledge.evaluation import GoldenQuery
from knowledge.evaluation import run_eval
from knowledge.retrieval import runbooks_kb_tool, runtime
from knowledge.retrieval.contracts import RetrievalResponse, RetrievedPassage


def _response(doc_ids):
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
        )
        for rank, doc_id in enumerate(doc_ids, start=1)
    ]
    return RetrievalResponse(query="q", passages=passages)


QUERIES = [
    GoldenQuery(id="q1", query="one", relevant_docs=("a",), kind="symptom_only", split="dev"),
    GoldenQuery(id="q2", query="two", relevant_docs=("b",), kind="paraphrase", split="heldout"),
]


@pytest.fixture
def stubbed_main(monkeypatch):
    calls = {"tools": [], "services": []}

    def fake_create_tool(service=None):
        calls["tools"].append(service)
        return lambda text: _response(["a"] if text == "one" else ["x"])

    def fake_initialize(*, query_rewrite_count):
        calls["services"].append(query_rewrite_count)
        return f"service-{query_rewrite_count}"

    monkeypatch.setattr(run_eval, "load_golden_queries", lambda: list(QUERIES))
    monkeypatch.setattr(runbooks_kb_tool, "create_runbooks_kb_tool", fake_create_tool)
    monkeypatch.setattr(runtime, "initialize_retrieval_service", fake_initialize)
    return calls


def test_main_prints_a_single_report_with_the_configured_service(stubbed_main, capsys):
    assert run_eval.main(["--k", "3"]) == 0

    output = capsys.readouterr().out
    assert "Recall@3 evaluation (2 queries)" in output
    assert "OK   q1" in output
    assert "MISS q2" in output
    assert stubbed_main == {"tools": [None], "services": []}


def test_main_filters_queries_by_split(stubbed_main, capsys):
    assert run_eval.main(["--split", "heldout"]) == 0

    output = capsys.readouterr().out
    assert "(1 queries)" in output
    assert "q2" in output
    assert "OK   q1" not in output


def test_main_compares_unique_rewrite_counts(stubbed_main, capsys):
    assert run_eval.main(["--rewrite-counts", "0", "2", "0"]) == 0

    output = capsys.readouterr().out
    assert stubbed_main["services"] == [0, 2]
    assert stubbed_main["tools"] == ["service-0", "service-2"]
    assert "Recall@5 comparison" in output
    assert "== rewrite_count=0 ==" in output
    assert "== rewrite_count=2 ==" in output


@pytest.mark.filterwarnings("ignore::RuntimeWarning")
def test_module_entry_point_exits_with_main_status(stubbed_main, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["run_eval", "--k", "2"])

    with pytest.raises(SystemExit) as exit_info:
        runpy.run_module("knowledge.evaluation.run_eval", run_name="__main__")

    assert exit_info.value.code == 0
    assert "Recall@2 evaluation" in capsys.readouterr().out
