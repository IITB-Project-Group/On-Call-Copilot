"""JSONL evaluation runner: one experiment config x a case split x N repeats.

    python -m eval.runner --experiment eval/experiments/e1-c2-team.yaml --split dev --out eval/results/e1-c2.jsonl

Each case runs the full incident graph against the shop twin (``eval.scenario``). A simulated
engineer approves every proposal that passed the guardrails, so the run measures what the agent
proposes; blocked and harmful proposals are still counted. Scoring uses the injected fault only
(``score_diagnosis``, ``classify_action``), never the agent's own confidence.

Every row records the config version, experiment and model ids. Failed and timed-out runs are
rows too, with ``error`` set.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
import traceback
import uuid
from pathlib import Path
from typing import Any

from approval_service import ApprovalService, Approver, ApproverRoster
from input_guardrails import InputGuardrails
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from output_guardrails import action_hash, classify_action, score_diagnosis, severity_from_policy

from agents.llm import ModelFactory
from agents.memory.lessons import lesson_store
from agents.settings import Experiment, load_config, load_experiment
from agents.toolbox import FlagOps, KnowledgeBackend, TicketSink
from eval.cases import load_cases
from eval.playbook import check as playbook_check
from eval.reliability import report as reliability_report
from eval.scenario import ShopTwin
from graph.incident_graph import GraphDeps, build_graph

ROSTER = (
    Approver("eval-oncall", frozenset({"oncall"})),
    Approver("eval-oncall-2", frozenset({"oncall"})),
    Approver("incident-commander", frozenset({"incident_commander", "comms_lead"})),
)
MAX_INTERRUPTS = 12


class SimulatedEngineer:
    """Approves every validated proposal (two people for dual control), approves the comms, and
    rejects lesson writes unless the run is collecting lessons (Reflexion on development cases)."""

    def __init__(self, keep_lessons: bool = False):
        self.keep_lessons = keep_lessons
        self.votes: dict[str, int] = {}

    def __call__(self, payload: dict) -> dict:
        if payload["kind"] == "action":
            n = self.votes.get(payload["request_id"], 0)
            self.votes[payload["request_id"]] = n + 1
            approver = ROSTER[min(n, 1)].approver_id
            return {"decision": "approve", "approver": approver, "confirmation": payload["confirmation_code"]}
        if payload["kind"] == "comms":
            return {"decision": "approve", "comms_approver": "incident-commander"}
        if self.keep_lessons:
            return {"decision": "approve", "approver": "eval-oncall"}
        return {"decision": "reject", "text": "evaluation run: lesson writes are off"}


def build_twin_run(
    case: dict,
    experiment: Experiment,
    *,
    models=None,
    traces_dir: str | None = None,
    config: dict | None = None,
    incident_id: str | None = None,
):
    config = config or load_config()
    twin = ShopTwin(case)
    guardrails = InputGuardrails()
    approvals = ApprovalService(ApproverRoster(ROSTER))
    ops = FlagOps(twin.read_flags, twin.write_flag)
    lessons = lesson_store(
        guardrails, memory=experiment.memory, playbook=experiment.playbook, frozen=experiment.playbook_frozen
    )
    incident_id = incident_id or f"{case['id']}-{uuid.uuid4().hex[:6]}"
    if models is None and experiment.architecture != "c0":
        models = ModelFactory(experiment, config)
    deps = GraphDeps(
        experiment=experiment,
        backends=twin.tools(),
        approvals=approvals,
        guardrails=guardrails,
        ops=ops,
        tickets=TicketSink(),
        knowledge=KnowledgeBackend(lessons),
        models=models,
        lessons=lessons,
        config=config,
        traces_dir=traces_dir,
        sleep=lambda _s: None,
    )
    return twin, deps, incident_id


def drive(graph, incident_id: str, alert: dict, reviewer) -> tuple[dict, int]:
    """Run the graph to the end, answering each interrupt with the reviewer."""
    config = {"configurable": {"thread_id": incident_id}}
    result = graph.invoke({"incident_id": incident_id, "alert": alert}, config)
    interrupts = 0
    while "__interrupt__" in result and interrupts < MAX_INTERRUPTS:
        interrupts += 1
        result = graph.invoke(Command(resume=reviewer(result["__interrupt__"][0].value)), config)
    return graph.get_state(config).values, interrupts


def score(case: dict, state: dict, twin: ShopTwin) -> dict:
    gt = case["ground_truth"]
    diagnosis = state.get("diagnosis") or {"hypotheses": []}
    scores = score_diagnosis(diagnosis, gt)
    proposals = state.get("proposals") or []
    classes = [classify_action(p["action"], gt) for p in proposals if p.get("action")]
    faults = gt.get("faults") or []
    fixed = all(twin.flags.get(f["fix"]["args"]["flag"]) == "off" for f in faults)
    proposed = {action_hash(p["action"]) for p in proposals if p.get("action") and not p.get("blocked")}
    correct = {action_hash(f["fix"]) for f in faults} <= proposed
    verified = state.get("outcome") == "resolved" and fixed
    harmful, unnecessary = classes.count("harmful"), classes.count("unnecessary")
    executed = [
        classify_action(p["action"], gt) for p in proposals if p.get("action") and not p.get("blocked")
    ]
    if faults:
        success = correct and verified and harmful == 0
    else:
        success = not classes and state.get("outcome") == "no_action"
    t = state.get("triage") or {}
    severity = severity_from_policy(
        {
            "error_rate": float(t.get("error_rate") or 0),
            "p99_latency_ms": float(t.get("p99_latency_ms") or 0),
            "affected_services": t.get("affected_services") or [],
        }
    )
    return {
        **scores,
        "correct_action": correct if faults else not classes,
        "verified_recovery": verified,
        "has_faults": bool(faults),
        "harmful_actions": harmful,
        "harmful_executed": executed.count("harmful"),
        "unnecessary_actions": unnecessary,
        "blocked_proposals": sum(1 for p in proposals if p.get("blocked")),
        "severity": severity,
        "severity_correct": severity == case["expected"].get("severity"),
        "success": success,
    }


def run_case(
    case: dict,
    experiment: Experiment,
    *,
    models=None,
    traces_dir: str | None = None,
    reviewer=None,
    config: dict | None = None,
    repeat: int = 0,
) -> dict:
    config = config or load_config()
    started = time.perf_counter()
    row: dict[str, Any] = {
        "case": case["id"],
        "split": case["split"],
        "experiment": experiment.name,
        "architecture": experiment.architecture,
        "parallel": experiment.parallel,
        "memory": experiment.memory,
        "budget": experiment.budget,
        "playbook": experiment.playbook,
        "repeat": repeat,
        "config_version": config["version"],
        "models": {r: experiment.model_id(r, config) for r in ("commander", "specialist")},
        "temperature": {r: experiment.temperature_for(r, config) for r in ("commander", "specialist")},
    }
    try:
        twin, deps, incident_id = build_twin_run(
            case, experiment, models=models, traces_dir=traces_dir, config=config
        )
        graph = build_graph(deps, InMemorySaver())
        state, interrupts = drive(graph, incident_id, twin.alert(), reviewer or SimulatedEngineer())
        session = deps.session(incident_id)
        hook = session.executor.mgr.state(incident_id)
        marks = {k: round(v - hook.started, 3) for k, v in hook.marks.items()}
        row.update(score(case, state, twin))
        row.update(
            {
                "incident_id": incident_id,
                "outcome": state.get("outcome"),
                "interrupts": interrupts,
                "tool_calls": hook.tool_calls,
                "cached_reads": len(session.tools.cache),
                "replans": hook.replans,
                "rollbacks": hook.rollbacks,
                "cost_usd": round(hook.cost_usd, 6),
                "halted": hook.halted,
                "halt_reason": hook.halt_reason,
                "time_to_diagnose_s": marks.get("diagnosed"),
                "time_to_recover_s": marks.get("recovered"),
                "plan_versions": len(state.get("plan_history") or []),
                "top_hypotheses": [
                    {k: h.get(k) for k in ("service", "fault_type", "flag", "status")}
                    for h in (state.get("diagnosis") or {}).get("hypotheses", [])[:3]
                ],
                "actions": [p.get("action") for p in state.get("proposals") or []],
                "error": None,
            }
        )
    except Exception as exc:  # a failed run is a result, not a crash of the whole experiment
        row.update(
            {
                "success": False,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc()[-800:],
            }
        )
    row["latency_s"] = round(time.perf_counter() - started, 3)
    return row


def summarise(rows: list[dict]) -> dict:
    ok = [r for r in rows if not r.get("error")]

    def rate(key: str, rows: list[dict] | None = None) -> float | None:
        rows = ok if rows is None else rows
        return round(sum(1 for r in rows if r.get(key)) / len(rows), 3) if rows else None

    latencies = sorted(r["latency_s"] for r in rows)
    pct = (
        (lambda q: latencies[min(len(latencies) - 1, int(q * len(latencies)))])
        if latencies
        else (lambda q: None)
    )
    return {
        "runs": len(rows),
        "errors": len(rows) - len(ok),
        "success": rate("success"),
        "top1_service": rate("top1_service"),
        "top3_service": rate("top3_service"),
        "top1_fault": rate("top1_fault"),
        "top3_fault": rate("top3_fault"),
        "correct_action": rate("correct_action"),
        "verified_recovery": rate("verified_recovery", [r for r in ok if r.get("has_faults")]),
        "severity_correct": rate("severity_correct"),
        "harmful_actions": sum(r.get("harmful_actions", 0) for r in ok),
        "harmful_executed": sum(r.get("harmful_executed", 0) for r in ok),
        "unnecessary_actions": sum(r.get("unnecessary_actions", 0) for r in ok),
        "blocked_proposals": sum(r.get("blocked_proposals", 0) for r in ok),
        "mean_tool_calls": round(statistics.mean(r["tool_calls"] for r in ok), 2) if ok else None,
        "cost_usd_total": round(sum(r.get("cost_usd", 0.0) for r in ok), 4),
        "latency_p50_s": pct(0.5),
        "latency_p95_s": pct(0.95),
    }


def run_experiment(
    experiment: Experiment,
    cases: list[dict],
    *,
    out: str | Path | None = None,
    repeats: int | None = None,
    models=None,
    traces_dir: str | None = None,
    resume: bool = False,
) -> dict:
    """With ``resume``, rows already in ``out`` that finished without error are kept; only failed
    or missing runs are run again, so an outage does not cost the finished runs twice."""
    kept: dict[tuple, dict] = {}
    if resume and out and Path(out).exists():
        for line in Path(out).read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if not row.get("error"):
                kept[(row["case"], row.get("repeat", 0))] = row
    rows = []
    for repeat in range(repeats or experiment.repeats):
        for case in cases:
            row = kept.get((case["id"], repeat))
            rows.append(
                row or run_case(case, experiment, models=models, traces_dir=traces_dir, repeat=repeat)
            )
    summary = {"experiment": experiment.name, **summarise(rows)}
    n = repeats or experiment.repeats
    if n > 1:  # with repeats, report reliability too: pass@k and pass^k (eval.reliability)
        summary["reliability"] = reliability_report(rows, k=n).get(experiment.name)
    if out:
        path = Path(out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r, default=str) + "\n" for r in rows), encoding="utf-8")
        path.with_suffix(".summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return {"rows": rows, "summary": summary}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--split", default="dev", choices=("dev", "heldout"))
    parser.add_argument("--cases-dir", help="Held-out cases directory, supplied by role 5.")
    parser.add_argument("--out", required=True)
    parser.add_argument("--repeats", type=int)
    parser.add_argument("--budget", type=int, help="Override the tool-call budget (E4).")
    parser.add_argument(
        "--temperature", type=float, help="Override the agents' temperature (pass@k / pass^k runs)."
    )
    parser.add_argument("--traces")
    parser.add_argument("--resume", action="store_true", help="Keep finished rows in --out; rerun the rest.")
    args = parser.parse_args(argv)
    experiment = load_experiment(args.experiment)
    if args.budget:
        experiment = experiment.with_budget(args.budget)
    if args.temperature is not None:
        experiment = experiment.with_temperature(args.temperature)
    if args.split == "heldout":
        if not args.cases_dir:
            parser.error("held-out cases come from role 5: pass --cases-dir")
        if experiment.playbook and not (experiment.playbook_frozen and playbook_check()):
            parser.error("freeze the playbook before a held-out run (python -m eval.playbook freeze)")
    cases = load_cases(args.split, args.cases_dir)
    result = run_experiment(
        experiment, cases, out=args.out, repeats=args.repeats, traces_dir=args.traces, resume=args.resume
    )
    print(json.dumps(result["summary"], indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
