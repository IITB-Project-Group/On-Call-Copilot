"""Telemetry MCP server (L7, READ-only).

The agent's "senses": exposes read-only tools to query the shop's health from
Prometheus (metrics + trace-derived span metrics) and Jaeger (traces). It makes
NO changes to the world — diagnosis agents get only this server, which is half
of signature challenge B ("diagnosis agents have no write tools").

Run standalone:  python -m mcp_servers.telemetry.server
"""
from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from config import settings
from mcp_servers.telemetry import client

settings.apply_ca_bundle_to_env()

mcp = FastMCP("telemetry")


@mcp.tool
def promql(query: str) -> dict[str, Any]:
    """Run an instant PromQL query against Prometheus and return matching series.

    Use for custom metric questions. For rate()/histogram queries, prefer a 5m
    window because the demo samples metrics about once per minute.
    READ-ONLY.
    """
    return client.promql(query).as_dict()


@mcp.tool
def service_error_rates(window: str = settings.DEFAULT_RANGE_WINDOW) -> dict[str, Any]:
    """Rank services by error rate (errors/sec) from trace span-metrics.

    Primary triage signal: identifies which services are currently failing.
    READ-ONLY.
    """
    return client.service_error_rates(window).as_dict()


@mcp.tool
def service_request_rates(window: str = settings.DEFAULT_RANGE_WINDOW) -> dict[str, Any]:
    """Per-service total call rate (calls/sec) from trace span-metrics. READ-ONLY."""
    return client.service_request_rates(window).as_dict()


@mcp.tool
def service_latency_p95(window: str = settings.DEFAULT_RANGE_WINDOW) -> dict[str, Any]:
    """Per-service p95 latency (seconds). Useful for 'slow but not erroring'
    incidents. READ-ONLY.
    """
    return client.service_latency_p95(window).as_dict()


@mcp.tool
def list_metric_names(substring: str = "") -> dict[str, Any]:
    """Discover available Prometheus metric names, optionally filtered. Helps the
    agent find the right metric before querying. READ-ONLY.
    """
    return client.list_metric_names(substring).as_dict()


@mcp.tool
def get_traces(service: str, only_errors: bool = True, limit: int = 5) -> dict[str, Any]:
    """Fetch recent (optionally errored) trace spans for a service from Jaeger.

    Returns a structured 'unavailable' result if Jaeger's query API cannot be
    reached, so the agent falls back to metric-based diagnosis. READ-ONLY.
    """
    return client.get_traces(service, only_errors, limit).as_dict()


if __name__ == "__main__":
    mcp.run()
