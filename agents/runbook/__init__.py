"""Runbook specialist: match the top hypothesis to runbooks and past lessons (ReAct, KB tools only).

Lesson applicability is decided by code (``check_lesson`` inside memory_search); the specialist
reports which lessons it applied or rejected and why, and which runbook steps it did not follow.
"""

from __future__ import annotations

from agents.context import AgentContext, compact
from agents.handoffs import RunbookAdvice


def run_runbook(ctx: AgentContext, hypothesis: dict, budget: int) -> RunbookAdvice:
    result = ctx.react(
        "runbook",
        "runbook",
        {"hypothesis": compact(hypothesis, 600), "observations": compact(ctx.tools.observations, 1200)},
        "Find the runbook and relevant lessons for the top hypothesis and submit a RunbookAdvice.",
        RunbookAdvice,
        budget,
    )
    return result.output or RunbookAdvice(notes=f"Runbook lookup did not finish ({result.reason}).")
