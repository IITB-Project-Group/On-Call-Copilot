"""Wire the incident graph to the live shop for the incident API.

    COPILOT_AGENT=c2        team (c1 single agent, c0 fixed workflow); unset keeps the old flag gate
    OPENROUTER_API_KEY      needed for c1 and c2; without it the API falls back to c0 and says so
    COPILOT_MCP_URL         read telemetry through the FastMCP server instead of the in-process client
    COPILOT_BUDGET          investigation tool-call budget (default 10)
    COPILOT_PLAYBOOK        reviewed lessons file; COPILOT_PLAYBOOK_FROZEN=1 for held-out runs

The checkpointer, lesson store and traces sit next to the incident database.
Live reads use in-cluster Prometheus, Jaeger and OpenSearch (or MCP). Runbook search
tries role 2's hybrid index and falls back to BM25. Ticket drafts are copied into the
incident store.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path

from agents.llm import ModelFactory
from agents.memory.lessons import lesson_store
from agents.observability import AgentMetrics
from agents.settings import Experiment
from agents.toolbox import FlagOps, KnowledgeBackend, McpFetch, TelemetryBackend, TicketSink
from graph.incident_graph import GraphDeps
from graph.service import AgentService

logger = logging.getLogger(__name__)


class HybridSearch:
    """Role 2's runbook index. An empty or failed lookup lets KnowledgeBackend use BM25."""

    def __init__(self, factory=None):
        self.factory = factory
        self.tool = None
        self.failed = False

    def __call__(self, query: str) -> list[str]:
        if self.failed:
            return []
        try:
            if self.tool is None:
                create = self.factory or _default_runbooks_tool
                self.tool = create()
            response = self.tool(query)
            return [str(rid) for rid in (getattr(response, "runbook_ids", None) or [])]
        except Exception as exc:
            logger.warning("role-2 hybrid retrieval unavailable (%s); using BM25 runbooks", exc)
            self.failed = True
            return []


def _default_runbooks_tool():
    from knowledge.retrieval.runbooks_kb_tool import create_runbooks_kb_tool

    return create_runbooks_kb_tool()


def live_architecture(env=os.environ) -> str | None:
    arch = env.get("COPILOT_AGENT", "").strip().lower()
    if arch not in ("c0", "c1", "c2"):
        return None
    if arch != "c0" and not env.get("OPENROUTER_API_KEY"):
        logger.warning(
            "COPILOT_AGENT=%s needs OPENROUTER_API_KEY; running the fixed workflow (c0) instead", arch
        )
        return "c0"
    return arch


def build_live_agent(
    store,
    gate,
    registry,
    db_path: str,
    env=os.environ,
    *,
    read_flags=None,
    write_flag=None,
    fetch=None,
    run_async: bool = True,
    runbook_search=None,
) -> AgentService | None:
    arch = live_architecture(env)
    if arch is None:
        return None
    from langgraph.checkpoint.sqlite import SqliteSaver

    from tools.actions.set_flag import read_flags as live_read, set_flag

    base = Path(db_path)
    experiment = Experiment(
        name=f"live-{arch}",
        architecture=arch,
        budget=int(env.get("COPILOT_BUDGET") or 10),
        playbook=env.get("COPILOT_PLAYBOOK") or None,
        playbook_frozen=env.get("COPILOT_PLAYBOOK_FROZEN") == "1",
    )
    if fetch is None and env.get("COPILOT_MCP_URL"):
        fetch = McpFetch(env["COPILOT_MCP_URL"], guardrails=gate.ig).connect()
    telemetry = TelemetryBackend(fetch) if fetch is not None else TelemetryBackend()
    lessons = lesson_store(
        gate.ig,
        memory=experiment.memory,
        playbook=experiment.playbook,
        frozen=experiment.playbook_frozen,
        path=str(base.with_name("lessons.sqlite3")),
    )
    tickets = TicketSink(on_change=store.set_tickets)
    deps = GraphDeps(
        experiment=experiment,
        backends=telemetry.tools(),
        approvals=gate.approvals,
        guardrails=gate.ig,
        ops=FlagOps(read_flags or live_read, write_flag or set_flag, ttl_s=2.0),
        tickets=tickets,
        knowledge=KnowledgeBackend(lessons, search=runbook_search or HybridSearch()),
        models=None if arch == "c0" else ModelFactory(experiment),
        lessons=lessons,
        audit=gate.audit,
        traces_dir=env.get("COPILOT_TRACES_DIR") or str(base.with_name("traces")),
    )
    saver = SqliteSaver(sqlite3.connect(str(base.with_name("checkpoints.sqlite3")), check_same_thread=False))

    def publish(incident_id: str, view: dict) -> None:
        store.set_agent(incident_id, view)
        pending = service.pending(incident_id)
        if pending and pending.get("kind") == "action":
            store.set_proposal(
                incident_id,
                request_id=pending["request_id"],
                code=pending["confirmation_code"],
                command=pending["command"],
            )

    service = AgentService(deps, saver, run_async=run_async, metrics=AgentMetrics(registry), publish=publish)
    return service
