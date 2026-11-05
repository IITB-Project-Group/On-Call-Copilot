"""Start a FastMCP server on stdio or on a localhost HTTP port."""

from __future__ import annotations

import os
from typing import Any

_HTTP = {"http", "streamable-http"}


def run_server(mcp: Any, *, port_env: str, default_port: int) -> None:
    """Run one server. HTTP listens on 127.0.0.1 unless MCP_HOST is set."""
    transport = os.environ.get("MCP_TRANSPORT", "stdio").strip().lower()
    if transport in {"", "stdio"}:
        mcp.run()
        return
    if transport not in _HTTP:
        raise ValueError(f"MCP_TRANSPORT must be stdio or http, not {transport!r}")
    host = os.environ.get("MCP_HOST", "127.0.0.1").strip() or "127.0.0.1"
    raw = os.environ.get(port_env)
    port = default_port if raw is None or not raw.strip() else int(raw.strip())
    mcp.run(transport=transport, host=host, port=port, show_banner=False)
