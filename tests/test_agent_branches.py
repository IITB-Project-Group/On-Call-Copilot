"""Branches the main agent tests do not reach: memory off, edits with notes, restarts, live reads."""

from __future__ import annotations

import json
from types import SimpleNamespace

import agents_support as S
import httpx
import pytest
from hooks import GuardedExecutor, HookManager, default_hooks
from input_guardrails import InputGuardrails
from langgraph.checkpoint.memory import InMemorySaver
from output_guardrails import action_hash
from test_agent_graph import CASES, Scripted, run

from agents import settings
from agents.context import AgentContext
from agents.handoffs import TriageReport
from agents.llm import tool_call
from agents.memory.lessons import LessonStore
from agents.settings import Experiment
from agents.toolbox import SPECS, IncidentTools, RoleToolset
from eval import runner
from eval.runner import SimulatedEngineer, build_twin_run, drive
from eval.scenario import ShopTwin
from graph import live, trace_report
from graph.incident_graph import build_graph

IG = InputGuardrails()


def executor(tools=None, **kw):
    return GuardedExecutor(HookManager(default_hooks(input_guardrails=IG, **kw)), tools or {})


def test_model_arguments_become_hook_arguments():
    logs = SPECS["log_search"].to_hook({"query": "error", "service": "payment", "minutes": 10})
    assert logs["index"] == "otel-logs-payment" and logs["size"] == 20
    assert "status" not in SPECS["trace_search"].to_hook({"service": "ad", "errors_only": False})
    assert SPECS["recent_changes"].to_hook({})["lookback_s"] == 3600


def test_role_budget_refusal_reaches_the_model_as_an_error():
    ex = executor({"promql_query": lambda query, time=None: {}}, per_role={"triage": 0})
    toolset = RoleToolset(IncidentTools(ex, "i"), "triage", {"promql_query"})
    assert json.loads(toolset.call("promql_query", {"query": "up"}))["error"].startswith(
        "role_budget_exhausted"
    )


def test_context_runs_without_a_recorder_and_with_memory_off():
    exp = Experiment(memory=False)
    tools = IncidentTools(executor(), "i")
    ctx = AgentContext(
        "i",
        tools.executor,
        tools,
        S.models(exp),
        exp,
        settings.load_config(),
        {"memory_search"},
        lessons=LessonStore(guardrails=IG),
    )
    assert ctx.react("triage", "triage", {}, "t", TriageReport, None).output is not None
    ctx.experiment = Experiment()
    assert ctx.lesson_text() == "[]"


def test_live_reads_of_flags_and_one_trace(monkeypatch):
    from tools.actions import set_flag as flags_mod
    from tools.telemetry import client

    monkeypatch.setattr(
        flags_mod,
        "_request",
        lambda *a, **k: {"flags": {"paymentFailure": {"defaultVariant": "50%"}, "bad": 1}},
    )
    assert flags_mod.read_flags() == {"paymentFailure": "50%"}
    monkeypatch.setattr(flags_mod, "_request", lambda *a, **k: {})
    with pytest.raises(flags_mod.FlagWriteError):
        flags_mod.read_flags()

    class Http:
        def __init__(self, status, payload=None, error=None):
            self.status, self.payload, self.error = status, payload, error

        def __call__(self, timeout=None):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, params=None):
            if self.error:
                raise self.error
            return SimpleNamespace(status_code=self.status, json=lambda: self.payload)

    trace = {
        "data": [
            {
                "processes": {"p": {"serviceName": "payment"}},
                "spans": [
                    {
                        "processID": "p",
                        "operationName": "charge",
                        "traceID": "a" * 32,
                        "spanID": "b" * 16,
                        "startTime": 5,
                        "references": [{"refType": "CHILD_OF", "spanID": "c" * 16}],
                        "tags": [{"key": "error", "value": True}],
                    }
                ],
            }
        ]
    }
    monkeypatch.setattr(client.httpx, "Client", Http(200, trace))
    assert client.get_trace("a" * 32).series[0]["parent_span_id"] == "c" * 16
    monkeypatch.setattr(client.httpx, "Client", Http(404))
    assert "HTTP 404" in client.get_trace("x").error
    monkeypatch.setattr(client.httpx, "Client", Http(200, error=httpx.ConnectError("refused")))
    assert "refused" in client.get_trace("x").error


def test_memory_off_and_an_edit_note_reach_the_team():
    exp = Experiment(name="c2", architecture="c2", memory=False, learn=False)
    state, deps, iid, _ = run(
        CASES["dev-f1-50pct"], exp, reviewer=Scripted({"decision": "edit", "text": "use the flag"})
    )
    assert deps.lessons is None and state["outcome"] == "resolved"


def test_lesson_writes_are_rejected_in_evaluation_runs():
    state, *_ = run(CASES["dev-f1-50pct"], Experiment(name="c2", architecture="c2"))
    assert state["lessons_reviewed"][0]["stored"] is False


def test_graph_runs_without_knowledge_and_reports_updates():
    exp = Experiment(name="c0", architecture="c0", learn=False)
    twin, deps, iid = build_twin_run(CASES["dev-f1-50pct"], exp)
    deps.knowledge, deps.lessons, seen = None, None, []
    deps.on_update = lambda incident_id, state: seen.append(state.get("status"))
    real = deps.backends["promql_query"]

    def flaky(query, time=None):
        if query == "copilot:container_cpu_ratio":
            raise RuntimeError("down")
        return real(query, time)

    deps.backends["promql_query"] = flaky
    state, _ = drive(build_graph(deps, InMemorySaver()), iid, twin.alert(), SimulatedEngineer())
    assert "investigating" in seen and state["runbook"]["runbook_ids"] == []


def test_a_no_fault_verdict_without_evidence_goes_to_a_person():
    def quiet(role, messages):
        return tool_call("submit", {"no_fault": True, "summary": "quiet"})

    state, *_ = run(
        CASES["dev-noise-startup-burst"],
        Experiment(name="c2", architecture="c2", learn=False),
        {"triage": quiet},
    )
    assert state["outcome"] == "escalated" and not state.get("proposals")


def test_a_restart_has_no_rollback_and_the_team_replans():
    def restart(role, messages):
        return tool_call(
            "submit",
            {
                "hypothesis_id": "h1",
                "rationale": "restart",
                "action": {"type": "restart_service", "service": "payment"},
            },
        )

    exp = Experiment(name="c2", architecture="c2", learn=False)
    twin, deps, iid = build_twin_run(CASES["dev-f1-50pct"], exp, models=S.models(exp, remediation=restart))

    class Ops:
        def snapshot(self, _=""):
            return {"flags": {}}

        def tools(self):
            return {
                "ops_dry_run": lambda action: {
                    "ok": True,
                    "command_hash": action_hash(action),
                    "previous_state": {},
                },
                "ops_restart_service": lambda action, approval_request_id, phase="forward": "restarted",
            }

    deps.ops = Ops()
    state, _ = drive(build_graph(deps, InMemorySaver()), iid, twin.alert(), SimulatedEngineer())
    assert state["proposals"][0]["action"]["type"] == "restart_service"
    assert state["outcome"] in ("escalated", "rolled_back") and len(state["plan_history"]) > 1


def test_remaining_runner_twin_and_report_branches(tmp_path):
    twin = ShopTwin(
        {
            "id": "x",
            "inject": [{"flag": "notAFlag", "variant": "on"}],
            "log_lines": [{"service": "frontend", "body": "hello"}],
        }
    )
    assert twin.readings()["error_ratio"]["payment"] == 0.002
    assert twin.log_search("otel-logs-payment", "*", "a", "b") == []
    assert (
        twin.write_flag("cartFailure", "off") == "cartFailure is off" and "cartFailure" not in twin.fixed_at
    )
    result = runner.run_experiment(Experiment(architecture="c0", learn=False), [CASES["dev-f3-10pct"]])
    assert result["summary"]["runs"] == 1
    assert (
        runner.main(
            [
                "--experiment",
                "eval/experiments/e1-c0-fixed.yaml",
                "--out",
                str(tmp_path / "h.jsonl"),
                "--split",
                "heldout",
                "--cases-dir",
                str(tmp_path),
            ]
        )
        == 0
    )
    assert live.build_live_agent(None, None, None, "x", {}) is None
    path = tmp_path / "t.jsonl"
    path.write_text(
        json.dumps(
            {"ts": 0, "incident": "i", "kind": "plan", "plan": {"version": 1, "focus": [], "reason": ""}}
        ),
        encoding="utf-8",
    )
    assert "Plan v1" in trace_report.render(path)


def test_short_metric_names_resolve_and_spent_budgets_are_refused_before_the_hooks():
    from agents.toolbox import parse_metric_query

    assert parse_metric_query('copilot:service_p95_latency_seconds{service="ad"}') == (
        "copilot:service_p95_latency_seconds:2m",
        "ad",
    )
    assert parse_metric_query("copilot:service") is None  # ambiguous: several metrics start with it
    tools = IncidentTools(executor({"promql_query": lambda query, time=None: {}}), "i")
    toolset = RoleToolset(tools, "triage", {"promql_query"}, budget=1)
    toolset.call("promql_query", {"query": "up"})
    assert "budget is used up" in toolset.call("promql_query", {"query": "down"})
    assert tools.executor.mgr.state("i").blocked_attempts == 0
