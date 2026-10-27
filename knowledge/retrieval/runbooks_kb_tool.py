"""Callable runbooks-kb adapter and command-line query tool."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from typing import Sequence

from .contracts import RetrievalRequest, RetrievalResponse
from .runtime import initialize_retrieval_service
from .service import RetrievalService


class RunbooksKBTool:
    """Reusable query-only adapter for MCP or another in-process tool host."""

    def __init__(self, retrieval_service: RetrievalService) -> None:
        """Retain the initialized service so requests reuse its index and Chroma client."""
        self._retrieval_service = retrieval_service

    def __call__(self, query: str) -> RetrievalResponse:
        """Forward one query string and return the retrieval response contract."""
        return self._retrieval_service.retrieve(RetrievalRequest(query=query))


def create_runbooks_kb_tool(
    retrieval_service: RetrievalService | None = None,
) -> RunbooksKBTool:
    """Create the callable tool, initializing retrieval only when called at startup."""
    service = retrieval_service or initialize_retrieval_service()
    return RunbooksKBTool(service)


def main(argv: Sequence[str] | None = None) -> int:
    """Accept a query in the terminal and print its full response as JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True, help="Incident search query")
    args = parser.parse_args(argv)

    tool = create_runbooks_kb_tool()
    response = tool(args.query)
    print(json.dumps(asdict(response), indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
