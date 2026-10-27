from knowledge.retrieval.contracts import RetrievalRequest
from knowledge.retrieval.index import RetrievalCandidate
from knowledge.retrieval.ingest import IngestedDocument
from knowledge.retrieval.service import RetrievalService


class FakeRerankedIndex:
    def __init__(self, candidates):
        """Store deterministic candidates without calling an embedding or rerank API."""
        self.candidates = candidates
        self.query = None

    def search_reranked(self, query):
        """Record the generated query and return configured candidates."""
        self.query = query
        return self.candidates


def test_retrieval_service_maps_ranked_results_to_contract_and_full_runbook():
    """The service should return passages, full runbooks, and separate postmortem context."""
    runbook = IngestedDocument(
        doc_id="payment-failure",
        source="runbooks/payment-failure.md",
        source_date="2026-10-18",
        service="payment",
        failure_family="payment_failure",
        title="Payment service failures",
        body="## Confirm\nCheck payment traces.\n\n## Remediation\nRequire approval.",
        metadata={"fix": "Disable paymentFailure after approval", "related_flag": "paymentFailure"},
    )
    runbook_passage = RetrievalCandidate(
        chunk={
            "chunk_id": "payment-failure-2",
            "doc_id": runbook.doc_id,
            "source": runbook.source,
            "source_date": runbook.source_date,
            "service": runbook.service,
            "failure_family": runbook.failure_family,
            "title": runbook.title,
            "text": "## Confirm\nCheck payment traces.",
            "metadata": runbook.metadata,
        },
        score=0.8,
        rank=1,
        channel="reranker",
    )
    postmortem_passage = RetrievalCandidate(
        chunk={
            "chunk_id": "pm-payment-0",
            "doc_id": "pm-payment",
            "source": "postmortems/payment-flag-incident.md",
            "source_date": "2026-10-17",
            "service": "payment",
            "failure_family": "payment_failure",
            "title": "Payment flag incident",
            "text": "Payment traces confirmed the payment failure.",
            "metadata": {"preconditions": ["payment trace errors", "flag enabled"]},
        },
        score=0.7,
        rank=2,
        channel="reranker",
    )
    unsupported_source = RetrievalCandidate(
        chunk={
            "chunk_id": "ignored-0",
            "doc_id": "policy",
            "source": "memory/memory-policy.md",
            "text": "Policy text is not a RAG source document.",
        },
        score=0.6,
        rank=3,
        channel="reranker",
    )
    index = FakeRerankedIndex([runbook_passage, postmortem_passage, unsupported_source])
    service = RetrievalService(index, [runbook])

    response = service.retrieve(RetrievalRequest(query="Payment authorization requests are failing."))

    assert index.query == "Payment authorization requests are failing."
    assert response.query == index.query
    assert [passage.chunk_id for passage in response.passages] == [
        "payment-failure-2",
        "pm-payment-0",
    ]
    assert [passage.document_type for passage in response.passages] == ["runbook", "postmortem"]
    assert response.runbook_ids == ["payment-failure"]
    assert response.postmortem_ids == ["pm-payment"]
    assert response.postmortem_passages == [response.passages[1]]
    assert len(response.runbooks) == 1
    assert response.runbooks[0].text == runbook.body
    assert response.runbooks[0].metadata["fix"] == "Disable paymentFailure after approval"
    assert response.runbooks[0].matched_passages == [response.passages[0]]


def test_retrieval_service_returns_empty_context_when_no_supported_sources_match():
    """Unsupported retrieval sources should not leak into the Runbook Agent response."""
    index = FakeRerankedIndex(
        [
            RetrievalCandidate(
                chunk={
                    "chunk_id": "memory-0",
                    "doc_id": "memory",
                    "source": "memory/memory-policy.md",
                    "text": "Memory policy is not a runbook or postmortem passage.",
                },
                score=0.5,
                rank=1,
                channel="reranker",
            )
        ]
    )
    service = RetrievalService(index, [])

    response = service.retrieve(RetrievalRequest(query="checkout failure"))

    assert response.passages == []
    assert response.runbooks == []
    assert response.postmortem_passages == []
