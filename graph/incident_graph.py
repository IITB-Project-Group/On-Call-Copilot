"""The incident graph: a LangGraph state machine for one incident (L8, L10, L11, L14).

    intake -> plan -> triage -> diagnose (one per suspect, in parallel) -> assess
    assess -> runbook -> propose -> approve (interrupt) -> act -> verify -> communicate -> review (interrupt) -> learn
    assess / propose / approve / rollback -> replan -> diagnose      (replan on contradiction)
    verify -> rollback -> replan                                     (self-correction loop)

C1 swaps triage and diagnose for one ``investigate`` node; C0 swaps them for the fixed workflow.
Everything after ``assess`` is shared, so the comparison is about how the incident is investigated.

The state is typed (``IncidentGraphState``) and checkpointed after every step, so a stopped
process resumes where it stopped. Every tool call goes through the safety hooks, every action
waits for ``interrupt()`` and the engineer's ``Command(resume=...)``, and an edit cancels the
pending approval. Per-incident runtime objects (executor, recorder) live outside the state.
"""

from __future__ import annotations

import operator
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Annotated, Any, TypedDict

from guardrail_core import FLAG_SERVICE_MAP, Decision
from hooks import CostLimitHook, GuardedExecutor, HookManager, default_hooks
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send, interrupt
from output_guardrails import (
    severity_from_policy,
    validate_diagnosis,
    validate_plan,
    validate_postmortem,
    validate_status_note,
    verify_recovery,
)

from agents.catalog import FLAG_FAULT_TYPE
from agents.comms import run_comms, template_draft
from agents.context import AgentContext
from agents.diagnosis import merge, run_diagnosis
from agents.handoffs import DiagnosisReport
from agents.observability import Recorder
from agents.remediation import build_plan, run_remediation
from agents.runbook import run_runbook
from agents.settings import Experiment, load_config, role_budgets
from agents.toolbox import IncidentTools
from agents.triage import clean_suspects, run_triage
from graph import commander
from graph.baselines import fixed_investigation, run_investigator

OPS_TOOL = {
    "set_flag": "ops_set_flag",
    "restart_service": "ops_restart_service",
    "scale_service": "ops_scale_service",
    "rollback_deploy": "ops_rollback_deploy",
}


class IncidentGraphState(TypedDict, total=False):
    incident_id: str
    alert: dict
    status: str
    next: str
    plan: dict
    plan_history: Annotated[list, operator.add]
    round: int
    triage: dict
    suspects: list
    assignment: list
    diagnoses: Annotated[list, operator.add]
    diagnosis: dict
    contradiction: str
    runbook: dict
    investigation: dict
    proposal: dict
    edit_note: str
    proposals: Annotated[list, operator.add]
    resolved: Annotated[list, operator.add]
    verification: dict
    comms: dict
    outcome: str
    events: Annotated[list, operator.add]
    lessons_reviewed: list


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class Session:
    """Runtime objects for one incident. Rebuilt after a restart; budgets start again then."""

    executor: GuardedExecutor
    tools: IncidentTools
    recorder: Recorder
    ctx: AgentContext


@dataclass
class GraphDeps:
    experiment: Experiment
    backends: dict[str, Callable[..., Any]]
    approvals: Any
    guardrails: Any
    ops: Any
    tickets: Any
    knowledge: Any = None
    models: Any = None
    lessons: Any = None
    config: dict = field(default_factory=load_config)
    audit: Any = None
    traces_dir: str | None = None
    sleep: Callable[[float], None] = time.sleep
    on_update: Callable[[str, dict], None] | None = None
    on_activity: Callable[[str, str], None] | None = None
    sessions: dict = field(default_factory=dict)

    def executor_for(self, incident_id: str) -> GuardedExecutor:
        budgets = self.config["budgets"]
        hooks = default_hooks(
            input_guardrails=self.guardrails,
            approval_gate=self.approvals,
            previous_state=self.ops.snapshot,
            max_tool_calls=self.experiment.budget + budgets["action_reserve_tool_calls"],
            max_cost_usd=budgets["max_cost_usd"],
            max_wall_clock_s=budgets["max_wall_clock_s"],
            max_replans=budgets["max_replans"],
            max_rollbacks=budgets["max_rollbacks"],
            per_role=role_budgets(self.experiment, self.config),
            memory_frozen=self.experiment.playbook_frozen,
        )
        pricing = self.config["pricing"]
        hooks = [
            CostLimitHook(budgets["max_cost_usd"], pricing) if isinstance(h, CostLimitHook) else h
            for h in hooks
        ]
        tools = {**self.backends, **self.ops.tools(), **self.tickets.tools(incident_id)}
        if self.knowledge is not None:
            tools.update(
                self.knowledge.tools(
                    memory=self.experiment.memory,
                    context=lambda: self.sessions[incident_id].tools.observations,
                )
            )
        if self.lessons is not None:
            tools["memory_write"] = lambda lesson, incident_outcome: self.lessons.put(
                lesson, incident_outcome=incident_outcome
            )
        return GuardedExecutor(HookManager(hooks, audit=self.audit), tools)

    def session(self, incident_id: str) -> Session:
        if incident_id not in self.sessions:
            path = f"{self.traces_dir}/{incident_id}.jsonl" if self.traces_dir else None
            recorder = Recorder(incident_id, path)
            executor = self.executor_for(incident_id)
            tools = IncidentTools(
                executor,
                incident_id,
                recorder,
                on_activity=None
                if self.on_activity is None
                else (lambda text: self.on_activity(incident_id, text)),
            )
            available = set(executor.tools)
            ctx = AgentContext(
                incident_id,
                executor,
                tools,
                self.models,
                self.experiment,
                self.config,
                available,
                recorder,
                self.lessons,
            )
            self.sessions[incident_id] = Session(executor, tools, recorder, ctx)
        return self.sessions[incident_id]


def _plan(state: dict, **statuses: str) -> dict:
    plan = dict(state.get("plan") or {})
    plan["steps"] = [{**s, "status": statuses.get(s["name"], s["status"])} for s in plan.get("steps", [])]
    return plan


def _close_remediation_plan(state: dict) -> dict:
    """Stop showing Propose as current once remediation is abandoned (blocked → escalate)."""
    statuses: dict[str, str] = {}
    for step in (state.get("plan") or {}).get("steps", []):
        name, status = step["name"], step["status"]
        if name == "propose" and status in ("running", "pending"):
            statuses[name] = "failed"
        elif name in ("approve", "act", "verify") and status in ("running", "pending"):
            statuses[name] = "skipped"
    return _plan(state, **statuses)


def _event(what: str, span: str | None = None) -> dict:
    return {"ts": _now(), "what": what, "span_id": span}


def build_graph(deps: GraphDeps, checkpointer=None, store=None):
    arch, budgets = deps.experiment.architecture, role_budgets(deps.experiment, deps.config)
    cfg = deps.config

    def s(state) -> Session:
        return deps.session(state["incident_id"])

    def update(state: dict, changes: dict) -> dict:
        if deps.on_update is not None:
            deps.on_update(state["incident_id"], {**state, **changes})
        return changes

    def trace(state, kind: str, **data) -> None:
        s(state).recorder.event(kind, **data)

    # ------------------------------------------------------------------ start
    def intake(state):
        trace(
            state,
            "incident",
            alert=state["alert"],
            experiment=deps.experiment.name,
            config=cfg["version"],
            models={role: deps.experiment.model_id(role, cfg) for role in ("commander", "specialist")},
        )
        return update(state, {"status": "investigating", "round": 0, "events": [_event("Alert received")]})

    def plan(state):
        alert = state["alert"]
        p = commander.make_plan(s(state).ctx, alert) if arch == "c2" else commander.fixed_plan(alert)
        data = p.model_dump()
        trace(state, "plan", plan=data)
        return update(state, {"plan": data, "plan_history": [data], "suspects": data["focus"]})

    # ------------------------------------------------------------------ investigate
    def triage(state):
        report = run_triage(s(state).ctx, state["alert"], budgets["triage"])
        suspects = clean_suspects(
            report.suspects + state.get("suspects", []), state["alert"].get("service", "")
        )
        trace(state, "triage", report=report.model_dump(), suspects=suspects)
        s(state).tools.call(  # bookkeeping, as the commander, so it does not spend triage's budget
            "commander",
            "incident_record_update",
            {
                "incident_id": state["incident_id"],
                "fields": {"affected_services": report.affected_services, "summary": report.summary[:300]},
            },
            cacheable=False,
        )
        return update(
            state,
            {
                "triage": report.model_dump(),
                "suspects": suspects,
                "plan": _plan(state, triage="done", diagnose="running"),
            },
        )

    def dispatch(state):
        if state["triage"].get("no_fault"):
            return "assess"
        suspects = state.get("suspects") or [state["alert"].get("service", "")]
        groups = [[svc] for svc in suspects] if deps.experiment.parallel else [suspects]
        base = {k: state[k] for k in ("incident_id", "alert", "triage", "round") if k in state}
        base["contradiction"] = state.get("contradiction", "")
        return [
            Send("diagnose", {**base, "assignment": group, "groups": len(groups), "index": i})
            for i, group in enumerate(groups)
        ]

    def diagnose(task):
        # Split the diagnosis budget; the remainder goes to the most likely suspects (5 over 3 is 2, 2, 1).
        whole, extra = divmod(budgets["diagnosis"], task.get("groups", 1))
        share = max(1, whole + (1 if task.get("index", 0) < extra else 0))
        report = run_diagnosis(
            deps.session(task["incident_id"]).ctx,
            task["alert"],
            task["assignment"],
            task["triage"],
            share,
            task.get("contradiction", ""),
        )
        return {"diagnoses": [{"round": task.get("round", 0), "report": report.model_dump()}]}

    def investigate(state):
        report = run_investigator(
            s(state).ctx, state["alert"], budgets["investigator"], state.get("contradiction", "")
        )
        if report is None:
            report_d = {
                "triage": {
                    "suspects": [state["alert"].get("service")],
                    "summary": "investigator did not finish",
                },
                "diagnosis": DiagnosisReport().model_dump(),
                "runbook_ids": [],
                "lessons": [],
            }
        else:
            report_d = report.model_dump()
        trace(state, "investigation", report=report_d)
        return update(
            state,
            {
                "investigation": report_d,
                "triage": report_d["triage"],
                "diagnoses": [{"round": state.get("round", 0), "report": report_d["diagnosis"]}],
                "plan": _plan(state, triage="done", diagnose="done"),
            },
        )

    def fixed(state):
        triage_d, diagnosis = fixed_investigation(s(state).tools, state["alert"])
        report = {
            "investigator": "fixed workflow",
            "no_fault": diagnosis["no_fault"],
            "hypotheses": diagnosis["hypotheses"],
            "evidence": diagnosis.get("evidence", []),
        }
        trace(state, "fixed_investigation", triage=triage_d, diagnosis=diagnosis)
        return update(
            state,
            {
                "triage": triage_d,
                "diagnoses": [{"round": state.get("round", 0), "report": report}],
                "plan": _plan(state, triage="done", diagnose="done"),
            },
        )

    # ------------------------------------------------------------------ decide
    def assess(state):
        sess, rnd = s(state), state.get("round", 0)
        reports = [DiagnosisReport(**d["report"]) for d in state.get("diagnoses", []) if d["round"] == rnd]
        if state.get("triage", {}).get("no_fault") and not reports:
            reports = [DiagnosisReport(no_fault=True, evidence=state["triage"].get("evidence", []))]
        hook_state = sess.executor.mgr.state(state["incident_id"])
        evidence = sess.tools.evidence | hook_state.evidence_ids
        diagnosis = merge(reports, evidence)
        resolved = set(state.get("resolved", []))
        obs = sess.tools.observations
        if diagnosis["no_fault"] and not diagnosis.get("evidence"):  # evidence triage cited, if any
            diagnosis["evidence"] = [e for e in state.get("triage", {}).get("evidence", []) if e in evidence]
        for h in diagnosis["hypotheses"]:
            link_flag(h, obs)
        for h in diagnosis["hypotheses"]:
            if h.get("flag") and obs.get(f"flag.{h['flag']}") is False and h["status"] == "supported":
                h["status"], h["rationale"] = "refuted", f"{h['flag']} is off. " + h.get("rationale", "")
        check = validate_diagnosis(
            diagnosis,
            evidence_ids=evidence,
            tool_calls_used=hook_state.tool_calls,
            tool_budget=deps.experiment.budget + cfg["budgets"]["action_reserve_tool_calls"],
        )
        open_h = [
            h for h in diagnosis["hypotheses"] if h["status"] == "supported" and _key(h) not in resolved
        ]
        if diagnosis["no_fault"] and "ungrounded_no_fault" in check.codes:
            nxt, contradiction = (
                "escalate",
                "A no-fault verdict cited no gathered evidence; a person decides.",
            )
        elif diagnosis["no_fault"]:
            nxt, contradiction = "no_fault", ""
        elif open_h:
            nxt, contradiction = "runbook", ""
            sess.executor.mgr.mark(state["incident_id"], "diagnosed")
        else:
            contradiction = state.get("contradiction") or "No hypothesis is supported by the evidence."
            if diagnosis["hypotheses"] and diagnosis["hypotheses"][0]["status"] == "refuted":
                contradiction = (
                    f"Top hypothesis refuted: {diagnosis['hypotheses'][0].get('rationale', '')[:200]}"
                )
            nxt = "replan" if arch != "c0" and rnd < cfg["budgets"]["max_replans"] else "escalate"
        trace(
            state,
            "assess",
            diagnosis=diagnosis,
            findings=sorted(check.codes),
            next=nxt,
            contradiction=contradiction,
        )
        events = [
            _event(
                f"Diagnosis round {rnd + 1}: " + (_describe(open_h[0]) if open_h else nxt),
                _span(open_h, sess),
            )
        ]
        return update(
            state,
            {
                "diagnosis": diagnosis,
                "next": nxt,
                "contradiction": contradiction,
                "events": events,
                "plan": _plan(state, diagnose="done"),
            },
        )

    def replan(state):
        sess = s(state)
        hook = sess.executor.replan(state["incident_id"], state.get("contradiction", ""))
        if not hook.ok:
            trace(state, "replan_refused", reason=hook.reason)
            return update(state, {"next": "escalate", "contradiction": f"replan refused: {hook.reason}"})
        history = state.get("plan_history", [])
        if arch == "c2":
            p = commander.replan(
                sess.ctx,
                state["alert"],
                history,
                state.get("contradiction", ""),
                state.get("diagnosis", {}).get("hypotheses", []),
            )
        else:
            p = commander.fixed_plan(
                state["alert"], len(history) + 1, f"Retry: {state.get('contradiction', '')}"
            )
        data = p.model_dump()
        done = {st["name"] for st in (state.get("plan") or {}).get("steps", []) if st["status"] == "done"} & {
            "triage"
        }
        data["steps"] = [
            {**st, "status": "done" if st["name"] in done else st["status"]} for st in data["steps"]
        ]
        trace(state, "plan", plan=data, replan=True)
        return update(
            state,
            {
                "plan": data,
                "plan_history": [data],
                "round": state.get("round", 0) + 1,
                "suspects": data["focus"],
                "next": "investigate",
                "events": [_event(f"Replanned (plan v{data['version']}): {data['reason'][:120]}")],
            },
        )

    def runbook(state):
        top = _target(state)
        if arch == "c2":
            advice = run_runbook(s(state).ctx, top, budgets["runbook"]).model_dump()
        elif arch == "c1":
            inv = state.get("investigation") or {}
            advice = {
                "runbook_ids": inv.get("runbook_ids", []),
                "lessons": inv.get("lessons", []),
                "recommended_action": None,
                "unsafe_steps": [],
                "notes": "from the investigator's report",
            }
        else:
            ok, result, _ = s(state).tools.call(
                "runbook", "runbook_search", {"query": f"{top['service']} {top['fault_type']}"}
            )
            advice = {
                "runbook_ids": [r["id"] for r in result] if ok and isinstance(result, list) else [],
                "lessons": [],
                "recommended_action": None,
                "unsafe_steps": [],
                "notes": "fixed lookup",
            }
        trace(state, "runbook", advice=advice)
        return update(state, {"runbook": advice, "plan": _plan(state, runbook="done", propose="running")})

    # ------------------------------------------------------------------ act safely
    def propose(state):
        sess, top = s(state), _target(state)
        flags = sess.tools.observations
        executable = tuple(a for a, tool in OPS_TOOL.items() if tool in deps.ops.tools())
        action, rationale = None, ""
        if arch == "c0":  # the fixed rule: switch off the flag of the top supported hypothesis
            action = (
                {"type": "set_flag", "args": {"flag": top["flag"], "enabled": False}}
                if top.get("flag")
                else None
            )
            rationale = top.get("rationale", "")
        else:
            proposal = run_remediation(
                sess.ctx,
                top,
                state.get("runbook", {}),
                {k: v for k, v in flags.items() if k.startswith("flag.")},
                state.get("edit_note", ""),
                executable,
            )
            if proposal is not None:
                action, rationale = proposal.action.to_action(), proposal.rationale
        if action is None:
            return update(state, _blocked(state, None, ["no_action_proposed"], "No action was proposed."))
        if action.get("type") not in executable:
            # Models still suggest restart/scale/rollback; only set_flag is wired in this deploy.
            return update(
                state,
                _blocked(
                    state,
                    action,
                    ["dry_run_missing"],
                    f"{action.get('type')} is not available in this deployment",
                ),
            )
        ok, dry, reason = sess.tools.call("remediation", "ops_dry_run", {"action": action}, cacheable=False)
        dry = dry if ok and isinstance(dry, dict) else {"ok": False, "detail": reason}
        plan_dict = build_plan(
            top, action, rationale, dry, cfg["verification"]["effects"], cfg["verification"]
        )
        hook_state = sess.executor.mgr.state(state["incident_id"])
        checked = validate_plan(
            plan_dict,
            diagnosis=_open_diagnosis(state),
            triage=state.get("triage"),
            quarantined_evidence=hook_state.quarantined_ids,
            previous_state=dry.get("previous_state"),
        )
        if checked.blocked:
            return update(state, _blocked(state, action, sorted(checked.codes), dry.get("detail", "")))
        severity = severity_from_policy(_signals(state))
        submitted = deps.approvals.submit_action(state["incident_id"], checked, severity)
        if submitted.blocked:
            return update(state, _blocked(state, action, sorted(submitted.codes), "approval request refused"))
        req = submitted.sanitized
        proposal = {
            "request_id": req.request_id,
            "confirmation_code": req.confirmation_code,
            "command": req.command,
            "rollback_command": req.rollback_command,
            "review_card": req.review_card(),
            "severity": severity,
            "action": action,
            "rollback": plan_dict["rollback"],
            "expected_effect": plan_dict["expected_effect"],
            "hypothesis": top,
            "rationale": rationale,
            "required_approvals": req.required_approvals,
        }
        trace(state, "proposal", proposal={k: v for k, v in proposal.items() if k != "review_card"})
        return update(
            state,
            {
                "proposal": proposal,
                "status": "waiting_approval",
                "next": "approve",
                "proposals": [{"action": action, "blocked": False, "codes": [], "severity": severity}],
                "events": [_event(f"Proposed: {req.command}")],
                "plan": _plan(state, propose="done", approve="running"),
            },
        )

    def _blocked(state, action, codes, detail):
        trace(state, "proposal_blocked", action=action, codes=codes, detail=detail)
        nxt = (
            "replan" if arch != "c0" and state.get("round", 0) < cfg["budgets"]["max_replans"] else "escalate"
        )
        out = {
            "next": nxt,
            "contradiction": f"Proposal refused ({', '.join(codes)}): {detail}"[:300],
            "proposals": [{"action": action, "blocked": True, "codes": codes}],
            "events": [_event("Proposal refused by the guardrails: " + ", ".join(codes))],
        }
        if nxt == "escalate":
            out["plan"] = _close_remediation_plan(state)
        return out

    def approve(state):
        proposal = state["proposal"]
        decision = (
            interrupt(
                {
                    "kind": "action",
                    **{
                        k: proposal[k]
                        for k in (
                            "request_id",
                            "command",
                            "rollback_command",
                            "confirmation_code",
                            "severity",
                            "review_card",
                            "required_approvals",
                        )
                    },
                    "hypothesis": proposal["hypothesis"],
                }
            )
            or {}
        )
        trace(
            state,
            "decision",
            about="action",
            decision={k: v for k, v in decision.items() if k != "confirmation"},
        )
        req_id = proposal["request_id"]
        if deps.approvals.get(req_id) is None:  # lost in a restart: propose again
            return update(state, {"next": "propose", "edit_note": ""})
        choice, who = decision.get("decision"), decision.get("approver") or "oncall"
        if choice == "approve":
            result = deps.approvals.approve(req_id, who, decision.get("confirmation", ""))
            if result.blocked or result.decision is Decision.REQUIRE_APPROVAL:
                codes = sorted(result.codes)
                return update(
                    state,
                    {"next": "approve", "events": [_event("Approval not complete: " + ", ".join(codes))]},
                )
            return update(
                state,
                {
                    "next": "act",
                    "status": "acting",
                    "events": [_event(f"Approved by {who}")],
                    "plan": _plan(state, approve="done", act="running"),
                },
            )
        if choice == "edit":
            deps.approvals.cancel(req_id, "edited by engineer: approval cancelled")
            return update(
                state,
                {
                    "next": "propose",
                    "edit_note": decision.get("text", ""),
                    "status": "investigating",
                    "events": [_event("Engineer edited the proposal; approval cancelled")],
                },
            )
        deps.approvals.reject(req_id, who, decision.get("text") or "rejected")
        nxt = (
            "replan" if arch != "c0" and state.get("round", 0) < cfg["budgets"]["max_replans"] else "escalate"
        )
        return update(
            state,
            {
                "next": nxt,
                "contradiction": f"Engineer rejected the proposal: {decision.get('text', '')}",
                "events": [_event(f"Rejected by {who}: {decision.get('text', '')[:100]}")],
            },
        )

    def act(state):
        proposal = state["proposal"]
        args = {
            "action": proposal["action"],
            "approval_request_id": proposal["request_id"],
            "phase": "forward",
        }
        ok, result, reason = s(state).tools.call(
            "remediation", OPS_TOOL[proposal["action"]["type"]], args, cacheable=False
        )
        trace(state, "action", ok=ok, result=result, reason=reason)
        if not ok:
            return update(
                state,
                {
                    "next": "escalate",
                    "contradiction": f"Action failed: {reason}",
                    "events": [_event(f"Action failed: {reason}")],
                },
            )
        return update(
            state,
            {
                "next": "verify",
                "events": [_event(f"Executed: {proposal['command']}")],
                "plan": _plan(state, act="done", verify="running"),
            },
        )

    def verify(state):
        sess, proposal = s(state), state["proposal"]
        effect, service = proposal["expected_effect"], proposal["hypothesis"]["service"]
        if effect["metric"] == "copilot:kafka_consumer_lag":
            service = "accounting"
        samples: list = []
        window = cfg["verification"]
        # Sample through the verification window; stop once the effect has held for sustain_samples readings.
        for i in range(max(effect["sustain_samples"], window["window_s"] // window["interval_s"])):
            deps.sleep(window["interval_s"])
            query = {"query": f'{effect["metric"]}{{service="{service}"}}', "time": f"{_now()}#{i}"}
            ok, result, _ = sess.tools.call("remediation", "promql_query", query, cacheable=False)
            series = (result or {}).get("series") or [] if ok else []
            samples.append(series[0]["points"][-1][1] if series and series[0].get("points") else None)
            check = verify_recovery(effect, samples)
            if check.sanitized["recovered"]:
                break
        recovered = bool(check.sanitized["recovered"])
        deps.approvals.record_verification(proposal["request_id"], recovered)
        trace(state, "verification", samples=samples, recovered=recovered, codes=sorted(check.codes))
        verification = {
            "samples": samples,
            "recovered": recovered,
            "metric": effect["metric"],
            "service": service,
        }
        if not recovered:
            return update(
                state,
                {
                    "verification": verification,
                    "next": "rollback",
                    "events": [_event(f"Verification failed: {samples}")],
                },
            )
        sess.executor.mgr.mark(state["incident_id"], "recovered")
        # Hypotheses that blame the flag just fixed are the same root cause seen from another service.
        fixed_flag = proposal["action"]["args"].get("flag")
        hypotheses = state["diagnosis"]["hypotheses"]
        resolved_now = sorted(
            {_key(proposal["hypothesis"])}
            | {_key(h) for h in hypotheses if fixed_flag and h.get("flag") == fixed_flag}
        )
        remaining = [
            h
            for h in hypotheses
            if h["status"] == "supported"
            and _key(h) not in resolved_now
            and _key(h) not in state.get("resolved", [])
            and h.get("flag")  # only another flag is a second, actionable fault
        ]
        actions = sum(1 for p in state.get("proposals", []) if not p.get("blocked"))
        nxt = "propose" if remaining and actions < cfg["budgets"]["max_actions"] else "communicate"
        return update(
            state,
            {
                "verification": verification,
                "resolved": resolved_now,
                "next": nxt,
                "outcome": "resolved",
                "events": [_event(f"Verified recovery: {effect['metric']} {samples}")],
                "plan": _plan(state, verify="done"),
            },
        )

    def rollback(state):
        proposal = state["proposal"]
        rb = proposal["rollback"]
        if rb.get("type") != "noop":
            args = {"action": rb, "approval_request_id": proposal["request_id"], "phase": "rollback"}
            ok, _, reason = s(state).tools.call("remediation", OPS_TOOL[rb["type"]], args, cacheable=False)
            trace(state, "rollback", ok=ok, reason=reason)
        halted = s(state).executor.mgr.state(state["incident_id"]).halted
        nxt = (
            "replan"
            if arch != "c0" and not halted and state.get("round", 0) < cfg["budgets"]["max_replans"]
            else "escalate"
        )
        return update(
            state,
            {
                "next": nxt,
                "outcome": "rolled_back",
                "contradiction": f"The action did not recover {proposal['hypothesis']['service']}; rolled back.",
                "events": [_event(f"Rolled back: {proposal['rollback_command']}")],
            },
        )

    def escalate(state):
        reason = state.get("contradiction") or "escalated"
        trace(state, "escalate", reason=reason)
        outcome = "resolved" if state.get("resolved") else "escalated"
        return update(
            state,
            {
                "status": "escalated" if outcome == "escalated" else "resolved",
                "outcome": outcome,
                "plan": _close_remediation_plan(state),
                "events": [_event(f"Escalated to the on-call engineer: {reason[:150]}")],
            },
        )

    def no_fault(state):
        trace(state, "no_fault", evidence=state["diagnosis"].get("evidence", []))
        return update(
            state,
            {
                "outcome": "no_action",
                "status": "closed_no_action",
                "events": [_event("No fault found; no action taken")],
            },
        )

    # ------------------------------------------------------------------ tell people
    def communicate(state):
        sess = s(state)
        outcome = state.get("outcome") or "escalated"
        severity = severity_from_policy(_signals(state))
        incident = {
            "service": state["alert"].get("service"),
            "alert": state["alert"],
            "hypotheses": state.get("diagnosis", {}).get("hypotheses", [])[:3],
            "actions": state.get("proposals", []),
            "verification": state.get("verification"),
        }
        timeline = _timeline(state, sess)
        draft = None if arch == "c0" else run_comms(sess.ctx, incident, outcome, timeline)
        draft = draft or template_draft(incident, outcome, severity)
        verified = outcome == "resolved"
        internal = {**draft.internal.model_dump(), "verified": verified}
        sess.tools.call(
            "comms", "status_draft", {"incident_id": state["incident_id"], "note": internal}, cacheable=False
        )
        external = None if draft.external is None else {**draft.external.model_dump(), "verified": verified}
        ext_check = None if external is None else validate_status_note(external, incident_verified=verified)
        postmortem = {
            "summary": draft.summary,
            "impact": draft.impact,
            "timeline": timeline,
            "root_cause": draft.root_cause,
            "resolution": draft.resolution,
            "lessons": [lesson.model_dump() for lesson in draft.lessons],
            "action_items": draft.action_items,
        }
        pm_check = validate_postmortem(
            postmortem,
            incident_start=state["alert"].get("starts_at"),
            incident_end=_now(),
            known_span_ids=sess.tools.span_ids,
        )
        sess.tools.call(
            "comms",
            "postmortem_draft",
            {"incident_id": state["incident_id"], "postmortem": postmortem},
            cacheable=False,
        )
        comms = {
            "internal": internal,
            "external": external,
            "postmortem": postmortem,
            "severity": severity,
            "external_findings": [] if ext_check is None else sorted(ext_check.codes),
            "external_ok": ext_check is not None and not ext_check.blocked,
            "postmortem_findings": sorted(pm_check.codes),
        }
        trace(state, "comms", comms=comms)
        return update(
            state, {"comms": comms, "status": "waiting_review", "plan": _plan(state, communicate="running")}
        )

    def review(state):
        comms = state["comms"]
        decision = (
            interrupt(
                {
                    "kind": "comms",
                    "internal": comms["internal"],
                    "external": comms["external"],
                    "postmortem": comms["postmortem"],
                    "external_findings": comms["external_findings"],
                    "postmortem_findings": comms["postmortem_findings"],
                }
            )
            or {}
        )
        trace(
            state,
            "decision",
            about="comms",
            decision={k: v for k, v in decision.items() if k != "confirmation"},
        )
        choice = decision.get("decision")
        if choice == "edit" and comms["external"] is not None:
            external = {**comms["external"], "body": decision.get("text") or comms["external"]["body"]}
            check = validate_status_note(external, incident_verified=bool(external.get("verified")))
            changed = {
                **comms,
                "external": external,
                "external_findings": sorted(check.codes),
                "external_ok": not check.blocked,
            }
            return update(state, {"comms": changed, "next": "review"})
        published = False
        if choice == "approve" and comms["external_ok"]:
            published = _publish(state, comms, decision)
        status = state.get("status")
        return update(
            state,
            {
                "next": "learn",
                "status": "closed" if status == "waiting_review" else status,
                "comms": {**comms, "published": published},
                "plan": _plan(state, communicate="done"),
                "events": [_event("External status published" if published else "Status notes reviewed")],
            },
        )

    def _publish(state, comms, decision) -> bool:
        note = comms["external"]
        checked = validate_status_note(note, incident_verified=bool(note.get("verified")))
        req = deps.approvals.submit_external_comms(state["incident_id"], checked, comms["severity"])
        if req.blocked:
            return False
        request = req.sanitized
        approver = decision.get("comms_approver") or "incident-commander"
        approved = deps.approvals.approve(request.request_id, approver, request.confirmation_code)
        if approved.blocked:
            trace(state, "publish_refused", codes=sorted(approved.codes))
            return False
        ok, _, reason = s(state).tools.call(
            "comms",
            "status_publish_external",
            {"note": note, "approval_request_id": request.request_id},
            cacheable=False,
        )
        return ok

    def learn(state):
        lessons = state["comms"]["postmortem"].get("lessons") or []
        if not (deps.experiment.learn and deps.experiment.memory and deps.lessons is not None and lessons):
            trace(state, "learn_skipped", lessons=len(lessons))
            return update(state, {"plan": _plan(state, learn="skipped"), "status": _final(state)})
        decision = interrupt({"kind": "lessons", "lessons": lessons}) or {}
        trace(state, "decision", about="lessons", decision=decision)
        reviewed = []
        approved = set(decision.get("approve", [])) if decision.get("decision") == "approve" else set()
        outcome = "verified_recovery" if state.get("outcome") == "resolved" else "verified_failure"
        for i, lesson in enumerate(lessons):
            if i in approved or (decision.get("decision") == "approve" and not decision.get("approve")):
                record = {**lesson, "reviewed_by": decision.get("approver") or "oncall"}
                ok, _, reason = s(state).tools.call(
                    "memory", "memory_write", {"lesson": record, "incident_outcome": outcome}, cacheable=False
                )
                reviewed.append({"lesson": lesson["lesson"], "stored": ok, "reason": reason})
            else:
                reviewed.append(
                    {
                        "lesson": lesson["lesson"],
                        "stored": False,
                        "reason": decision.get("text") or "rejected by reviewer",
                    }
                )
        trace(state, "lessons_reviewed", reviewed=reviewed)
        return update(
            state, {"lessons_reviewed": reviewed, "plan": _plan(state, learn="done"), "status": _final(state)}
        )

    # ------------------------------------------------------------------ wiring
    g = StateGraph(IncidentGraphState)
    for name, fn in (
        ("intake", intake),
        ("plan", plan),
        ("assess", assess),
        ("replan", replan),
        ("runbook", runbook),
        ("propose", propose),
        ("approve", approve),
        ("act", act),
        ("verify", verify),
        ("rollback", rollback),
        ("escalate", escalate),
        ("no_fault", no_fault),
        ("communicate", communicate),
        ("review", review),
        ("learn", learn),
    ):
        g.add_node(name, fn)
    g.add_edge(START, "intake")
    g.add_edge("intake", "plan")
    if arch == "c2":
        g.add_node("triage", triage)
        g.add_node("diagnose", diagnose)
        g.add_edge("plan", "triage")
        g.add_conditional_edges("triage", dispatch, ["diagnose", "assess"])
        g.add_edge("diagnose", "assess")
        g.add_conditional_edges(
            "replan",
            lambda st: "escalate" if st["next"] == "escalate" else dispatch(st),
            ["diagnose", "assess", "escalate"],
        )
    else:
        name = "investigate" if arch == "c1" else "fixed"
        g.add_node(name, investigate if arch == "c1" else fixed)
        g.add_edge("plan", name)
        g.add_edge(name, "assess")
        g.add_conditional_edges(
            "replan", lambda st: "escalate" if st["next"] == "escalate" else name, [name, "escalate"]
        )
    route = lambda st: st["next"]  # noqa: E731
    g.add_conditional_edges("assess", route, ["runbook", "replan", "escalate", "no_fault"])
    g.add_edge("runbook", "propose")
    g.add_conditional_edges("propose", route, ["approve", "replan", "escalate"])
    g.add_conditional_edges("approve", route, ["act", "approve", "propose", "replan", "escalate"])
    g.add_conditional_edges("act", route, ["verify", "escalate"])
    g.add_conditional_edges("verify", route, ["propose", "communicate", "rollback"])
    g.add_conditional_edges("rollback", route, ["replan", "escalate"])
    g.add_edge("escalate", "communicate")
    g.add_edge("no_fault", "communicate")
    g.add_edge("communicate", "review")
    g.add_conditional_edges("review", route, ["review", "learn"])
    g.add_edge("learn", END)
    return g.compile(checkpointer=checkpointer, store=store)


# ---------------------------------------------------------------------- helpers
def link_flag(h: dict, observations: dict) -> None:
    """Name the flag for a hypothesis that has none, when exactly one flag that is on injects that
    fault type into that service (fault catalogue). The link is written into the rationale."""
    if h.get("flag"):
        return
    linked = [
        flag
        for flag, fault in FLAG_FAULT_TYPE.items()
        if fault == h["fault_type"]
        and h["service"] in FLAG_SERVICE_MAP[flag]
        and observations.get(f"flag.{flag}")
    ]
    if len(linked) == 1:
        h["flag"] = linked[0]
        h["rationale"] = (
            f"Linked to {linked[0]}: it is on and injects {h['fault_type']} into {h['service']}. "
            + h.get("rationale", "")
        )


def _key(h: dict) -> str:
    return f"{h.get('service')}/{h.get('fault_type')}/{h.get('flag')}"


def _describe(h: dict) -> str:
    return f"{h['service']} {h['fault_type']}" + (f" ({h['flag']})" if h.get("flag") else "")


def _span(hypotheses: list[dict], sess: Session) -> str | None:
    for h in hypotheses:
        for e in h.get("evidence", []):
            if e.startswith("span:"):
                return e[5:]
    return next(iter(sorted(sess.tools.span_ids)), None)


def _open_diagnosis(state: dict) -> dict:
    """The diagnosis without hypotheses already fixed and verified, re-ranked 1..n. A second fault
    in a two-fault incident becomes the top hypothesis once the first is resolved."""
    resolved = set(state.get("resolved", []))
    open_h = [h for h in state["diagnosis"]["hypotheses"] if _key(h) not in resolved]
    return {**state["diagnosis"], "hypotheses": [{**h, "rank": i + 1} for i, h in enumerate(open_h)]}


def _target(state: dict) -> dict:
    hypotheses = _open_diagnosis(state)["hypotheses"]
    return next((h for h in hypotheses if h["status"] == "supported"), hypotheses[0])


def _signals(state: dict) -> dict:
    t = state.get("triage") or {}
    return {
        "error_rate": float(t.get("error_rate") or 0.0),
        "p99_latency_ms": float(t.get("p99_latency_ms") or 0.0),
        "affected_services": t.get("affected_services") or [],
        "availability_down": bool(t.get("availability_down")),
    }


def _timeline(state: dict, sess: Session) -> list[dict]:
    """Postmortem timeline from the incident's events. An entry without an observed span keeps
    span_id None, and validate_postmortem reports it rather than the timeline inventing one."""
    fallback = next(iter(sorted(sess.tools.span_ids)), None)
    alert_ts = state["alert"].get("starts_at") or _now()
    out = []
    for i, ev in enumerate(state.get("events", [])):
        ts = alert_ts if i == 0 else ev["ts"]
        out.append({"ts": ts, "event": ev["what"], "span_id": ev.get("span_id") or fallback})
    return out


def _final(state: dict) -> str:
    return {"resolved": "resolved", "no_action": "closed_no_action"}.get(
        state.get("outcome", ""), "escalated"
    )
