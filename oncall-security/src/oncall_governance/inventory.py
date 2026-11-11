"""AI system inventory (MAP-02) and software bill of materials (DP-02)."""
from __future__ import annotations

from importlib import metadata


def build_inventory(target=None) -> dict:
    from output_guardrails import ROLE_TOOL_ALLOWLIST, WRITE_TOOLS
    try:
        from oncall_copilot.shop_tools import ShopTools  # type: ignore  (v2 reference)
        tools = sorted(n for n in dir(ShopTools) if not n.startswith("_") and n not in ("tool_map", "previous_state"))
    except ImportError:   # live product: the tools agents may call are exactly the role allow-lists
        tools = sorted(set().union(*ROLE_TOOL_ALLOWLIST.values()))
    return {"system": "On-Call Copilot", "model": "gpt-4.1-mini (OpenRouter/OpenAI) or deterministic policy",
            "roles": {r: sorted(t) for r, t in ROLE_TOOL_ALLOWLIST.items()},
            "write_tools": sorted(WRITE_TOOLS), "tools": tools,
            "data_flows": ["Prometheus -> telemetry tools -> input guardrails -> agents",
                           "OpenSearch logs / Jaeger traces -> input guardrails -> agents",
                           "agents -> output guardrails -> approval service -> ops-actions -> shop",
                           "agents -> comms -> status notes (external needs approval)",
                           "lessons -> memory (human review, frozen) -> runbook agent"],
            "human_roles": ["oncall", "incident_commander", "comms_lead", "security_admin", "viewer"],
            "external_dependencies": ["OpenRouter / OpenAI API", "Prometheus", "OpenSearch", "Jaeger", "flagd", "Docker API (live)"]}


def sbom() -> dict:
    comps = sorted({(d.metadata["Name"], d.version) for d in metadata.distributions() if d.metadata["Name"]})
    keep = {"langgraph", "langchain-core", "fastapi", "starlette", "uvicorn", "pydantic", "openai", "mcp", "httpx",
            "prometheus-client", "prometheus_client", "pyyaml", "PyYAML", "opentelemetry-api", "opentelemetry-sdk",
            "python-dotenv", "oncall-copilot", "oncall-security", "on-call-copilot", "sniffio", "idna", "h11", "certifi", "annotated-types", "typing_extensions", "typing-extensions", "click", "anyio", "pydantic-core", "pydantic_core", "jsonschema"}
    return {"bomFormat": "CycloneDX-lite", "components": [{"name": n, "version": v} for n, v in comps if n in keep or n.lower() in keep]}
