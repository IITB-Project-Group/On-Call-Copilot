import json

from knowledge.retrieval import runbooks_kb_tool, runtime
from knowledge.retrieval.contracts import RetrievalRequest, RetrievalResponse
from knowledge.retrieval.ingest import IngestedDocument
from knowledge.retrieval.service import RetrievalService


class FakeRetrievalService:
    """Capture query requests and return a fixed response without network calls."""

    def __init__(self):
        """Create a service double that counts requests."""
        self.requests = []
        self.response = RetrievalResponse(query="sample query")

    def retrieve(self, request):
        """Save the request and return the configured response."""
        self.requests.append(request)
        return self.response


def test_runtime_initializer_composes_startup_dependencies_once(monkeypatch):
    """The runtime initializer should build one reusable service from injected parts."""
    document = IngestedDocument(
        doc_id="sample-runbook",
        source="runbooks/sample.md",
        source_date="2026-10-21",
        service="sample",
        failure_family="sample_failure",
        title="Sample runbook",
        body="Sample runbook body.",
    )
    passage = {"chunk_id": "runbook-0", "text": "A passage"}
    encoder = object()
    created = {}

    monkeypatch.setattr(runtime, "load_retrieval_documents", lambda source: [document])
    monkeypatch.setattr(runtime, "chunk_markdown_documents", lambda docs: [passage])
    monkeypatch.setattr(runtime, "create_embedding_encoder", lambda: encoder)

    class FakeVectorStore:
        """Represent an already-indexed persistent Chroma collection."""

        count = 1

        def __init__(self, received_encoder, **kwargs):
            """Record the encoder and collection options passed at startup."""
            created["encoder"] = received_encoder
            created["store_kwargs"] = kwargs

    class FakeIndex:
        """Represent the hybrid index built once for the service lifetime."""

        def __init__(self, received_chunks, received_encoder, vector_store):
            """Record index construction dependencies."""
            created["chunks"] = received_chunks
            created["index_encoder"] = received_encoder
            created["vector_store"] = vector_store

        def search_reranked(self, query):
            """Return no candidates for this initialization-only test."""
            return []

    monkeypatch.setattr(runtime, "ChromaPassageStore", FakeVectorStore)
    monkeypatch.setattr(runtime, "HybridCandidateIndex", FakeIndex)

    service = runtime.initialize_retrieval_service()

    assert isinstance(service, RetrievalService)
    assert created["encoder"] is encoder
    assert created["index_encoder"] is encoder
    assert created["chunks"] == [passage]
    assert isinstance(created["vector_store"], FakeVectorStore)


def test_runbooks_tool_reuses_initialized_service_for_queries(monkeypatch):
    """Creating the tool initializes once, and repeated tool calls reuse that service."""
    service = FakeRetrievalService()
    initialize_calls = []

    def initialize_service():
        """Count startup initialization calls and return the shared service."""
        initialize_calls.append(True)
        return service

    monkeypatch.setattr(runbooks_kb_tool, "initialize_retrieval_service", initialize_service)
    tool = runbooks_kb_tool.create_runbooks_kb_tool()
    first_response = tool("first incident query")
    second_response = tool("second incident query")

    assert initialize_calls == [True]
    assert [request.query for request in service.requests] == [
        "first incident query",
        "second incident query",
    ]
    assert first_response is service.response
    assert second_response is service.response
    assert all(isinstance(request, RetrievalRequest) for request in service.requests)


def test_cli_prints_the_full_retrieval_response_as_json(monkeypatch, capsys):
    """The terminal adapter should serialize the contract returned by the tool."""
    query = "Add-to-cart requests are failing."
    service = FakeRetrievalService()
    service.response = RetrievalResponse(query=query, postmortem_ids=["cart-incident"])
    monkeypatch.setattr(
        runbooks_kb_tool,
        "create_runbooks_kb_tool",
        lambda: lambda value: service.retrieve(RetrievalRequest(value)),
    )

    exit_code = runbooks_kb_tool.main(["--query", query])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["query"] == query
    assert output["postmortem_ids"] == ["cart-incident"]
