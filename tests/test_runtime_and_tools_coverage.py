import json
import runpy
import sys

import pytest

from knowledge.retrieval import build_index, runbooks_kb_tool, runtime
from knowledge.retrieval import index as retrieval_index
from knowledge.retrieval.build_index import index_knowledge_corpus, load_retrieval_documents
from knowledge.retrieval.contracts import RetrievalRequest, RetrievalResponse
from knowledge.retrieval.runbooks_kb_tool import RunbooksKBTool, create_runbooks_kb_tool
from knowledge.retrieval.runtime import initialize_local_retrieval_service, initialize_retrieval_service


class StubEncoder:
    model = "stub-model"

    def encode(self, texts):
        return [[float(len(text) % 7 + 1), 1.0] for text in texts]


def _corpus(tmp_path, runbook_body="# Steps\nRestart the payment service."):
    knowledge_dir = tmp_path / "knowledge"
    (knowledge_dir / "runbooks").mkdir(parents=True)
    (knowledge_dir / "postmortems").mkdir()
    (knowledge_dir / "policies").mkdir()
    (knowledge_dir / "runbooks" / "payment.md").write_text(
        f"---\nid: payment\ntitle: Payment\n---\n{runbook_body}\n", encoding="utf-8"
    )
    (knowledge_dir / "postmortems" / "pm.md").write_text(
        "---\nid: pm-1\n---\n# Incident\nCard processor outage.\n", encoding="utf-8"
    )
    (knowledge_dir / "policies" / "policy.md").write_text("# Policy\nNot retrievable.\n", encoding="utf-8")
    return knowledge_dir


def test_local_retrieval_service_searches_without_chroma(tmp_path):
    service = initialize_local_retrieval_service(knowledge_dir=_corpus(tmp_path))

    response = service.retrieve(RetrievalRequest(query="payment service"))

    assert response.runbook_ids == ["payment"]


def test_local_retrieval_service_rejects_an_empty_corpus(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    blank = tmp_path / "blank"
    (blank / "runbooks").mkdir(parents=True)
    (blank / "runbooks" / "empty.md").write_text("---\nid: empty\n---\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="No runbook or postmortem documents"):
        initialize_local_retrieval_service(knowledge_dir=empty)
    with pytest.raises(RuntimeError, match="produced no passage chunks"):
        initialize_local_retrieval_service(knowledge_dir=blank)


def test_load_retrieval_documents_only_returns_runbooks_and_postmortems(tmp_path):
    documents = load_retrieval_documents(_corpus(tmp_path))

    assert sorted(document.source for document in documents) == ["postmortems/pm.md", "runbooks/payment.md"]


def test_index_knowledge_corpus_rejects_an_empty_corpus(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()

    with pytest.raises(ValueError, match="No runbook or postmortem documents"):
        index_knowledge_corpus(empty, tmp_path / "chroma", encoder=StubEncoder())


def test_index_knowledge_corpus_rejects_documents_without_chunks(tmp_path):
    knowledge_dir = tmp_path / "knowledge"
    (knowledge_dir / "runbooks").mkdir(parents=True)
    (knowledge_dir / "runbooks" / "empty.md").write_text("---\nid: empty\n---\n", encoding="utf-8")

    with pytest.raises(ValueError, match="produced no passage chunks"):
        index_knowledge_corpus(knowledge_dir, tmp_path / "chroma", encoder=StubEncoder())


def test_index_knowledge_corpus_creates_the_default_encoder_when_none_is_given(tmp_path, monkeypatch):
    monkeypatch.setattr(build_index, "create_embedding_encoder", lambda: StubEncoder())

    summary = index_knowledge_corpus(_corpus(tmp_path), tmp_path / "chroma")

    assert summary.document_count == 2
    assert summary.collection_count == summary.chunk_count == 2


def test_main_indexes_and_prints_a_summary(tmp_path, capsys, monkeypatch):
    knowledge_dir = _corpus(tmp_path)
    persist = tmp_path / "chroma"
    monkeypatch.setattr(build_index, "create_embedding_encoder", lambda: StubEncoder())

    code = build_index.main(
        [
            "--knowledge-dir",
            str(knowledge_dir),
            "--persist-directory",
            str(persist),
            "--collection-name",
            "cli_passages",
            "--batch-size",
            "1",
        ]
    )

    output = capsys.readouterr().out
    assert code == 0
    assert "Source documents: 2" in output
    assert "Passage chunks: 2" in output
    assert "New or updated passages: 2" in output
    assert "Total passages in collection: 2" in output
    assert f"Persistent store: {persist}" in output


def test_main_prints_provider_failures_and_exits(capsys, monkeypatch):
    def fail(**_kwargs):
        raise build_index.OpenRouterError(
            "OpenRouter embeddings request for model baai/bge-m3 failed (HTTP 404): "
            "Model blocked by guardrail"
        )

    monkeypatch.setattr(build_index, "index_knowledge_corpus", fail)

    code = build_index.main([])

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert "Model blocked by guardrail" in captured.err
    assert "Traceback" not in captured.err


@pytest.mark.filterwarnings("ignore::RuntimeWarning")
def test_build_index_module_entry_point_exits_with_main_status(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(retrieval_index, "create_embedding_encoder", lambda: StubEncoder())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_index",
            "--knowledge-dir",
            str(_corpus(tmp_path)),
            "--persist-directory",
            str(tmp_path / "chroma"),
        ],
    )

    with pytest.raises(SystemExit) as exit_info:
        runpy.run_module("knowledge.retrieval.build_index", run_name="__main__")

    assert exit_info.value.code == 0
    assert "Source documents: 2" in capsys.readouterr().out


def test_runtime_rejects_missing_documents_and_chunks(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(RuntimeError, match="No runbook or postmortem documents"):
        initialize_retrieval_service(
            knowledge_dir=empty, persist_directory=tmp_path / "c1", encoder=StubEncoder()
        )

    knowledge_dir = tmp_path / "blank"
    (knowledge_dir / "runbooks").mkdir(parents=True)
    (knowledge_dir / "runbooks" / "blank.md").write_text("---\nid: blank\n---\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="produced no passage chunks"):
        initialize_retrieval_service(
            knowledge_dir=knowledge_dir, persist_directory=tmp_path / "c2", encoder=StubEncoder()
        )


def test_runtime_requires_a_prebuilt_index(tmp_path):
    with pytest.raises(RuntimeError, match="index is empty"):
        initialize_retrieval_service(
            knowledge_dir=_corpus(tmp_path), persist_directory=tmp_path / "chroma", encoder=StubEncoder()
        )


def test_runtime_builds_a_service_over_the_existing_index(tmp_path, monkeypatch):
    knowledge_dir = _corpus(tmp_path)
    persist = tmp_path / "chroma"
    index_knowledge_corpus(knowledge_dir, persist, encoder=StubEncoder())
    monkeypatch.setattr(runtime, "create_embedding_encoder", lambda: StubEncoder())

    service = initialize_retrieval_service(knowledge_dir=knowledge_dir, persist_directory=persist)

    assert type(service._search_index).__name__ == "HybridCandidateIndex"
    assert service._documents_by_source.keys() == {"runbooks/payment.md", "postmortems/pm.md"}


def test_runtime_can_pin_the_query_rewrite_count(tmp_path, monkeypatch):
    knowledge_dir = _corpus(tmp_path)
    persist = tmp_path / "chroma"
    index_knowledge_corpus(knowledge_dir, persist, encoder=StubEncoder())

    service = initialize_retrieval_service(
        knowledge_dir=knowledge_dir,
        persist_directory=persist,
        encoder=StubEncoder(),
        query_rewrite_count=3,
    )

    override = service._search_index
    seen = {}

    def fake_search_reranked(query, **options):
        seen.update(query=query, **options)
        return ["result"]

    monkeypatch.setattr(override._index, "search_reranked", fake_search_reranked)
    assert override.search_reranked("payment") == ["result"]
    assert seen == {"query": "payment", "query_rewrite_count": 3}


class StubService:
    def retrieve(self, request):
        assert isinstance(request, RetrievalRequest)
        return RetrievalResponse(query=request.query, runbook_ids=["payment"])


def test_tool_forwards_queries_to_the_service():
    assert RunbooksKBTool(StubService())("payment down").runbook_ids == ["payment"]


def test_create_tool_uses_a_supplied_service_or_initializes_one(monkeypatch):
    supplied = StubService()
    assert create_runbooks_kb_tool(supplied)._retrieval_service is supplied

    monkeypatch.setattr(runbooks_kb_tool, "initialize_retrieval_service", lambda: supplied)
    assert create_runbooks_kb_tool()._retrieval_service is supplied


def test_tool_main_prints_the_response_as_json(monkeypatch, capsys):
    monkeypatch.setattr(runbooks_kb_tool, "initialize_retrieval_service", lambda: StubService())

    assert runbooks_kb_tool.main(["--query", "payment down"]) == 0

    printed = json.loads(capsys.readouterr().out)
    assert printed["query"] == "payment down"
    assert printed["runbook_ids"] == ["payment"]


@pytest.mark.filterwarnings("ignore::RuntimeWarning")
def test_tool_module_entry_point_exits_with_main_status(monkeypatch, capsys):
    monkeypatch.setattr(runtime, "initialize_retrieval_service", lambda: StubService())
    monkeypatch.setattr(sys, "argv", ["runbooks_kb_tool", "--query", "payment down"])

    with pytest.raises(SystemExit) as exit_info:
        runpy.run_module("knowledge.retrieval.runbooks_kb_tool", run_name="__main__")

    assert exit_info.value.code == 0
    assert json.loads(capsys.readouterr().out)["query"] == "payment down"
