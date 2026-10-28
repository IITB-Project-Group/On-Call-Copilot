"""FastAPI process: webhook, live stream, decisions, and the console page."""

from __future__ import annotations

import asyncio
import os
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)
from pydantic import BaseModel, Field

from api.alerts import firing_alerts
from api.stream import snapshot_event
from incident_api.store import DECISIONS, IncidentStore
from tools.actions import FlagWriteError, set_payment_failure_off
from ui.page import PAGE


class DecisionBody(BaseModel):
    decision: str
    text: str = Field(default="")


def default_db_path() -> str:
    configured = os.environ.get("INCIDENT_DB")
    if configured:
        return configured
    preferred = Path("/data/incidents.sqlite3")
    try:
        preferred.parent.mkdir(parents=True, exist_ok=True)
        return str(preferred)
    except OSError:
        return str(Path(tempfile.gettempdir()) / "oncall-incidents.sqlite3")


_runbook_search = None


def default_runbook_search():
    """Load the in-memory runbook index once for this process."""
    global _runbook_search
    if _runbook_search is None:
        from knowledge.retrieval.contracts import RetrievalRequest
        from knowledge.retrieval.runtime import initialize_local_retrieval_service

        service = initialize_local_retrieval_service()

        def search(query: str):
            return service.retrieve(RetrievalRequest(query=query))

        _runbook_search = search
    return _runbook_search


def create_app(db_path: str | None = None, on_approve=None, runbook_search=None) -> FastAPI:
    change_flag = set_payment_failure_off if on_approve is None else on_approve
    store = IncidentStore(db_path or default_db_path())
    registry = CollectorRegistry()
    incidents_total = Counter(
        "copilot_incidents_total",
        "Incidents received from Alertmanager.",
        registry=registry,
    )
    Histogram(
        "copilot_time_to_diagnose_seconds",
        "Time from alert to a stated cause.",
        registry=registry,
    )
    Histogram(
        "copilot_time_to_recover_seconds",
        "Time from alert to verified recovery.",
        registry=registry,
    )
    Counter(
        "copilot_tool_calls_total",
        "Tool calls recorded for incidents.",
        registry=registry,
    )
    Counter(
        "copilot_rollbacks_total",
        "Remediation actions rolled back.",
        registry=registry,
    )
    Counter(
        "copilot_cost_usd_total",
        "Model cost in USD.",
        registry=registry,
    )

    app = FastAPI(title="On-Call Copilot incident API")
    app.state.store = store

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/runbooks")
    def search_runbooks(q: str = "") -> dict:
        if not q.strip():
            raise HTTPException(status_code=400, detail="q must not be empty")
        try:
            selected = runbook_search if runbook_search is not None else default_runbook_search()
            response = selected(q)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {
            "query": response.query,
            "runbook_ids": list(response.runbook_ids),
            "postmortem_ids": list(response.postmortem_ids),
        }

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return PAGE

    @app.get("/incidents")
    def list_incidents(state: str | None = None) -> list[dict]:
        if state is None:
            return store.list_incidents()
        if state in {"open", "closed"}:
            return store.list_incidents(state=state)
        raise HTTPException(status_code=400, detail="state must be open or closed")

    @app.get("/incidents/{incident_id}")
    def get_incident(incident_id: str) -> dict:
        incident = store.get(incident_id)
        if incident is None:
            raise HTTPException(status_code=404, detail="incident not found")
        return incident

    @app.post("/webhooks/alert")
    async def webhook(request: Request) -> dict:
        body = await request.json()
        created = []
        for alert in firing_alerts(body):
            incident, is_new = store.create(**alert.model_dump())
            if is_new:
                incidents_total.inc()
            created.append(incident)
        return {"incidents": created}

    @app.post("/incidents/{incident_id}/decision")
    def decision(incident_id: str, body: DecisionBody) -> dict:
        if body.decision not in DECISIONS:
            raise HTTPException(status_code=400, detail="unknown decision")
        current = store.get(incident_id)
        if current is None:
            raise HTTPException(status_code=404, detail="incident not found")
        flag_result = None
        if body.decision == "approve" and current["service"] in {"checkout", "payment"}:
            try:
                flag_result = change_flag()
            except FlagWriteError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
        try:
            updated = store.decide(incident_id, body.decision, body.text)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if updated is None:
            raise HTTPException(status_code=404, detail="incident not found")
        if flag_result is not None:
            updated = {**updated, "flag_result": flag_result}
        return updated

    @app.get("/incidents/{incident_id}/stream")
    async def stream(incident_id: str) -> StreamingResponse:
        async def events() -> AsyncIterator[str]:
            previous = None
            while True:
                incident = store.get(incident_id)
                event = snapshot_event(incident)
                if event != previous:
                    yield event
                    previous = event
                if incident is None:
                    return
                await asyncio.sleep(0.5)

        return StreamingResponse(events(), media_type="text/event-stream")

    @app.get("/metrics")
    def metrics() -> Response:
        return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
