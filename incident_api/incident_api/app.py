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

from api.safety_gate import FLAG_SERVICES, AlertRateLimiter, SafetyGate, screen_webhook
from api.stream import snapshot_event
from incident_api.store import DECISIONS, IncidentStore
from tools.actions.set_flag import set_flag
from ui.page import PAGE

_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com; "
    "frame-ancestors 'none'"
)
_SECURITY_HEADERS = (
    ("x-frame-options", "DENY"),
    ("x-content-type-options", "nosniff"),
    ("content-security-policy", _CSP),
    ("referrer-policy", "no-referrer"),
)
_SECURITY_HEADER_NAMES = {name.encode() for name, _value in _SECURITY_HEADERS}


class DecisionBody(BaseModel):
    decision: str
    text: str = Field(default="")
    confirmation: str = Field(default="")
    approver: str = Field(default="oncall")


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


class SecurityHeaders:
    """Add the headers the deployment check looks for on every response."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = [
                    item
                    for item in message.get("headers") or []
                    if item[0].lower() not in _SECURITY_HEADER_NAMES
                ]
                headers.extend((name.encode(), value.encode()) for name, value in _SECURITY_HEADERS)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


def create_app(db_path: str | None = None, on_approve=None, agent=None) -> FastAPI:
    chosen = db_path or default_db_path()
    change_flag = set_flag if on_approve is None else on_approve
    store = IncidentStore(chosen)
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

    gate = SafetyGate(change_flag, audit_path=str(Path(chosen).with_name("audit.jsonl")))
    if agent is None and os.environ.get("COPILOT_AGENT"):
        from graph.live import build_live_agent

        agent = build_live_agent(store, gate, registry, chosen)
    if agent is not None:
        agent.resume_unfinished([incident["id"] for incident in store.list_incidents(state="open")])
    app = FastAPI(title="On-Call Copilot incident API")
    app.add_middleware(SecurityHeaders)
    app.state.store = store
    app.state.gate = gate
    app.state.agent = agent
    app.state.alerts = AlertRateLimiter()

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

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
        if not app.state.alerts.allow():
            raise HTTPException(status_code=429, detail="alert rate limit")
        raw = await request.body()
        alerts, error = screen_webhook(
            raw,
            request.headers.get("x-signature"),
            request.headers.get("x-timestamp"),
        )
        if error:
            raise HTTPException(status_code=400, detail=error)
        created = []
        for alert in alerts:
            incident, is_new = store.create(**alert)
            if is_new and agent is not None:
                incidents_total.inc()
                agent.start(incident["id"], {k: incident[k] for k in ("alert_name", "service", "starts_at")})
            elif is_new:
                incidents_total.inc()
                proposal = gate.propose(incident["id"], incident["service"])
                if proposal is not None:
                    request_id, code, command = proposal
                    saved = store.set_proposal(
                        incident["id"],
                        request_id=request_id,
                        code=code,
                        command=command,
                    )
                    incident = saved or incident
            created.append(incident)
        return {"incidents": created}

    @app.post("/incidents/{incident_id}/decision")
    def decision(incident_id: str, body: DecisionBody) -> dict:
        if body.decision not in DECISIONS:
            raise HTTPException(status_code=400, detail="unknown decision")
        current = store.get(incident_id)
        if current is None:
            raise HTTPException(status_code=404, detail="incident not found")
        if agent is not None and agent.handles(incident_id):
            return _agent_decision(incident_id, current, body)
        flag_result = None
        if body.decision == "approve" and current["service"] in FLAG_SERVICES:
            outcome = gate.execute(incident_id, current.get("approval_request_id"), body.confirmation)
            if not outcome.ok:
                raise HTTPException(status_code=outcome.status, detail=outcome.detail)
            flag_result = outcome.result
        try:
            updated = store.decide(incident_id, body.decision, body.text)
            if body.decision == "edit" and current["service"] in FLAG_SERVICES:
                gate.release(incident_id)
                proposal = gate.propose(incident_id, current["service"])
                if proposal is not None and updated is not None:
                    request_id, code, command = proposal
                    saved = store.set_proposal(
                        incident_id,
                        request_id=request_id,
                        code=code,
                        command=command,
                    )
                    updated = saved or updated
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if updated is None:
            raise HTTPException(status_code=404, detail="incident not found")
        if flag_result is not None:
            updated = {**updated, "flag_result": flag_result}
        return updated

    def _agent_decision(incident_id: str, current: dict, body: DecisionBody) -> dict:
        """Resume the incident graph with the engineer's decision on whatever it is waiting for."""
        pending = agent.pending(incident_id)
        if pending is None:
            view = agent.view(incident_id)
            if view.get("running"):
                raise HTTPException(status_code=409, detail="the agent is still working")
            # Graph finished (often escalated) but the incident row is still open: allow close.
            if body.decision in ("approve", "reject"):
                updated = store.decide(incident_id, body.decision, body.text) or current
                return {**updated, "agent": view}
            raise HTTPException(status_code=409, detail="the agent is not waiting for a decision")
        if body.decision == "edit" and not body.text.strip():
            raise HTTPException(status_code=400, detail="edit requires text")
        if pending["kind"] == "action" and body.decision == "approve":
            if body.confirmation.strip().upper() != str(pending["confirmation_code"]).upper():
                raise HTTPException(
                    status_code=400, detail="Confirmation does not match the exact command shown"
                )
        agent.resume(
            incident_id,
            {
                "decision": body.decision,
                "approver": body.approver,
                "text": body.text,
                "confirmation": body.confirmation,
                "comms_approver": body.approver,
            },
        )
        updated = current
        if pending["kind"] == "action" and body.decision in ("approve", "reject"):
            updated = store.decide(incident_id, body.decision, body.text) or current
        return {**updated, "agent": agent.view(incident_id)}

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
