"""Runbook search tool.

Search calls the in-process knowledge service and returns the full retrieval response,
including complete runbook text. ``up.sh`` serves it at http://127.0.0.1:8013/mcp.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from api.live_screen import require_clean_descriptions, screen_retrieval
from knowledge.retrieval.runbooks_kb_tool import create_runbooks_kb_tool

TOOL_NAMES = ("search",)


def search(query: str) -> dict[str, Any]:
    """Return ranked runbooks and postmortems for one incident query."""
    try:
        response = create_runbooks_kb_tool()(query)
    except (RuntimeError, ValueError) as exc:
        return {"ok": False, "error": str(exc), "query": query}
    body = asdict(response)
    body["ok"] = True
    return screen_retrieval(body)


def build_server(factory=None):
    """Register runbook search. Pass a factory in tests to avoid installing FastMCP."""
    require_clean_descriptions("runbooks-kb", (search,))
    mcp_cls = factory if factory is not None else load_fastmcp()
    mcp = mcp_cls("runbooks-kb")
    mcp.tool(search)
    return mcp


def load_fastmcp():
    """Import FastMCP when a server process actually starts."""
    from fastmcp import FastMCP

    return FastMCP


def main() -> None:
    """Run the runbooks MCP server. HTTP when MCP_TRANSPORT=http."""
    from tools.mcp_runtime import run_server

    run_server(build_server(), port_env="RUNBOOKS_MCP_PORT", default_port=8013)


if __name__ == "__main__":  # pragma: no cover
    main()
