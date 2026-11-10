"""Tool registration stays read-only and returns the in-process results."""

import sys
import types

from agents.diagnosis import READ_TOOLS
from agents.toolbox import MCP_TOOL_FOR
from knowledge.retrieval.contracts import RetrievalResponse, RetrievedPassage, RetrievedRunbook
from tools.actions import WRITE_ACTIONS
from tools.runbooks import server as runbooks
from tools.telemetry import client, server
from tools.tickets.server import ticket_tools


class Query:
    def __init__(self, **payload):
        self.payload = {"ok": True, "query": "q", "series": [], "error": None, **payload}

    def as_dict(self):
        return self.payload


class FakeMCP:
    def __init__(self, name):
        self.name = name
        self.tools = {}

    def tool(self, function):
        self.tools[function.__name__] = function
        return function

    def run(self, **kwargs):
        self.ran = True
        self.kwargs = kwargs


def test_ticket_writes_stay_on_the_incident_api():
    assert ticket_tools() == ()
    assert "set_flag" in WRITE_ACTIONS


def test_telemetry_tools_match_the_diagnosis_names_and_delegate(monkeypatch):
    monkeypatch.setattr(client, "promql", lambda query: Query(query=query))
    monkeypatch.setattr(client, "log_search", lambda query, service=None, limit=8: Query(query=query))
    monkeypatch.setattr(client, "get_traces", lambda service, only_errors=True, limit=5: Query(query=service))
    monkeypatch.setattr(client, "recent_changes", lambda: Query(query="recent_changes"))
    monkeypatch.setattr(client, "service_error_ratio", lambda window=None: Query(query=window or "2m"))
    monkeypatch.setattr(client, "service_error_rates", lambda window=None: Query(query="rate"))
    monkeypatch.setattr(client, "service_request_rates", lambda window=None: Query(query="requests"))
    monkeypatch.setattr(client, "service_latency_p95", lambda window=None: Query(query="latency"))
    monkeypatch.setattr(client, "list_metric_names", lambda substring="": Query(query=substring))

    assert server.promql("up")["query"] == "up"
    assert server.logs("error", service="payment")["query"] == "error"
    assert server.traces("payment")["query"] == "payment"
    assert server.recent_changes()["query"] == "recent_changes"
    assert server.service_error_ratio()["query"] == "2m"
    assert server.service_error_rates("2m")["query"] == "rate"
    assert server.service_request_rates()["query"] == "requests"
    assert server.service_latency_p95()["query"] == "latency"
    assert server.list_metric_names("span")["query"] == "span"
    assert set(server.TOOL_NAMES).isdisjoint(WRITE_ACTIONS)
    assert {"promql_query", "log_search", "trace_search", "recent_changes"} <= set(READ_TOOLS)
    assert set(MCP_TOOL_FOR.values()) <= set(server.TOOL_NAMES)


def test_telemetry_server_registers_tools_without_installing_fastmcp(monkeypatch):
    created = {}

    def factory(name):
        created["server"] = FakeMCP(name)
        return created["server"]

    registered = server.build_server(factory)
    assert registered.name == "telemetry"
    assert set(registered.tools) == set(server.TOOL_NAMES)

    module = types.ModuleType("fastmcp")
    module.FastMCP = FakeMCP
    monkeypatch.setitem(sys.modules, "fastmcp", module)
    assert server.load_fastmcp() is FakeMCP
    loaded = server.build_server()
    assert loaded.name == "telemetry"

    monkeypatch.setattr(server, "build_server", lambda: FakeMCP("telemetry"))
    server.main()


def test_runbook_search_returns_the_full_runbook(monkeypatch):
    text = "Disable the paymentFailure feature flag after engineer approval. " * 20
    passage = RetrievedPassage(
        rank=1,
        chunk_id="pm-1",
        doc_id="pm-010",
        document_type="postmortem",
        title="Misleading lesson case",
        source="postmortems/misleading-lesson-case.md",
        source_date=None,
        service="ad",
        failure_family="ad_high_cpu",
        text="The ad lesson does not apply.",
    )
    response = RetrievalResponse(
        runbook_ids=["payment-failure"],
        postmortem_ids=["pm-010"],
        query="payment errors",
        runbooks=[
            RetrievedRunbook(
                id="payment-failure",
                title="Payment service failures",
                source="runbooks/payment-failure.md",
                source_date="2026-01-01",
                service="payment",
                failure_family="payment_failure",
                text=text,
            )
        ],
        postmortem_passages=[passage],
    )

    monkeypatch.setattr(runbooks, "create_runbooks_kb_tool", lambda: (lambda query: response))
    found = runbooks.search("payment errors")
    assert found["ok"] is True
    assert found["runbooks"][0]["text"] == text
    assert len(found["runbooks"][0]["text"]) > 240
    assert found["postmortem_passages"][0]["doc_id"] == "pm-010"

    monkeypatch.setattr(runbooks, "create_runbooks_kb_tool", lambda: _raising(RuntimeError("index empty")))
    assert runbooks.search("payment errors")["error"] == "index empty"
    monkeypatch.setattr(runbooks, "create_runbooks_kb_tool", lambda: _raising(ValueError("blank")))
    assert runbooks.search(" ")["error"] == "blank"


def _raising(exc):
    def tool(query):
        raise exc

    return tool


def test_runbook_server_registers_search(monkeypatch):
    registered = runbooks.build_server(FakeMCP)
    assert registered.name == "runbooks-kb"
    assert set(registered.tools) == {"search"}

    module = types.ModuleType("fastmcp")
    module.FastMCP = FakeMCP
    monkeypatch.setitem(sys.modules, "fastmcp", module)
    assert runbooks.load_fastmcp() is FakeMCP
    assert runbooks.build_server().name == "runbooks-kb"
    monkeypatch.setattr(runbooks, "build_server", lambda: FakeMCP("runbooks-kb"))
    runbooks.main()
