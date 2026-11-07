"""Triage specialist: affected services, severity inputs, recent changes, suspects (ReAct, read-only)."""

from __future__ import annotations

from guardrail_core import KNOWN_SERVICES, PLATFORM_SERVICES

from agents.context import AgentContext, alert_text, metrics_text
from agents.handoffs import TriageReport


def clean_suspects(names: list[str], fallback: str) -> list[str]:
    """Known shop services only, no duplicates, at most three. Platform services are never suspects."""
    out: list[str] = []
    for name in names:
        if name in KNOWN_SERVICES and name not in PLATFORM_SERVICES and name not in out:
            out.append(name)
    if not out and fallback in KNOWN_SERVICES and fallback not in PLATFORM_SERVICES:
        out.append(fallback)
    return out[:3]


def run_triage(ctx: AgentContext, alert: dict, budget: int) -> TriageReport:
    result = ctx.react(
        "triage",
        "triage",
        {"alert": alert_text(alert), "metrics": metrics_text()},
        "Triage this alert and submit a TriageReport.",
        TriageReport,
        budget,
    )
    report = result.output or TriageReport(
        affected_services=[alert.get("service", "")],
        suspects=[alert.get("service", "")],
        summary=f"Triage did not finish ({result.reason}); falling back to the alerting service.",
    )
    report.suspects = clean_suspects(report.suspects, alert.get("service", ""))
    report.evidence = [e for e in report.evidence if e in ctx.tools.evidence]
    return report
