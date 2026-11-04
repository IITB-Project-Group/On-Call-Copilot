"""Runbooks-KB MCP server (L7, READ).

Exposes hybrid search over runbooks + postmortems (BM25 + vector + RRF + cross
-encoder rerank). Returns citable passage IDs. READ-only.

Run standalone:  python -m mcp_servers.runbooks_kb.server
"""
from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from retrieval.hybrid_search import get_retriever

mcp = FastMCP("runbooks-kb")


@mcp.tool
def search(query: str, k: int = 5) -> dict[str, Any]:
    """Search runbooks + postmortems for passages relevant to the query.

    Returns ranked passages with citable IDs and metadata (service, flag, type).
    READ-only.
    """
    hits = get_retriever().search(query, k=k)
    return {"query": query, "results": [
        {"id": h["id"], "service": h["metadata"].get("service"),
         "flag": h["metadata"].get("flag"), "type": h["metadata"].get("type"),
         "score": round(h.get("rerank_score", 0.0), 3),
         "preconditions": h["metadata"].get("preconditions"),
         "excerpt": h["text"][:240]}
        for h in hits]}


if __name__ == "__main__":
    mcp.run()
