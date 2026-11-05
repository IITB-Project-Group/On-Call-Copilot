"""The copilot MCP processes can listen on localhost without a cluster."""

import pytest

from tools import mcp_runtime
from tools.runbooks import server as runbooks
from tools.telemetry import server


class Recorder:
    def __init__(self):
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)


def test_stdio_is_the_default(monkeypatch):
    monkeypatch.delenv("MCP_TRANSPORT", raising=False)
    mcp = Recorder()
    mcp_runtime.run_server(mcp, port_env="TELEMETRY_MCP_PORT", default_port=8012)
    assert mcp.calls == [{}]


def test_blank_transport_stays_on_stdio(monkeypatch):
    monkeypatch.setenv("MCP_TRANSPORT", "  ")
    mcp = Recorder()
    mcp_runtime.run_server(mcp, port_env="TELEMETRY_MCP_PORT", default_port=8012)
    assert mcp.calls == [{}]


def test_http_uses_the_port_from_the_environment(monkeypatch):
    monkeypatch.setenv("MCP_TRANSPORT", "HTTP")
    monkeypatch.setenv("MCP_HOST", "  ")
    monkeypatch.setenv("TELEMETRY_MCP_PORT", " 9012 ")
    mcp = Recorder()
    mcp_runtime.run_server(mcp, port_env="TELEMETRY_MCP_PORT", default_port=8012)
    assert mcp.calls == [{"transport": "http", "host": "127.0.0.1", "port": 9012, "show_banner": False}]


def test_a_blank_port_uses_the_default(monkeypatch):
    monkeypatch.setenv("MCP_TRANSPORT", "http")
    monkeypatch.setenv("MCP_HOST", "127.0.0.1")
    monkeypatch.setenv("RUNBOOKS_MCP_PORT", "   ")
    mcp = Recorder()
    mcp_runtime.run_server(mcp, port_env="RUNBOOKS_MCP_PORT", default_port=8013)
    assert mcp.calls == [{"transport": "http", "host": "127.0.0.1", "port": 8013, "show_banner": False}]


def test_a_missing_port_uses_the_default(monkeypatch):
    monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")
    monkeypatch.delenv("MCP_HOST", raising=False)
    monkeypatch.delenv("RUNBOOKS_MCP_PORT", raising=False)
    mcp = Recorder()
    mcp_runtime.run_server(mcp, port_env="RUNBOOKS_MCP_PORT", default_port=8013)
    assert mcp.calls == [
        {
            "transport": "streamable-http",
            "host": "127.0.0.1",
            "port": 8013,
            "show_banner": False,
        }
    ]


def test_an_unknown_transport_is_rejected(monkeypatch):
    monkeypatch.setenv("MCP_TRANSPORT", "sse")
    with pytest.raises(ValueError, match="stdio or http"):
        mcp_runtime.run_server(Recorder(), port_env="TELEMETRY_MCP_PORT", default_port=8012)


def test_each_server_publishes_its_own_port(monkeypatch):
    seen = []

    def capture(mcp, *, port_env, default_port):
        seen.append((mcp, port_env, default_port))

    monkeypatch.setattr(mcp_runtime, "run_server", capture)
    monkeypatch.setattr(server, "build_server", lambda: "telemetry-mcp")
    monkeypatch.setattr(runbooks, "build_server", lambda: "runbooks-mcp")
    server.main()
    runbooks.main()
    assert seen == [
        ("telemetry-mcp", "TELEMETRY_MCP_PORT", 8012),
        ("runbooks-mcp", "RUNBOOKS_MCP_PORT", 8013),
    ]
