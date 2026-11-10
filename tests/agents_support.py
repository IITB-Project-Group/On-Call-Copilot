"""Scripted models for the agent tests. They imitate tool-calling models so the graph, hooks and
hand-offs run without network calls. They are test fixtures, never reported as model results."""

from __future__ import annotations

import json
import re

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

from agents.llm import scripted_builder, tool_call
from agents.settings import Experiment

ERR = "copilot:service_error_ratio:5m"


def steps(messages: list) -> int:
    return sum(1 for m in messages if isinstance(m, AIMessage))


def results(messages: list) -> list:
    out = []
    for m in messages:
        if isinstance(m, ToolMessage):
            try:
                out.append(json.loads(m.content))
            except (TypeError, ValueError):
                out.append(m.content)
    return out


def evidence(messages: list) -> list[str]:
    text = " ".join(str(m.content) for m in messages if isinstance(m, ToolMessage))
    return sorted(set(re.findall(r'"evidence_id": "([^"]+)"', text)))


def system(messages: list) -> str:
    return next(str(m.content) for m in messages if isinstance(m, SystemMessage))


def active_flags(messages: list) -> list[str]:
    flags = []
    for r in results(messages):
        if isinstance(r, dict):
            for c in r.get("changes") or []:
                if c.get("flag") and c.get("to") not in (None, "off") and c["flag"] not in flags:
                    flags.append(c["flag"])
                elif c.get("flag") in flags and c.get("to") == "off":
                    flags.remove(c["flag"])
    return flags


def error_ratios(messages: list) -> dict[str, float]:
    for r in results(messages):
        if isinstance(r, dict) and r.get("series"):
            return {s["service"]: s["value"] for s in r["series"]}
    return {}


SERVICE_FLAG = {
    "payment": ["paymentFailure", "paymentUnreachable"],
    "cart": ["cartFailure"],
    "ad": ["adHighCpu"],
    "kafka": ["kafkaQueueProblems"],
    "checkout": ["paymentUnreachable"],
}


def commander(role, messages):
    if "What contradicted it" in system(messages):
        return tool_call(
            "submit", {"focus": ["payment"], "reason": "the first hypothesis was refuted; test payment again"}
        )
    alert = re.search(r"Alert: \w+ on ([\w-]+)", system(messages)).group(1)
    return tool_call(
        "submit", {"focus": [alert, "payment"], "goals": {"triage": "look"}, "reason": "start at the alert"}
    )


def triage(role, messages):
    n = steps(messages)
    if n == 0:
        return tool_call("promql_query", {"query": ERR}, "t1")
    if n == 1:
        return tool_call("recent_changes", {"minutes": 60}, "t2")
    ratios = error_ratios(messages)
    ranked = [s for s, v in sorted(ratios.items(), key=lambda kv: -kv[1]) if v > 0.05 and s != "flagd"]
    return tool_call(
        "submit",
        {
            "no_fault": not ranked and not active_flags(messages),
            "affected_services": ranked,
            "suspects": ranked[:3] or ["ad"],
            "error_rate": max(ratios.values() or [0]),
            "active_flags": active_flags(messages),
            "evidence": evidence(messages)[:5],
            "summary": "scripted triage",
        },
    )


def make_diagnosis(wrong_first: bool = False):
    calls = {"rounds": 0}

    def diagnosis(role, messages):
        n = steps(messages)
        suspect = (
            re.search(r"Suspects assigned to you: ([\w, -]+)", system(messages))
            .group(1)
            .split(",")[0]
            .strip()
        )
        if n == 0:
            return tool_call("trace_search", {"service": suspect}, "d1")
        if n == 1:
            return tool_call("recent_changes", {"minutes": 60}, "d2")
        flags = active_flags(messages)
        text = " ".join(str(m.content) for m in messages if isinstance(m, ToolMessage))
        ev = evidence(messages)[:4]
        if wrong_first and calls["rounds"] == 0 and "connection refused" in text:
            calls["rounds"] += 1
            return tool_call(
                "submit",
                {
                    "hypotheses": [
                        {
                            "id": "a",
                            "rank": 1,
                            "service": "payment",
                            "fault_type": "error_injection",
                            "status": "supported",
                            "flag": "paymentFailure",
                            "evidence": ev,
                            "rationale": "checkout errors on the charge path",
                        }
                    ]
                },
            )
        if "connection refused" in text:
            return tool_call(
                "submit",
                {
                    "hypotheses": [
                        {
                            "id": "a",
                            "rank": 1,
                            "service": "payment",
                            "fault_type": "dependency_unreachable",
                            "status": "supported",
                            "flag": "paymentUnreachable",
                            "evidence": ev,
                            "rationale": "checkout cannot reach payment",
                        },
                        {
                            "id": "b",
                            "rank": 2,
                            "service": "payment",
                            "fault_type": "error_injection",
                            "status": "refuted",
                            "flag": "paymentFailure",
                            "evidence": ev,
                            "rationale": "paymentFailure is off",
                        },
                    ]
                },
            )
        candidates = [f for f in SERVICE_FLAG.get(suspect, []) if f in flags]
        if not candidates:
            return tool_call(
                "submit",
                {
                    "hypotheses": [
                        {
                            "id": "a",
                            "rank": 1,
                            "service": suspect,
                            "fault_type": "error_injection",
                            "status": "inconclusive",
                            "evidence": ev,
                        }
                    ],
                    "summary": "nothing here",
                },
            )
        fault = {
            "adHighCpu": "resource_exhaustion",
            "kafkaQueueProblems": "queue_backlog",
            "paymentUnreachable": "dependency_unreachable",
        }.get(candidates[0], "error_injection")
        return tool_call(
            "submit",
            {
                "hypotheses": [
                    {
                        "id": "a",
                        "rank": 1,
                        "service": suspect,
                        "fault_type": fault,
                        "status": "supported",
                        "flag": candidates[0],
                        "evidence": ev,
                        "rationale": f"{candidates[0]} is on",
                    },
                    {
                        "id": "b",
                        "rank": 2,
                        "service": suspect,
                        "fault_type": "crash",
                        "status": "proposed",
                        "evidence": [],
                    },
                    {
                        "id": "c",
                        "rank": 3,
                        "service": "checkout",
                        "fault_type": "hang",
                        "status": "proposed",
                        "evidence": [],
                    },
                ]
            },
        )

    return diagnosis


def runbook(role, messages):
    n = steps(messages)
    if n == 0:
        return tool_call("runbook_search", {"query": "payment errors"}, "r1")
    if n == 1:
        return tool_call("memory_search", {"query": "similar incidents"}, "r2")
    lessons = []
    for r in results(messages):
        if isinstance(r, list):
            lessons += [
                {
                    "lesson_id": x["id"],
                    "decision": "apply" if x.get("applicable") else "reject",
                    "reason": x.get("reason", ""),
                }
                for x in r
                if isinstance(x, dict) and "applicable" in x
            ]
    return tool_call("submit", {"runbook_ids": ["payment-failure"], "lessons": lessons, "notes": "scripted"})


def remediation(role, messages):
    flag = re.search(r'"flag": "(\w+)"', system(messages))
    action = {"type": "set_flag", "flag": flag.group(1) if flag else "paymentFailure", "enabled": False}
    return tool_call(
        "submit", {"hypothesis_id": "h1", "action": action, "rationale": "switch the injecting flag off"}
    )


def comms(role, messages):
    note = {
        "audience": "internal",
        "title": "Incident update",
        "body": "Checkout errors were fixed.",
        "severity": "SEV2",
    }
    ext = {
        "audience": "external",
        "title": "Some checkouts failed",
        "body": "Some customers could not check out. It is resolved.",
        "severity": "SEV2",
    }
    lesson = {
        "service": "payment",
        "fault_type": "error_injection",
        "lesson": "Switch the flag off after checking traces.",
        "preconditions": {"error_ratio.payment": {"op": "gte", "value": 0.05}},
        "applies_when": "payment errors",
    }
    return tool_call(
        "submit",
        {
            "internal": note,
            "external": ext,
            "summary": "s",
            "impact": "i",
            "root_cause": "r",
            "resolution": "fixed",
            "lessons": [lesson],
            "action_items": ["review"],
        },
    )


def investigator(role, messages):
    n = steps(messages)
    if n == 0:
        return tool_call("promql_query", {"query": ERR}, "i1")
    if n == 1:
        return tool_call("recent_changes", {"minutes": 60}, "i2")
    flags = active_flags(messages)
    flag = flags[0] if flags else None
    svc = {
        "paymentFailure": "payment",
        "cartFailure": "cart",
        "adHighCpu": "ad",
        "kafkaQueueProblems": "kafka",
    }.get(flag, "checkout")
    hyp = {
        "id": "a",
        "rank": 1,
        "service": svc,
        "fault_type": "error_injection",
        "status": "supported" if flag else "proposed",
        "flag": flag,
        "evidence": evidence(messages)[:3],
    }
    return tool_call(
        "submit",
        {
            "triage": {
                "suspects": [svc],
                "affected_services": [svc],
                "error_rate": 0.3,
                "evidence": evidence(messages)[:3],
                "summary": "single agent",
            },
            "diagnosis": {"hypotheses": [hyp]},
            "runbook_ids": ["payment-failure"],
            "lessons": [],
        },
    )


def reflection(role, messages):
    return tool_call(
        "submit",
        {
            "service": "payment",
            "fault_type": "error_injection",
            "lesson": "Check the flag first.",
            "preconditions": {"flag.paymentFailure": {"op": "eq", "value": True}},
            "applies_when": "paymentFailure is on",
        },
    )


def team(**overrides):
    scripts = {
        "commander": commander,
        "triage": triage,
        "diagnosis": make_diagnosis(),
        "runbook": runbook,
        "remediation": remediation,
        "comms": comms,
        "investigator": investigator,
        "reflection": reflection,
    }
    scripts.update(overrides)
    return scripts


def models(experiment: Experiment, **overrides):
    return scripted_builder(team(**overrides))(experiment)


def chatter(role, messages):
    """A model that never calls a tool, to test the 'call submit' nudge and max_steps."""
    return AIMessage(
        content="thinking", usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
    )
