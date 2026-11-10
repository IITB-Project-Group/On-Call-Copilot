"""Comms specialist: internal and external status notes and the postmortem, for a person to review.

The postmortem timeline is built by code from the incident trace, each entry tied to a span the
tools returned, so ``validate_postmortem`` can check it; the model writes the prose sections.
"""

from __future__ import annotations

from agents.context import AgentContext, compact
from agents.handoffs import CommsDraft, StatusNote


def run_comms(ctx: AgentContext, incident: dict, outcome: str, timeline: list[dict]) -> CommsDraft | None:
    result = ctx.react(
        "comms",
        "comms",
        {"incident": compact(incident, 1200), "outcome": outcome, "timeline": compact(timeline, 1200)},
        "Draft the status notes and the postmortem and submit a CommsDraft.",
        CommsDraft,
        budget=0,
    )
    return result.output


def template_draft(incident: dict, outcome: str, severity: str) -> CommsDraft:
    """The fixed-workflow (C0) draft: no model, plain facts only."""
    service = incident.get("service", "a service")
    top = (incident.get("hypotheses") or [{}])[0]
    cause = f"{top.get('service')} {top.get('fault_type')}" if top else "not determined"
    resolved = outcome == "resolved"
    return CommsDraft(
        internal=StatusNote(
            audience="internal",
            severity=severity,
            title=f"{service}: {outcome}",
            body=f"Alert on {service}. Top hypothesis: {cause}. Outcome: {outcome}.",
        ),
        external=StatusNote(
            audience="external",
            severity=severity,
            title="Service disruption" + (" resolved" if resolved else ""),
            body="Some customers saw errors or slow pages. "
            + ("Service has recovered." if resolved else "Engineers are working on it."),
        ),
        summary=f"Alert on {service}; outcome {outcome}.",
        impact="Customers on the affected path saw errors or slow responses.",
        root_cause=cause if resolved else "Not verified.",
        resolution="Approved action verified." if resolved else "Escalated to the on-call engineer.",
        lessons=[],
        action_items=["Review the incident trace."],
    )
