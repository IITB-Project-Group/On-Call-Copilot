"""Traces and metrics for the agents (L16: an agent inside an observed system).

* ``Recorder`` keeps a JSONL trace per incident: plan versions, every model and tool call with its
  hook verdict, interrupts and decisions. The evidence traces in docs/agents are rendered from it.
* LangSmith or Langfuse traces come from LangChain callbacks: set LANGSMITH_TRACING=true and
  LANGSMITH_API_KEY, or the LANGFUSE_* keys (``tracing_callbacks``).
* ``AgentMetrics`` exports Prometheus metrics for Grafana and for alerts on the agent itself.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Mapping

from prometheus_client import CollectorRegistry, Counter, Histogram


class Recorder:
    def __init__(self, incident_id: str, path: str | Path | None = None, clock=time.time):
        self.incident_id, self.clock = incident_id, clock
        self.path = Path(path) if path else None
        self.events: list[dict] = []
        self._lock = threading.Lock()  # parallel diagnosers record into one trace
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def event(self, kind: str, **data: Any) -> dict:
        entry = {"ts": round(self.clock(), 3), "incident": self.incident_id, "kind": kind, **data}
        self.events.append(entry)
        if self.path is not None:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, default=str) + "\n")
        return entry


def configure_tracing(env: Mapping[str, str] | None = None) -> bool:
    """Export spans to the shop collector when OTEL_EXPORTER_OTLP_ENDPOINT is set.

    Guardrail checks already call start_span. Without a provider those spans are discarded,
    so Jaeger shows the shop and not the agent.
    """
    environ = os.environ if env is None else env
    endpoint = environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if not endpoint:
        return False
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    service = environ.get("OTEL_SERVICE_NAME", "").strip() or "incident-api"
    provider = TracerProvider(resource=Resource.create({"service.name": service}))
    # The endpoint env is the collector base. The HTTP exporter appends /v1/traces.
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    return True


def tracing_callbacks() -> list:
    """LangChain callbacks for Langfuse when its keys are set. LangSmith needs only env vars."""
    if not (os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")):
        return []
    try:  # pragma: no cover - optional dependency, configured by role 6
        from langfuse.langchain import CallbackHandler

        return [CallbackHandler()]
    except ImportError:  # pragma: no cover
        return []


class AgentMetrics:
    """Prometheus metrics. Pass the incident API's registry so /metrics serves them."""

    def __init__(self, registry: CollectorRegistry | None = None):
        self.registry = registry or CollectorRegistry()
        r = self.registry
        self.incidents = Counter(
            "copilot_agent_incidents_total", "Agent runs by outcome.", ["outcome"], registry=r
        )
        self.diagnose = Histogram(
            "copilot_agent_time_to_diagnose_seconds",
            "Alert to a supported hypothesis.",
            registry=r,
            buckets=(10, 30, 60, 120, 300, 600, 1200, 1800),
        )
        self.recover = Histogram(
            "copilot_agent_time_to_recover_seconds",
            "Alert to verified recovery.",
            registry=r,
            buckets=(60, 120, 300, 600, 900, 1200, 1800, 3600),
        )
        self.tool_calls = Histogram(
            "copilot_agent_tool_calls_per_incident",
            "Tool calls per incident.",
            registry=r,
            buckets=(1, 3, 5, 10, 15, 20, 30, 50),
        )
        self.rollbacks = Counter("copilot_agent_rollbacks_total", "Actions rolled back.", registry=r)
        self.replans = Counter("copilot_agent_replans_total", "Replans.", registry=r)
        self.blocked = Counter(
            "copilot_agent_blocked_proposals_total", "Proposals the guardrails refused.", registry=r
        )
        self.halted = Counter(
            "copilot_agent_halted_total", "Incidents halted by a hook.", ["reason"], registry=r
        )
        self.cost = Counter("copilot_agent_cost_usd_total", "Model cost in USD.", registry=r)

    def observe(self, summary: dict) -> None:
        self.incidents.labels(outcome=summary.get("outcome") or "unknown").inc()
        if summary.get("time_to_diagnose_s") is not None:
            self.diagnose.observe(summary["time_to_diagnose_s"])
        if summary.get("time_to_recover_s") is not None:
            self.recover.observe(summary["time_to_recover_s"])
        self.tool_calls.observe(summary.get("tool_calls", 0))
        self.rollbacks.inc(summary.get("rollbacks", 0))
        self.replans.inc(summary.get("replans", 0))
        self.blocked.inc(summary.get("blocked_proposals", 0))
        self.cost.inc(summary.get("cost_usd", 0.0))
        if summary.get("halt_reason"):
            self.halted.labels(reason=str(summary["halt_reason"]).split(":")[0][:40]).inc()
