import pytest

from knowledge.retrieval.contracts import RetrievalRequest
from knowledge.retrieval.index import RetrievalCandidate
from knowledge.retrieval.ingest import IngestedDocument
from knowledge.retrieval.service import RetrievalService


class FakeIndex:
    def __init__(self, chunks):
        self.chunks = chunks
        self.queries = []

    def search_reranked(self, query):
        self.queries.append(query)
        return [
            RetrievalCandidate(chunk=chunk, score=1.0, rank=rank, channel="reranker")
            for rank, chunk in enumerate(self.chunks, start=1)
        ]


def _runbook(doc_id="rb", source="runbooks/rb.md"):
    return IngestedDocument(
        doc_id=doc_id,
        source=source,
        source_date="2026-01-01",
        service="payment",
        failure_family="config",
        title="Runbook title",
        body="Full runbook body",
        metadata={"owner": "sre"},
    )


def test_blank_queries_are_rejected_before_searching():
    index = FakeIndex([])

    with pytest.raises(ValueError, match="must not be empty"):
        RetrievalService(index, []).retrieve(RetrievalRequest(query="   "))
    assert index.queries == []


def test_retrieved_runbook_without_a_loaded_document_is_an_error():
    index = FakeIndex([{"chunk_id": "c", "source": "runbooks/missing.md", "text": "t"}])

    with pytest.raises(ValueError, match="No source document loaded.*runbooks/missing.md"):
        RetrievalService(index, []).retrieve(RetrievalRequest(query="q"))


def test_service_groups_passages_and_skips_unsupported_sources():
    chunks = [
        {"chunk_id": "skip-0", "source": "policies/policy.md", "text": "ignored"},
        {"chunk_id": "skip-1", "source": "single.md", "text": "ignored"},
        {"chunk_id": "skip-2", "source": "", "text": "ignored"},
        {
            "chunk_id": "rb-0",
            "doc_id": "rb",
            "source": ".\\runbooks\\rb.md",
            "text": "first",
            "metadata": {"extra": 1},
        },
        {"chunk_id": "rb-1", "source": "runbooks/rb.md", "text": "second", "metadata": "not-a-dict"},
        {
            "chunk_id": "pm-0",
            "doc_id": "pm",
            "source": "postmortems/pm.md",
            "title": "Postmortem",
            "source_date": "2025-05-05",
            "service": "cart",
            "failure_family": "latency",
            "text": "history",
        },
        {"chunk_id": "pm-1", "source": "postmortems/pm.md", "text": "more history"},
    ]
    index = FakeIndex(chunks)

    response = RetrievalService(index, [_runbook(source="runbooks/rb.md")]).retrieve(
        RetrievalRequest(query="  payment failing  ")
    )

    assert index.queries == ["payment failing"]
    assert response.query == "payment failing"
    assert response.runbook_ids == ["rb"]
    assert response.postmortem_ids == ["pm"]
    assert [passage.chunk_id for passage in response.passages] == ["rb-0", "rb-1", "pm-0", "pm-1"]
    first, second, historic, bare_historic = response.passages
    assert first.source == "runbooks/rb.md"
    assert first.metadata == {"extra": 1}
    assert first.title == "Runbook title"
    assert (first.source_date, first.service, first.failure_family) == ("2026-01-01", "payment", "config")
    assert second.doc_id == "rb"
    assert second.metadata == {}
    assert historic.document_type == "postmortem"
    assert (historic.title, historic.source_date, historic.service) == ("Postmortem", "2025-05-05", "cart")
    assert historic.failure_family == "latency"
    assert (bare_historic.doc_id, bare_historic.title, bare_historic.source_date) == ("pm", None, None)
    assert (bare_historic.service, bare_historic.failure_family) == (None, None)
    assert response.postmortem_passages == [historic, bare_historic]
    runbook = response.runbooks[0]
    assert runbook.text == "Full runbook body"
    assert runbook.metadata == {"owner": "sre"}
    assert runbook.matched_passages == [first, second]
