"""The two baselines E1 compares with the team, using the same tools, hooks and budget.

* C0, a fixed workflow: the same reads every time and a rule from the fault catalogue (an active
  flag whose service shows that fault's signal). No model decides anything. It generalises the
  original paymentFailure slice in graph/steps.py to every catalogue flag.
* C1, a single agent: one ReAct investigator with every read and knowledge tool and the whole
  investigation budget, submitting triage, diagnosis, runbook and an action proposal at once.
"""

from __future__ import annotations

from agents.catalog import FLAG_FAULT_TYPE, PRIMARY_SERVICE, SIGNAL, flags_text
from agents.context import AgentContext, alert_text, metrics_text
from agents.handoffs import InvestigationReport, TriageReport
from agents.toolbox import METRICS, IncidentTools

FIXED_READS = (
    "copilot:service_error_ratio:5m",
    "copilot:service_p95_latency_seconds:2m",
    "copilot:container_cpu_ratio",
    "copilot:memory_growth_ratio:5m",
    "copilot:kafka_consumer_lag",
    "copilot:service_request_rate:2m",
)


def fixed_investigation(tools: IncidentTools, alert: dict) -> tuple[dict, dict]:
    """C0: read every signal, list flag changes, and rank active flags by their service's signal."""
    evidence: dict[str, dict[str, str]] = {}
    for query in FIXED_READS:
        ok, result, _ = tools.call("triage", "promql_query", {"query": query})
        if ok:
            evidence[METRICS[query][0]] = {
                (s.get("labels") or {}).get("service_name"): s["evidence_id"]
                for s in result.get("series") or []
            }
    ok, changes, _ = tools.call("triage", "recent_changes", {"lookback_s": 3600})
    rows = (changes or {}).get("changes") or [] if ok else []
    change_ids = {c["flag"]: c["evidence_id"] for c in rows if c.get("flag")}
    obs = tools.observations
    hypotheses = []
    for flag, fault_type in FLAG_FAULT_TYPE.items():
        if not obs.get(f"flag.{flag}"):
            continue
        service = PRIMARY_SERVICE[flag]
        metric, threshold = SIGNAL[fault_type]
        watched = "accounting" if fault_type == "queue_backlog" else service
        value = obs.get(f"{metric}.{watched}", 0.0)
        supported = value >= threshold
        hypotheses.append(
            {
                "service": service,
                "fault_type": fault_type,
                "flag": flag,
                "score": value / threshold,
                "status": "supported" if supported else "proposed",
                "evidence": [e for e in (change_ids.get(flag), evidence.get(metric, {}).get(watched)) if e],
                "rationale": f"{flag} is on; {metric}.{watched}={value:.3g} (threshold {threshold})",
            }
        )
    hypotheses.sort(key=lambda h: (h["status"] != "supported", -h["score"]))
    ranked = [
        {**{k: v for k, v in h.items() if k != "score"}, "id": f"h{i + 1}", "rank": i + 1}
        for i, h in enumerate(hypotheses)
    ]
    errors = obs.get(f"error_ratio.{alert.get('service')}", 0.0)
    critical = max(
        [v for k, v in obs.items() if k.startswith("error_ratio.") and not k.endswith(".flagd")] or [0.0]
    )
    triage = TriageReport(
        no_fault=not ranked,
        affected_services=sorted({h["service"] for h in ranked}) or [alert.get("service", "")],
        suspects=[h["service"] for h in ranked[:3]],
        error_rate=critical,
        p99_latency_ms=1000 * max([v for k, v in obs.items() if k.startswith("p95_latency_s.")] or [0.0]),
        active_flags=[h["flag"] for h in ranked],
        summary=f"Fixed workflow: {len(ranked)} active failure flag(s); {alert.get('service')} error ratio {errors:.3g}.",
    ).model_dump()
    diagnosis = {"hypotheses": ranked, "no_fault": not ranked}
    if not ranked:
        diagnosis["evidence"] = sorted(tools.evidence)[:5]
    return triage, diagnosis


def run_investigator(
    ctx: AgentContext, alert: dict, budget: int, feedback: str = ""
) -> InvestigationReport | None:
    task = "Investigate this alert and submit an InvestigationReport."
    if feedback:
        task += f" Your previous conclusion did not hold up: {feedback}"
    result = ctx.react(
        "investigator",
        "investigator",
        {
            "alert": alert_text(alert),
            "lessons": ctx.lesson_text(),
            "metrics": metrics_text(),
            "flags": flags_text(),
        },
        task,
        InvestigationReport,
        budget,
    )
    return result.output
