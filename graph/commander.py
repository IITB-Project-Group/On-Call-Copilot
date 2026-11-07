"""The incident commander: writes the plan the engineer sees, and replans when evidence disagrees.

The commander uses the stronger model (agents.yaml ``models.commander``). Its plan names which
suspects to test first; the step list itself is fixed, so the model cannot skip approval or
verification. The fixed workflow (C0) and the single agent (C1) get a fixed plan instead.
"""

from __future__ import annotations

from agents.context import AgentContext, alert_text, compact
from agents.handoffs import STEP_NAMES, Plan, PlanDraft, PlanStep
from agents.triage import clean_suspects

DEFAULT_GOALS = {
    "triage": "Find affected services, severity inputs and recent changes.",
    "diagnose": "Test hypotheses for each suspect within the tool budget.",
    "runbook": "Match the top hypothesis to a runbook and check past lessons.",
    "propose": "Propose one allow-listed action with its rollback.",
    "approve": "Engineer approves the exact command.",
    "act": "Run the approved action.",
    "verify": "Confirm the expected effect is sustained, else roll back.",
    "communicate": "Draft status notes and the postmortem for review.",
    "learn": "Store reviewed lessons with their preconditions.",
}


def plan_from(draft: PlanDraft, version: int, fallback: str) -> Plan:
    goals = {**DEFAULT_GOALS, **{k: v for k, v in (draft.goals or {}).items() if k in DEFAULT_GOALS}}
    return Plan(
        version=version,
        focus=clean_suspects(draft.focus, fallback),
        steps=[PlanStep(name=name, goal=goals[name]) for name in STEP_NAMES],
        reason=draft.reason,
    )


def fixed_plan(
    alert: dict, version: int = 1, reason: str = "Fixed plan: investigate the alerting service."
) -> Plan:
    return plan_from(
        PlanDraft(focus=[alert.get("service", "")], reason=reason), version, alert.get("service", "")
    )


def make_plan(ctx: AgentContext, alert: dict) -> Plan:
    result = ctx.react(
        "commander",
        "commander",
        {"alert": alert_text(alert), "history": "none"},
        "Write the first plan and submit it.",
        PlanDraft,
        budget=0,
    )
    if result.output is None:
        return fixed_plan(alert, reason=f"Commander did not finish ({result.reason}); using the fixed plan.")
    return plan_from(result.output, 1, alert.get("service", ""))


def replan(
    ctx: AgentContext, alert: dict, history: list[dict], contradiction: str, hypotheses: list[dict]
) -> Plan:
    version = len(history) + 1
    result = ctx.react(
        "commander",
        "replan",
        {
            "alert": alert_text(alert),
            "history": compact(history, 1500),
            "contradiction": contradiction,
            "hypotheses": compact(hypotheses, 1200),
        },
        "Write the next plan and submit it.",
        PlanDraft,
        budget=0,
    )
    if result.output is None:
        previous = history[-1]["focus"] if history else [alert.get("service", "")]
        draft = PlanDraft(
            focus=previous, reason=f"Replan did not finish ({result.reason}); retrying: {contradiction}"
        )
        return plan_from(draft, version, alert.get("service", ""))
    return plan_from(result.output, version, alert.get("service", ""))
