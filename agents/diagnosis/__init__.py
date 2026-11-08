"""Diagnosis specialist: test hypotheses about assigned suspects (ReAct, read-only tools only).

Several run in parallel, one per suspect (LangGraph ``Send``), or one runs for all suspects when
the experiment compares parallel diagnosis with a single investigator. ``merge`` combines their
reports and ``ground`` keeps only evidence the tools actually returned.
"""

from __future__ import annotations

from output_guardrails import ROLE_TOOL_ALLOWLIST

from guardrail_core import FLAG_SERVICE_MAP

from agents.catalog import PRIMARY_SERVICE, flags_text
from agents.context import AgentContext, alert_text, compact, metrics_text
from agents.handoffs import DiagnosisReport, Hypothesis

# The safety allow-list names are the one set of tool names (U0 decision 1). Read only, always.
READ_TOOLS = tuple(sorted(ROLE_TOOL_ALLOWLIST["diagnosis"]))
STATUS_ORDER = {"supported": 0, "proposed": 1, "inconclusive": 1, "refuted": 2}


def run_diagnosis(
    ctx: AgentContext, alert: dict, suspects: list[str], triage: dict, budget: int, feedback: str = ""
) -> DiagnosisReport:
    task = f"Diagnose {', '.join(suspects)} and submit a DiagnosisReport."
    if feedback:
        task += f" Earlier attempt did not hold up: {feedback}"
    result = ctx.react(
        "diagnosis",
        "diagnosis",
        {
            "alert": alert_text(alert),
            "suspects": ", ".join(suspects),
            "triage": compact(triage, 800),
            "lessons": ctx.lesson_text(),
            "metrics": metrics_text(),
            "flags": flags_text(),
        },
        task,
        DiagnosisReport,
        budget,
    )
    report = result.output or DiagnosisReport(summary=f"Diagnosis did not finish ({result.reason}).")
    report.investigator = ", ".join(suspects)
    return report


def ground(hypotheses: list[Hypothesis], evidence: set[str]) -> list[Hypothesis]:
    """Drop evidence ids no tool returned. A verdict left without evidence becomes inconclusive."""
    out = []
    for h in hypotheses:
        kept = [e for e in h.evidence if e in evidence]
        status = h.status if kept or h.status in ("proposed", "inconclusive") else "inconclusive"
        out.append(h.model_copy(update={"evidence": kept, "status": status}))
    return out


def locate(h: Hypothesis) -> Hypothesis:
    """A flag injects its fault into its own service; errors elsewhere are knock-on effects.
    A hypothesis that names a flag but another service is moved to the flag's service."""
    services = FLAG_SERVICE_MAP.get(h.flag or "")
    if not services or h.service in services:
        return h
    note = (
        f"Located in {PRIMARY_SERVICE[h.flag]}: {h.flag} injects there; {h.service} shows knock-on errors. "
    )
    return h.model_copy(update={"service": PRIMARY_SERVICE[h.flag], "rationale": note + h.rationale})


def merge(reports: list[DiagnosisReport], evidence: set[str]) -> dict:
    """One ranked hypothesis list from several diagnosers: supported first, duplicates merged."""
    best: dict[tuple, Hypothesis] = {}
    for report in reports:
        for h in map(locate, ground(report.hypotheses, evidence)):
            key = (h.service, h.fault_type, h.flag)
            old = best.get(key)
            if old is None or (STATUS_ORDER[h.status], h.rank) < (STATUS_ORDER[old.status], old.rank):
                merged = sorted(set(h.evidence) | set(old.evidence if old else []))
                best[key] = h.model_copy(update={"evidence": merged})
    ranked = sorted(best.values(), key=lambda h: (STATUS_ORDER[h.status], h.rank))[:5]
    hypotheses = [
        h.model_copy(update={"rank": i + 1, "id": f"h{i + 1}"}).model_dump() for i, h in enumerate(ranked)
    ]
    no_fault = bool(reports) and all(r.no_fault for r in reports) and not hypotheses
    out = {"hypotheses": hypotheses, "no_fault": no_fault}
    if no_fault:
        out["evidence"] = sorted({e for r in reports for e in r.evidence if e in evidence})
    return out
