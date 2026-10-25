"""Alert, incident, tool result, action proposal, and eval case."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Alert(BaseModel):
    alert_name: str
    service: str
    starts_at: str
    expression: str
    payload: str


class IncidentState(BaseModel):
    id: str
    alert_name: str
    service: str
    starts_at: str
    expression: str
    payload: str
    command_text: str
    decision: str | None = None
    approved_text: str | None = None
    updated_at: str


class ToolResult(BaseModel):
    tool: str
    summary: str
    evidence: str = ""


class ActionProposal(BaseModel):
    action: str
    arguments: dict = Field(default_factory=dict)
    expected_effect: str
    rollback: str
    dry_run: bool = True


class EvalCase(BaseModel):
    case_id: str
    fault: str
    service: str
    correct_action: str
