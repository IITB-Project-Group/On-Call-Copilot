"""Typed hand-offs between the commander and the specialists.

Each specialist ends its ReAct loop by calling a ``submit`` tool whose arguments are one of these
models, so what it hands back is checked against a schema instead of being parsed from free text.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

STEP_NAMES = ("triage", "diagnose", "runbook", "propose", "approve", "act", "verify", "communicate", "learn")
HypothesisStatus = Literal["supported", "proposed", "inconclusive", "refuted"]
ActionType = Literal["set_flag", "restart_service", "scale_service", "rollback_deploy"]


class PlanStep(BaseModel):
    name: Literal[
        "triage", "diagnose", "runbook", "propose", "approve", "act", "verify", "communicate", "learn"
    ]
    goal: str = ""
    status: Literal["pending", "running", "done", "skipped", "failed"] = "pending"


class Plan(BaseModel):
    """The plan object the engineer sees. A replan writes a new version and says why."""

    version: int = 1
    focus: list[str] = Field(
        default_factory=list, description="Suspect services to test first, most likely first."
    )
    steps: list[PlanStep] = Field(default_factory=list)
    reason: str = ""


class PlanDraft(BaseModel):
    """What the commander model submits. Code turns it into a Plan with the fixed step list."""

    focus: list[str] = Field(description="Up to 3 suspect services to investigate, most likely first.")
    goals: dict[str, str] = Field(default_factory=dict, description="Optional goal text per step name.")
    reason: str = Field(description="One or two sentences: why this focus.")


class TriageReport(BaseModel):
    no_fault: bool = Field(default=False, description="True only when the evidence shows no fault (noise).")
    affected_services: list[str] = Field(default_factory=list)
    suspects: list[str] = Field(
        default_factory=list, description="Up to 3 suspect services, most likely first."
    )
    error_rate: float = Field(
        default=0.0, description="Highest error ratio on a critical-path service, 0..1."
    )
    p99_latency_ms: float = Field(default=0.0, description="Highest tail latency seen, in milliseconds.")
    availability_down: bool = False
    active_flags: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list, description="evidence_id values returned by the tools.")
    summary: str = ""


class Hypothesis(BaseModel):
    id: str
    rank: int
    service: str
    fault_type: str
    status: HypothesisStatus
    evidence: list[str] = Field(
        default_factory=list, description="evidence_id values that support or refute it."
    )
    flag: str | None = Field(default=None, description="The feature flag that would cause this, if any.")
    rationale: str = ""


class DiagnosisReport(BaseModel):
    investigator: str = ""
    no_fault: bool = False
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    summary: str = ""


class ActionSpec(BaseModel):
    """One allow-listed action with typed arguments. Free-form commands cannot be expressed."""

    type: ActionType
    flag: str | None = None
    enabled: bool | None = None
    service: str | None = None
    replicas: int | None = None
    to_version: str | None = None

    def to_action(self) -> dict:
        keys = {
            "set_flag": ("flag", "enabled"),
            "restart_service": ("service",),
            "scale_service": ("service", "replicas"),
            "rollback_deploy": ("service", "to_version"),
        }[self.type]
        return {"type": self.type, "args": {key: getattr(self, key) for key in keys}}


class LessonUse(BaseModel):
    lesson_id: str
    decision: Literal["apply", "reject"]
    reason: str = ""


class RunbookAdvice(BaseModel):
    runbook_ids: list[str] = Field(default_factory=list)
    recommended_action: ActionSpec | None = None
    lessons: list[LessonUse] = Field(default_factory=list)
    unsafe_steps: list[str] = Field(default_factory=list, description="Runbook steps not followed, and why.")
    notes: str = ""


class RemediationProposal(BaseModel):
    hypothesis_id: str
    action: ActionSpec
    rationale: str


class StatusNote(BaseModel):
    audience: Literal["internal", "external"]
    title: str
    body: str
    severity: Literal["SEV1", "SEV2", "SEV3", "SEV4"]


class LessonDraft(BaseModel):
    """A lesson and the conditions under which it applies. Preconditions use the observation keys
    the tools record, for example ``cpu_ratio.ad`` or ``flag.adHighCpu``."""

    service: str
    fault_type: str
    lesson: str
    preconditions: dict[str, dict] = Field(
        description='Map of observation key to {"op": eq|ne|in|not_in|gt|gte|lt|lte, "value": ...}.'
    )
    applies_when: str = Field(description="Plain-language statement of when the lesson applies.")


class CommsDraft(BaseModel):
    internal: StatusNote
    external: StatusNote | None = None
    summary: str
    impact: str
    root_cause: str
    resolution: str
    lessons: list[LessonDraft] = Field(default_factory=list)
    action_items: list[str] = Field(default_factory=list)


class InvestigationReport(BaseModel):
    """What the single-agent baseline (C1) submits: triage, diagnosis and runbook in one."""

    triage: TriageReport
    diagnosis: DiagnosisReport
    runbook_ids: list[str] = Field(default_factory=list)
    lessons: list[LessonUse] = Field(default_factory=list)
