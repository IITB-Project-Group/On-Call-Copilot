"""
hooks.py — L14 lifecycle hooks around every tool and model call of the On-Call Copilot.

    agent ──► GuardedExecutor.call_tool ──► PRE_TOOL_USE hooks ──► tool ──► POST_TOOL_USE hooks ──► agent
                                             (deny / halt / modify)          (sanitise / count / loop)

Hooks (lower priority number runs first):
  KillSwitchHook (0)        env ONCALL_COPILOT_KILL_SWITCH=1 stops everything, even rollbacks
  WallClockHook (5)         incident time budget
  ToolCallLimitHook (10)    tool-call budget per incident and per role; repeated blocked calls halt
  CostLimitHook (15)        model + tool cost cap, checked BEFORE spending (estimate) and charged after
  LoopDetectionHook (20)    identical repeats, A/B oscillation, calls that add no new evidence
  GuardrailHook (30)        output_guardrails.check_tool_call: role allow-list, typed args, approval gate
  TelemetrySanitizerHook(5) POST: input_guardrails on every telemetry result before the agent sees it
  ReplanLimitHook / RollbackLimitHook  cap replans; repeated rollbacks halt the incident

A halted incident refuses every call except an approved ROLLBACK (so a failed fix can always be undone);
only the kill switch stops rollbacks too. Every decision is counted (``hook.decisions``), traced
(span ``hooks.<event>``) and written to the audit log.
"""
from __future__ import annotations

import os
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Iterable

from guardrail_core import TELEMETRY, canonical_json, sha256_hex, start_span


# ============================================================================
# Events, verdicts, context, state
# ============================================================================
class HookEvent(str, Enum):
    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"
    PRE_MODEL_CALL = "pre_model_call"
    POST_MODEL_CALL = "post_model_call"
    ON_REPLAN = "on_replan"
    ON_ROLLBACK = "on_rollback"


class HookVerdict(str, Enum):
    CONTINUE = "continue"
    MODIFY = "modify"
    DENY = "deny"      # refuse this call; the incident goes on
    HALT = "halt"      # refuse and stop the incident (escalate to a human)


@dataclass
class HookDecision:
    verdict: HookVerdict = HookVerdict.CONTINUE
    reason: str = ""
    changes: dict[str, Any] = field(default_factory=dict)
    hook: str = ""


CONTINUE = HookDecision()


@dataclass
class HookContext:
    event: HookEvent
    incident_id: str
    role: str | None = None
    tool: str | None = None
    args: dict[str, Any] = field(default_factory=dict)
    result: Any = None
    est_cost_usd: float = 0.0
    model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    usage: dict[str, Any] = field(default_factory=dict)

    @property
    def phase(self) -> str:
        return str((self.args or {}).get("phase", "forward"))


@dataclass
class IncidentState:
    incident_id: str
    started: float
    tool_calls: int = 0
    per_role: dict[str, int] = field(default_factory=dict)
    blocked_attempts: int = 0
    cost_usd: float = 0.0
    replans: int = 0
    rollbacks: int = 0
    halted: bool = False
    halt_reason: str = ""
    killed: bool = False
    evidence_ids: set[str] = field(default_factory=set)
    quarantined_ids: set[str] = field(default_factory=set)
    no_progress: int = 0
    recent: deque = field(default_factory=lambda: deque(maxlen=16))
    marks: dict[str, float] = field(default_factory=dict)


class Hook:
    name: str = "hook"
    priority: int = 50
    events: frozenset[HookEvent] = frozenset()

    def __call__(self, ctx: HookContext, state: IncidentState) -> HookDecision:  # pragma: no cover
        return CONTINUE

    # helpers
    def deny(self, reason: str) -> HookDecision:
        return HookDecision(HookVerdict.DENY, reason, hook=self.name)

    def halt(self, reason: str) -> HookDecision:
        return HookDecision(HookVerdict.HALT, reason, hook=self.name)

    def modify(self, **changes: Any) -> HookDecision:
        return HookDecision(HookVerdict.MODIFY, "", changes, hook=self.name)


# ============================================================================
# Manager
# ============================================================================
class HookManager:
    def __init__(self, hooks: Iterable[Hook], *, audit: Any = None, clock: Callable[[], float] = time.monotonic) -> None:
        self.hooks = sorted(hooks, key=lambda h: h.priority)
        self.audit, self.clock = audit, clock
        self.kill_switch = False
        self._states: dict[str, IncidentState] = {}

    def state(self, incident_id: str) -> IncidentState:
        st = self._states.get(incident_id)
        if st is None:
            st = self._states[incident_id] = IncidentState(incident_id, self.clock())
        return st

    def halt(self, incident_id: str, reason: str) -> None:
        st = self.state(incident_id)
        if not st.halted:
            st.halted, st.halt_reason = True, reason
            TELEMETRY.inc("agent.incidents_halted", reason=reason.split(":")[0][:40])
            self._audit("hook.halt", {"incident_id": incident_id, "reason": reason})

    def mark(self, incident_id: str, milestone: str) -> None:
        """Record diagnosed / recovered milestones -> agent.time_to_diagnose / time_to_recover."""
        st = self.state(incident_id)
        if milestone in st.marks:
            return
        st.marks[milestone] = self.clock()
        elapsed = st.marks[milestone] - st.started
        if milestone == "diagnosed":
            TELEMETRY.observe("agent.time_to_diagnose", elapsed)
        elif milestone == "recovered":
            TELEMETRY.observe("agent.time_to_recover", elapsed)
        self._audit("hook.milestone", {"incident_id": incident_id, "milestone": milestone, "elapsed_s": elapsed})

    def _audit(self, event: str, data: dict) -> None:
        if self.audit is not None:
            self.audit.append(event, data)

    def _rollback_exempt(self, ctx: HookContext) -> bool:
        return ctx.event is HookEvent.PRE_TOOL_USE and ctx.phase == "rollback"

    def run(self, ctx: HookContext) -> HookDecision:
        st = self.state(ctx.incident_id)
        with start_span(f"hooks.{ctx.event.value}") as span:
            span.set_attribute("hook.event", ctx.event.value)
            span.set_attribute("hook.tool", str(ctx.tool or ""))
            span.set_attribute("hook.role", str(ctx.role or ""))
            final = self._run(ctx, st)
            span.set_attribute("hook.verdict", final.verdict.value)
            span.set_attribute("hook.reason", final.reason[:120])
        if final.verdict is not HookVerdict.CONTINUE or ctx.event is not HookEvent.POST_TOOL_USE:
            self._audit(f"hook.{ctx.event.value}", {"incident_id": ctx.incident_id, "role": ctx.role, "tool": ctx.tool,
                                                    "verdict": final.verdict.value, "reason": final.reason,
                                                    "hook": final.hook})
        return final

    def _run(self, ctx: HookContext, st: IncidentState) -> HookDecision:
        pre = ctx.event in (HookEvent.PRE_TOOL_USE, HookEvent.PRE_MODEL_CALL, HookEvent.ON_REPLAN)
        if self.kill_switch:
            st.killed = True
            self.halt(ctx.incident_id, "kill_switch")
            return HookDecision(HookVerdict.HALT, "kill_switch", hook="manager")
        if pre and st.halted and not self._rollback_exempt(ctx):
            return HookDecision(HookVerdict.HALT, f"incident_halted: {st.halt_reason}", hook="manager")
        if ctx.event is HookEvent.ON_ROLLBACK:
            st.rollbacks += 1
        if ctx.event is HookEvent.ON_REPLAN:
            st.replans += 1
        final = HookDecision()
        for h in self.hooks:
            if ctx.event not in h.events:
                continue
            if self._rollback_exempt(ctx) and not isinstance(h, (KillSwitchHook, GuardrailHook)):
                continue  # budgets / loops never prevent undoing a failed fix
            try:
                d = h(ctx, st) or CONTINUE
            except Exception as e:  # fail closed before the call, withhold data after it
                TELEMETRY.inc("hook.errors", hook=h.name)
                if pre:
                    return HookDecision(HookVerdict.DENY, f"hook_error:{h.name}:{type(e).__name__}", hook=h.name)
                ctx.result = {"error": "post-processing failed; result withheld"}
                return HookDecision(HookVerdict.MODIFY, f"hook_error:{h.name}", hook=h.name)
            TELEMETRY.inc("hook.decisions", hook=h.name, verdict=d.verdict.value)
            if d.verdict is HookVerdict.MODIFY:
                for k, v in d.changes.items():
                    setattr(ctx, k, v)
                final = HookDecision(HookVerdict.MODIFY, d.reason, dict(d.changes), h.name)
            elif d.verdict in (HookVerdict.DENY, HookVerdict.HALT):
                if d.verdict is HookVerdict.HALT:
                    self.halt(ctx.incident_id, d.reason)
                return d
        return final


# ============================================================================
# Hooks
# ============================================================================
class KillSwitchHook(Hook):
    name, priority = "kill_switch", 0
    events = frozenset({HookEvent.PRE_TOOL_USE, HookEvent.PRE_MODEL_CALL, HookEvent.ON_REPLAN})

    def __init__(self, env_var: str = "ONCALL_COPILOT_KILL_SWITCH") -> None:
        self.env_var = env_var

    def __call__(self, ctx: HookContext, state: IncidentState) -> HookDecision:
        if os.environ.get(self.env_var, "").strip().lower() in {"1", "true", "yes", "on"}:
            state.killed = True
            return self.halt("kill_switch")
        return CONTINUE


class WallClockHook(Hook):
    name, priority = "wall_clock", 5
    events = frozenset({HookEvent.PRE_TOOL_USE, HookEvent.PRE_MODEL_CALL})

    def __init__(self, max_s: float = 1800, clock: Callable[[], float] = time.monotonic) -> None:
        self.max_s, self.clock = max_s, clock

    def __call__(self, ctx: HookContext, state: IncidentState) -> HookDecision:
        if self.clock() - state.started > self.max_s:
            return self.halt("wall_clock_exceeded")
        return CONTINUE


class ToolCallLimitHook(Hook):
    name, priority = "tool_call_limit", 10
    events = frozenset({HookEvent.PRE_TOOL_USE})

    def __init__(self, max_calls: int = 10, per_role: dict[str, int] | None = None, max_blocked: int | None = 5) -> None:
        self.max_calls, self.per_role, self.max_blocked = max_calls, per_role or {}, max_blocked

    def __call__(self, ctx: HookContext, state: IncidentState) -> HookDecision:
        if self.max_blocked is not None and state.blocked_attempts >= self.max_blocked:
            return self.halt(f"too_many_blocked_attempts: {state.blocked_attempts}")
        if state.tool_calls >= self.max_calls:
            return self.halt(f"tool_budget_exhausted: {state.tool_calls}/{self.max_calls}")
        cap = self.per_role.get(str(ctx.role))
        if cap is not None and state.per_role.get(str(ctx.role), 0) >= cap:
            return self.deny(f"role_budget_exhausted: {ctx.role} {cap}")
        return CONTINUE


DEFAULT_PRICING = {
    "default": {"input_per_mtok": 3.0, "output_per_mtok": 15.0},          # conservative upper bound
    "gpt-4.1-mini": {"input_per_mtok": 0.40, "output_per_mtok": 1.60},
    "openai/gpt-4.1-mini": {"input_per_mtok": 0.40, "output_per_mtok": 1.60},
}


class CostLimitHook(Hook):
    name, priority = "cost_limit", 15
    events = frozenset({HookEvent.PRE_TOOL_USE, HookEvent.POST_TOOL_USE, HookEvent.PRE_MODEL_CALL,
                        HookEvent.POST_MODEL_CALL})

    def __init__(self, max_usd: float = 0.50, pricing: dict[str, dict[str, float]] | None = None) -> None:
        self.max_usd = max_usd
        self.pricing = pricing or DEFAULT_PRICING

    def price(self, model: str | None, input_tokens: int, output_tokens: int) -> float:
        p = self.pricing.get(model or "default") or self.pricing.get("default") or DEFAULT_PRICING["default"]
        return (input_tokens * p["input_per_mtok"] + output_tokens * p["output_per_mtok"]) / 1_000_000

    def __call__(self, ctx: HookContext, state: IncidentState) -> HookDecision:
        if ctx.event is HookEvent.PRE_TOOL_USE:
            if state.cost_usd + max(0.0, ctx.est_cost_usd) > self.max_usd + 1e-12:
                return self.halt("cost_budget_exhausted")
        elif ctx.event is HookEvent.POST_TOOL_USE:
            if ctx.est_cost_usd:
                state.cost_usd += ctx.est_cost_usd
                TELEMETRY.inc("agent.cost_usd", ctx.est_cost_usd, role=str(ctx.role))
        elif ctx.event is HookEvent.PRE_MODEL_CALL:
            est = self.price(ctx.model, ctx.input_tokens, ctx.output_tokens)
            if state.cost_usd + est > self.max_usd + 1e-12:
                return self.halt(f"cost_budget_exhausted: ${state.cost_usd:.4f} + est ${est:.4f} > ${self.max_usd}")
        elif ctx.event is HookEvent.POST_MODEL_CALL:
            u = ctx.usage or {}
            cost = self.price(ctx.model, int(u.get("input_tokens", 0)), int(u.get("output_tokens", 0)))
            state.cost_usd += cost
            TELEMETRY.inc("agent.cost_usd", cost, role=str(ctx.role))
        return CONTINUE


class LoopDetectionHook(Hook):
    name, priority = "loop_detection", 20
    events = frozenset({HookEvent.PRE_TOOL_USE, HookEvent.POST_TOOL_USE})

    def __init__(self, repeat_threshold: int = 3, oscillation_cycles: int = 3,
                 max_calls_without_progress: int | None = None) -> None:
        self.repeat_threshold, self.oscillation_cycles = repeat_threshold, oscillation_cycles
        self.max_no_progress = max_calls_without_progress

    def __call__(self, ctx: HookContext, state: IncidentState) -> HookDecision:
        if ctx.event is HookEvent.PRE_TOOL_USE:
            sig = sha256_hex(canonical_json([ctx.role, ctx.tool, ctx.args]))[:16]
            seq = list(state.recent) + [sig]
            if seq.count(sig) >= self.repeat_threshold:
                TELEMETRY.inc("agent.loops_detected", kind="repeat")
                return self.halt("loop_repeat")
            n = 2 * self.oscillation_cycles
            tail = seq[-n:]
            if len(tail) == n and len(set(tail)) == 2 and all(tail[i] != tail[i + 1] for i in range(n - 1)):
                TELEMETRY.inc("agent.loops_detected", kind="oscillation")
                return self.halt("loop_oscillation")
            state.recent.append(sig)
            return CONTINUE
        # POST: progress = new evidence ids (recorded by the sanitiser, which runs first)
        if self.max_no_progress is not None:
            before = getattr(ctx, "_evidence_before", None)
            if before is not None and len(state.evidence_ids) > before:
                state.no_progress = 0
            else:
                state.no_progress += 1
                if state.no_progress >= self.max_no_progress:
                    TELEMETRY.inc("agent.loops_detected", kind="no_progress")
                    return self.halt("no_progress")
        return CONTINUE


class ReplanLimitHook(Hook):
    name, priority = "replan_limit", 25
    events = frozenset({HookEvent.ON_REPLAN})

    def __init__(self, max_replans: int = 3) -> None:
        self.max_replans = max_replans

    def __call__(self, ctx: HookContext, state: IncidentState) -> HookDecision:
        if state.replans > self.max_replans:
            return self.halt("replan_limit")
        TELEMETRY.inc("agent.replans")
        return CONTINUE


class RollbackLimitHook(Hook):
    name, priority = "rollback_limit", 25
    events = frozenset({HookEvent.ON_ROLLBACK})

    def __init__(self, max_rollbacks: int = 2) -> None:
        self.max_rollbacks = max_rollbacks

    def __call__(self, ctx: HookContext, state: IncidentState) -> HookDecision:
        if state.rollbacks >= self.max_rollbacks:
            TELEMETRY.inc("agent.repeated_rollbacks")
            return self.halt("repeated_rollbacks")
        return CONTINUE


class GuardrailHook(Hook):
    """Runs output_guardrails.check_tool_call (role allow-list, typed args, query limits, approval gate)."""

    name, priority = "guardrail", 30
    events = frozenset({HookEvent.PRE_TOOL_USE})

    def __init__(self, approval_gate: Any = None, previous_state: Callable[[str], dict] | None = None,
                 memory_frozen: Callable[[], bool] | bool = False) -> None:
        self.approval_gate, self.previous_state, self.memory_frozen = approval_gate, previous_state, memory_frozen
        self._pre_action_state: dict[str, dict] = {}   # incident -> state captured before the forward action

    def __call__(self, ctx: HookContext, state: IncidentState) -> HookDecision:
        from output_guardrails import check_tool_call

        is_ops = str(ctx.tool).startswith("ops_") and ctx.tool != "ops_dry_run"
        if is_ops and ctx.phase == "rollback" and ctx.incident_id in self._pre_action_state:
            prev = self._pre_action_state[ctx.incident_id]   # rollback must restore the state BEFORE the action
        else:
            prev = self.previous_state(ctx.incident_id) if self.previous_state else None
        frozen = self.memory_frozen() if callable(self.memory_frozen) else bool(self.memory_frozen)
        kw: dict[str, Any] = {"approval_gate": self.approval_gate, "previous_state": prev}
        if frozen:
            kw["memory_frozen"] = True
        r = check_tool_call(str(ctx.role), str(ctx.tool), ctx.args, **kw)
        if not r.blocked and is_ops and ctx.phase == "forward" and prev is not None:
            self._pre_action_state[ctx.incident_id] = prev
        if r.blocked:
            code = next((f.code for f in r.findings if f.action.value == "block"), r.findings[0].code if r.findings else "blocked")
            return self.deny(f"guardrail:{code}")
        return CONTINUE


_TELEMETRY_TOOLS = {"log_search": "check_logs", "trace_search": "check_traces", "trace_get": "check_traces",
                    "promql_query": "check_metrics", "promql_range_query": "check_metrics",
                    "recent_changes": "check_changes"}


def _collect_ids(obj: Any, out: set[str]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "evidence_id" and isinstance(v, str):
                out.add(v)
            else:
                _collect_ids(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _collect_ids(v, out)


class TelemetrySanitizerHook(Hook):
    """POST_TOOL_USE: telemetry is DATA. Redact, wrap, quarantine before any agent (or model) sees it."""

    name, priority = "telemetry_sanitizer", 5
    events = frozenset({HookEvent.POST_TOOL_USE})

    def __init__(self, input_guardrails: Any) -> None:
        self.ig = input_guardrails

    def __call__(self, ctx: HookContext, state: IncidentState) -> HookDecision:
        ctx._evidence_before = len(state.evidence_ids)  # type: ignore[attr-defined]
        tool, res = str(ctx.tool), ctx.result
        method = _TELEMETRY_TOOLS.get(tool)
        if method:
            r = getattr(self.ig, method)(res)
            if r.blocked:
                return self.modify(result={"error": "blocked by input guardrail", "codes": sorted(r.codes)})
            clean = r.sanitized if isinstance(r.sanitized, dict) else {}
            ids: set[str] = set()
            _collect_ids(clean, ids)
            state.evidence_ids |= ids
            state.quarantined_ids |= set(clean.get("quarantined_ids") or [])
            return self.modify(result=clean)
        if isinstance(res, str):
            s = self.ig.screen_text(res, f"tool.{tool}", tool, f"{tool}:{sha256_hex(res)[:12]}", guardrail="tool_output")
            if s.quarantined:
                state.quarantined_ids.add(f"{tool}:{sha256_hex(res)[:12]}")
            return self.modify(result=s.wrapped)
        return CONTINUE


# ============================================================================
# Executor
# ============================================================================
@dataclass
class ToolOutcome:
    ok: bool
    result: Any = None
    verdict: HookVerdict = HookVerdict.CONTINUE
    reason: str = ""
    halted: bool = False


class GuardedExecutor:
    """The ONLY way agents reach tools or models. ``tools`` maps tool name -> callable(**args)."""

    def __init__(self, manager: HookManager, tools: dict[str, Callable[..., Any]]) -> None:
        self.mgr, self.tools = manager, tools

    def start_incident(self, incident_id: str) -> IncidentState:
        return self.mgr.state(incident_id)

    def end_incident(self, incident_id: str) -> IncidentState:
        st = self.mgr.state(incident_id)
        TELEMETRY.observe("agent.tool_calls_per_incident", st.tool_calls)
        TELEMETRY.inc("agent.incidents", outcome="halted" if st.halted else "completed")
        return st

    def call_tool(self, incident_id: str, role: str, tool: str, args: dict | None = None,
                  est_cost_usd: float = 0.0) -> ToolOutcome:
        st = self.mgr.state(incident_id)
        ctx = HookContext(HookEvent.PRE_TOOL_USE, incident_id, role=role, tool=tool, args=dict(args or {}),
                          est_cost_usd=est_cost_usd)
        d = self.mgr.run(ctx)
        if d.verdict in (HookVerdict.DENY, HookVerdict.HALT):
            st.blocked_attempts += 1
            TELEMETRY.inc("agent.tool_calls_blocked", role=role, reason=d.reason.split(":")[0][:40])
            return ToolOutcome(False, None, d.verdict, d.reason, st.halted)
        fn = self.tools.get(tool)
        if fn is None:
            return ToolOutcome(False, None, HookVerdict.DENY, "tool_not_available", st.halted)
        try:
            result = fn(**ctx.args)
        except Exception as e:
            TELEMETRY.inc("agent.tool_errors", tool=tool)
            return ToolOutcome(False, {"error": f"{type(e).__name__}"}, HookVerdict.DENY, f"tool_error:{type(e).__name__}",
                               st.halted)
        st.tool_calls += 1
        st.per_role[role] = st.per_role.get(role, 0) + 1
        post = HookContext(HookEvent.POST_TOOL_USE, incident_id, role=role, tool=tool, args=ctx.args, result=result,
                           est_cost_usd=est_cost_usd)
        pd = self.mgr.run(post)
        if ctx.phase == "rollback" and tool.startswith("ops_") and tool != "ops_dry_run":
            self.mgr.run(HookContext(HookEvent.ON_ROLLBACK, incident_id, role=role, tool=tool, args=ctx.args))
        halted = self.mgr.state(incident_id).halted
        return ToolOutcome(True, post.result, pd.verdict, pd.reason, halted)

    def call_model(self, incident_id: str, role: str, model: str, est_input_tokens: int, est_output_tokens: int,
                   fn: Callable[[], tuple[Any, dict]]) -> ToolOutcome:
        ctx = HookContext(HookEvent.PRE_MODEL_CALL, incident_id, role=role, model=model,
                          input_tokens=est_input_tokens, output_tokens=est_output_tokens)
        d = self.mgr.run(ctx)
        if d.verdict in (HookVerdict.DENY, HookVerdict.HALT):
            return ToolOutcome(False, None, d.verdict, d.reason, self.mgr.state(incident_id).halted)
        result, usage = fn()
        self.mgr.run(HookContext(HookEvent.POST_MODEL_CALL, incident_id, role=role, model=model, usage=usage or {}))
        return ToolOutcome(True, result, HookVerdict.CONTINUE, "", self.mgr.state(incident_id).halted)

    def replan(self, incident_id: str, reason: str = "") -> ToolOutcome:
        d = self.mgr.run(HookContext(HookEvent.ON_REPLAN, incident_id, args={"reason": reason}))
        ok = d.verdict not in (HookVerdict.DENY, HookVerdict.HALT)
        return ToolOutcome(ok, None, d.verdict, d.reason, self.mgr.state(incident_id).halted)


def default_hooks(*, input_guardrails: Any, approval_gate: Any = None,
                  previous_state: Callable[[str], dict] | None = None, max_tool_calls: int = 10,
                  max_cost_usd: float = 0.50, max_wall_clock_s: float = 1800, max_replans: int = 3,
                  max_rollbacks: int = 2, per_role: dict[str, int] | None = None,
                  max_calls_without_progress: int | None = None, memory_frozen: Callable[[], bool] | bool = False,
                  clock: Callable[[], float] = time.monotonic) -> list[Hook]:
    return [KillSwitchHook(), WallClockHook(max_wall_clock_s, clock), ToolCallLimitHook(max_tool_calls, per_role),
            CostLimitHook(max_cost_usd), LoopDetectionHook(max_calls_without_progress=max_calls_without_progress),
            GuardrailHook(approval_gate, previous_state, memory_frozen), TelemetrySanitizerHook(input_guardrails),
            ReplanLimitHook(max_replans), RollbackLimitHook(max_rollbacks)]
