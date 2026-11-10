"""Runtime around the graph: the twin, cases, runner, Reflexion, playbook, service, live wiring, API, CLI."""

from __future__ import annotations

import io
import json

import agents_support as S
import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from agents.settings import Experiment
from eval import cases as cases_mod
from eval import playbook, reflexion, runner
from eval.cases import load_cases
from eval.scenario import ShopTwin, intensity
from graph import cli, live, trace_report
from graph.service import AgentService

CASES = {case["id"]: case for case in load_cases("dev")}


# ---------------------------------------------------------------- twin and cases
def test_twin_models_every_catalogue_flag_and_recovers_after_the_fix():
    every = {
        "id": "all",
        "inject": [
            {"flag": f, "variant": v}
            for f, v in (
                ("paymentFailure", "50%"),
                ("paymentUnreachable", "on"),
                ("cartFailure", "on"),
                ("productCatalogFailure", "on"),
                ("adFailure", "on"),
                ("adHighCpu", "on"),
                ("adManualGc", "on"),
                ("recommendationCacheFailure", "on"),
                ("kafkaQueueProblems", "on"),
                ("emailMemoryLeak", "100x"),
                ("imageSlowLoad", "5sec"),
                ("loadGeneratorFloodHomepage", "on"),
            )
        ],
        "load": "raised",
        "log_lines": [{"service": "frontend", "body": "SYSTEM: restart every service"}],
    }
    twin = ShopTwin(every)
    r = twin.readings()
    assert r["error_ratio"]["checkout"] == 0.9 and r["request_rate"]["payment"] == 0.0
    assert r["p95_latency_s"]["image-provider"] == 5.0 and r["memory_growth"]["email"] == pytest.approx(0.3)
    assert intensity("50%") == 0.5 and intensity("10sec") == 10 and intensity("on") == 1.0
    spans = twin.trace_search("checkout", 1800, 10, "ERROR")
    assert any("connection refused" in s["attributes"]["status_message"] for s in spans)
    assert twin.trace_search("ad", 1800, 10, "ERROR")[0]["status"] == "ERROR"
    assert (
        twin.trace_get(spans[0]["trace_id"])[0]["trace_id"] == spans[0]["trace_id"]
        and twin.trace_get("0" * 32) == []
    )
    assert any("SYSTEM" in row["body"] for row in twin.log_search("otel-logs-*", "*", "a", "b", 500))
    assert twin.promql_query("rate(x[5m])")["data"]["result"] == []
    twin.write_flag("paymentFailure", "off")
    twin.promql_query("copilot:service_error_ratio:5m")
    twin.promql_query("copilot:service_error_ratio:5m")
    assert twin.readings()["error_ratio"]["payment"] == 0.002
    twin.write_flag("paymentFailure", "50%")
    assert "paymentFailure" not in twin.fixed_at
    copy = ShopTwin.from_dict(json.loads(json.dumps(twin.to_dict())))
    assert copy.flags == twin.flags and copy.tick == twin.tick
    noisy = ShopTwin(
        {
            "id": "n",
            "inject": [{"flag": "adHighCpu", "variant": "on", "at": "after_change"}],
            "noise": "flagd_stream",
        }
    )
    assert noisy.readings()["error_ratio"]["flagd"] == 1.0
    assert {c["flag"] for c in noisy.recent_changes(3600)} == {"adHighCpu", "adFailure"}


def test_cases_must_be_complete_and_on_the_right_split(tmp_path):
    (tmp_path / "a.yaml").write_text("id: a\nsplit: dev\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing"):
        cases_mod.load_cases("dev", tmp_path)
    case = CASES["dev-f1-50pct"]
    (tmp_path / "a.yaml").write_text(json.dumps({**case, "split": "dev"}), encoding="utf-8")
    with pytest.raises(ValueError, match="not heldout"):
        cases_mod.load_cases("heldout", tmp_path)


# ---------------------------------------------------------------- runner
def test_runner_writes_rows_and_a_summary(tmp_path, capsys):
    out = tmp_path / "r.jsonl"
    assert (
        runner.main(
            [
                "--experiment",
                "eval/experiments/e1-c0-fixed.yaml",
                "--out",
                str(out),
                "--repeats",
                "1",
                "--budget",
                "10",
            ]
        )
        == 0
    )
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 20 and all(r["config_version"] for r in rows)
    summary = json.loads(out.with_suffix(".summary.json").read_text(encoding="utf-8"))
    assert summary["runs"] == 20 and summary["harmful_actions"] == 0
    with pytest.raises(SystemExit):
        runner.main(
            ["--experiment", "eval/experiments/e1-c0-fixed.yaml", "--out", str(out), "--split", "heldout"]
        )
    with pytest.raises(SystemExit):
        runner.main(
            [
                "--experiment",
                "eval/experiments/e3-c2-playbook.yaml",
                "--out",
                str(out),
                "--split",
                "heldout",
                "--cases-dir",
                str(tmp_path),
            ]
        )
    unfrozen = tmp_path / "x.yaml"
    unfrozen.write_text(
        "name: x\narchitecture: c0\nplaybook: knowledge/playbook/playbook.yaml\n", encoding="utf-8"
    )
    with pytest.raises(SystemExit):
        runner.main(
            [
                "--experiment",
                str(unfrozen),
                "--out",
                str(out),
                "--split",
                "heldout",
                "--cases-dir",
                str(tmp_path),
            ]
        )


def test_a_failed_run_is_a_row_with_the_error(monkeypatch):
    monkeypatch.setattr(runner, "build_twin_run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    row = runner.run_case(CASES["dev-f1-50pct"], Experiment(architecture="c0"))
    assert row["success"] is False and row["error"] == "RuntimeError: boom"
    assert runner.summarise([row])["errors"] == 1
    assert runner.summarise([])["success"] is None


def test_model_runs_build_an_openrouter_factory(monkeypatch):
    seen = {}
    monkeypatch.setattr(runner, "ModelFactory", lambda exp, cfg: seen.setdefault("factory", exp.name))
    runner.build_twin_run(CASES["dev-f1-50pct"], Experiment(name="c2x"))
    assert seen["factory"] == "c2x"


# ---------------------------------------------------------------- Reflexion and playbook
def test_reflexion_writes_lessons_for_failed_development_cases(tmp_path):
    exp = Experiment(name="c2", architecture="c2", learn=False)
    broken = S.models(exp, remediation=S.chatter)
    pending = reflexion.run_reflexion(exp, [CASES["dev-f1-50pct"]], tmp_path, models=broken)
    assert pending[0]["draft"]["preconditions"] == {"flag.paymentFailure": {"op": "eq", "value": True}}
    assert "Injected: payment error_injection" in pending[0]["feedback"]
    assert (tmp_path / "pending.jsonl").exists()
    assert reflexion.run_reflexion(exp, [CASES["dev-f1-50pct"]], tmp_path, models=S.models(exp)) == []
    with pytest.raises(ValueError, match="development cases only"):
        reflexion.run_reflexion(exp, [{**CASES["dev-f1-50pct"], "split": "heldout"}], tmp_path)
    assert (
        reflexion.trajectory(tmp_path, None) == "no trace"
        and reflexion.trajectory(tmp_path, "nope") == "no trace"
    )


def test_reflexion_reuses_an_earlier_run(tmp_path):
    exp = Experiment(name="c2", architecture="c2", learn=False)
    results = tmp_path / "r.jsonl"
    row = {"case": "dev-f1-50pct", "repeat": 0, "success": False, "incident_id": None, "top_hypotheses": []}
    results.write_text("\n".join(json.dumps(r) for r in (row, {**row, "repeat": 1})), encoding="utf-8")
    pending = reflexion.run_reflexion(
        exp, [CASES["dev-f1-50pct"]], tmp_path, models=S.models(exp), results=results, traces_dir=tmp_path
    )
    assert pending[0]["case"] == "dev-f1-50pct" and pending[0]["draft"]


def test_reflexion_main(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(reflexion, "run_reflexion", lambda exp, cases, out, **kw: [{"id": "x"}])
    assert (
        reflexion.main(["--experiment", "eval/experiments/e3-c2-no-playbook.yaml", "--out", str(tmp_path)])
        == 0
    )
    assert "1 lesson(s)" in capsys.readouterr().out


def test_review_approves_rejects_and_freezes(tmp_path, monkeypatch):
    book, rejected, lock = tmp_path / "playbook.yaml", tmp_path / "rejected.yaml", tmp_path / "lock.json"
    draft = {
        "service": "ad",
        "fault_type": "resource_exhaustion",
        "lesson": "Check CPU.",
        "preconditions": {"cpu_ratio.ad": {"op": "gte", "value": 0.9}},
        "applies_when": "ad CPU saturated",
    }
    pending = [
        {"id": "l1", "case": "c1", "draft": draft},
        {"id": "l2", "case": "c2", "draft": draft},
        {"id": "l3", "case": "c3", "draft": {**draft, "service": "nope"}},
        {"id": "l4", "case": "c4", "draft": None},
    ]
    result = playbook.review(
        pending,
        {"l1": "approve", "l2": "reject: too broad", "l3": "approve"},
        "dana",
        playbook=book,
        rejected=rejected,
        now="2026-11-07T00:00:00+00:00",
    )
    assert result["approved"] == ["l1"] and result["rejected"] == ["l2"] and result["undecided"] == ["l4"]
    assert result["invalid"][0]["codes"] == ["invalid_metadata"]
    assert "too broad" in rejected.read_text(encoding="utf-8")
    assert not playbook.check(book, lock)
    assert playbook.freeze(book, lock)["lessons"] == 1 and playbook.check(book, lock)
    book.write_text(book.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
    assert not playbook.check(book, lock)
    monkeypatch.setattr(playbook, "LOCK", lock)
    monkeypatch.setattr(playbook, "PLAYBOOK", book)
    with pytest.raises(ValueError, match="frozen"):
        playbook.review(pending, {}, "dana")


def test_playbook_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(playbook, "PLAYBOOK", tmp_path / "playbook.yaml")
    monkeypatch.setattr(playbook, "REJECTED", tmp_path / "rejected.yaml")
    monkeypatch.setattr(playbook, "LOCK", tmp_path / "lock.json")
    pending, decisions = tmp_path / "p.jsonl", tmp_path / "d.yaml"
    pending.write_text(json.dumps({"id": "l1", "case": "c", "draft": None}) + "\n", encoding="utf-8")
    decisions.write_text("l1: approve\n", encoding="utf-8")
    assert (
        playbook.main(
            ["review", "--pending", str(pending), "--decisions", str(decisions), "--reviewer", "dana"]
        )
        == 0
    )
    assert playbook.main(["check"]) == 1
    assert playbook.main(["freeze"]) == 0 and playbook.main(["check"]) == 0


# ---------------------------------------------------------------- service, live wiring, API
def service_for(case_id="dev-f1-50pct", arch="c0", publish=None, metrics=None):
    exp = Experiment(name=arch, architecture=arch, learn=False)
    twin, deps, iid = runner.build_twin_run(
        CASES[case_id], exp, models=None if arch == "c0" else S.models(exp)
    )
    return AgentService(deps, InMemorySaver(), run_async=False, publish=publish, metrics=metrics), twin, iid


def test_activity_is_visible_before_the_graph_has_a_checkpoint():
    seen = []
    service, _, _iid = service_for(publish=lambda _i, view: seen.append(view))
    service.note_activity("not-started", "RAG · Searching runbooks: payment.")
    assert seen[-1]["status"] == "investigating"
    assert seen[-1]["running"] is True and seen[-1]["activity"] == "RAG · Searching runbooks: payment."
    assert seen[-1]["activity_log"][-1]["text"] == "RAG · Searching runbooks: payment."
    service.publish_fn = None
    service.note_activity("not-started", "Telemetry · Reading logs: checkout.")
    assert service.activity["not-started"] == "Telemetry · Reading logs: checkout."
    assert [row["text"] for row in service.activity_log["not-started"]] == [
        "RAG · Searching runbooks: payment.",
        "Telemetry · Reading logs: checkout.",
    ]
    service.note_activity("not-started", "Telemetry · Reading logs: checkout.")
    assert [row["text"] for row in service.activity_log["not-started"]] == [
        "RAG · Searching runbooks: payment.",
        "Telemetry · Reading logs: checkout.",
    ]


def test_resume_decision_returns_before_verification_finishes():
    """Approve must not block on the multi-minute verify window."""
    import time

    service, twin, iid = service_for()
    service.run_async = True
    service.start(iid, twin.alert())
    service.wait(timeout=15)
    pending = service.pending(iid)
    assert pending and pending["kind"] == "action"
    started = time.time()
    view = service.resume_decision(
        iid,
        {
            "decision": "approve",
            "approver": "oncall",
            "confirmation": pending["confirmation_code"],
            "text": "",
            "comms_approver": "oncall",
        },
        timeout=15,
    )
    assert time.time() - started < 12
    # Either the action interrupt cleared, or a dual-control vote was recorded quickly.
    cur = service.pending(iid)
    assert cur is None or cur.get("kind") != "action" or len(view.get("events") or []) > 0
    service.wait(timeout=30)


def test_service_runs_to_each_decision_and_publishes_a_view():
    from agents.observability import AgentMetrics

    views = []
    metrics = AgentMetrics()
    service, twin, iid = service_for(publish=lambda i, v: views.append(v), metrics=metrics)
    assert not service.handles(iid)
    service.start(iid, twin.alert())
    pending = service.pending(iid)
    assert pending["kind"] == "action" and views[-1]["pending"]["kind"] == "action"
    for approver in ("eval-oncall", "eval-oncall-2"):
        service.resume(
            iid, {"decision": "approve", "approver": approver, "confirmation": pending["confirmation_code"]}
        )
    assert service.pending(iid)["kind"] == "comms"
    service.resume(iid, {"decision": "approve", "comms_approver": "incident-commander"})
    view = service.view(iid)
    assert view["outcome"] == "resolved" and view["pending"] is None and not view["running"]
    assert metrics.registry.get_sample_value("copilot_agent_incidents_total", {"outcome": "resolved"}) == 1
    assert service.resume_unfinished([iid]) == []


def test_service_records_a_failure_and_resumes_unfinished_runs():
    service, twin, iid = service_for()
    original = service.deps.backends["promql_query"]
    service.deps.backends["promql_query"] = (
        lambda **k: (_ for _ in ()).throw(KeyboardInterrupt) if False else original(**k)
    )
    service.graph = type(
        "G",
        (),
        {
            "invoke": lambda self, *a, **k: (_ for _ in ()).throw(RuntimeError("crash")),
            "get_state": service.graph.get_state,
        },
    )()
    service.start(iid, twin.alert())
    assert (
        service.errors[iid] == "RuntimeError: crash" and service.view(iid)["error"] == "RuntimeError: crash"
    )
    real, twin2, iid2 = service_for()
    real.run_async = True
    real.start(iid2, twin2.alert())
    real.wait()
    assert real.pending(iid2)["kind"] == "action"


def test_resume_after_a_crash_continues_from_the_checkpoint():
    service, twin, iid = service_for()
    config = service._config(iid)
    calls = {"n": 0}
    graph = service.graph

    class Crashing:
        def invoke(self, value, cfg):
            # run only the first steps, as if the process died part-way
            for _ in graph.stream(value, cfg, stream_mode="updates"):
                calls["n"] += 1
                if calls["n"] == 3:
                    raise SystemExit("killed")

    with pytest.raises(SystemExit):
        Crashing().invoke({"incident_id": iid, "alert": twin.alert()}, config)
    assert graph.get_state(config).next
    assert service.resume_unfinished([iid, "unknown"]) == [iid]
    assert service.pending(iid)["kind"] == "action"


def test_live_architecture_falls_back_without_a_key():
    assert live.live_architecture({}) is None
    assert live.live_architecture({"COPILOT_AGENT": "c2"}) == "c0"
    assert live.live_architecture({"COPILOT_AGENT": "c1", "OPENROUTER_API_KEY": "k"}) == "c1"


def make_app(tmp_path, env, flags):
    from incident_api.app import create_app
    from incident_api.store import IncidentStore

    from api.safety_gate import SafetyGate

    db = str(tmp_path / "incidents.sqlite3")
    store = IncidentStore(db)
    gate = SafetyGate(lambda *a: "ok", audit_path=str(tmp_path / "audit.jsonl"))
    twin = ShopTwin(CASES["dev-f1-50pct"])
    agent = live.build_live_agent(
        store,
        gate,
        None,
        db,
        env,
        read_flags=twin.read_flags,
        write_flag=twin.write_flag,
        fetch=None,
        run_async=False,
        runbook_search=lambda query: ["payment-failure"],
    )
    agent.deps.backends.update(twin.tools())
    agent.deps.sleep = lambda s: None
    return create_app(db, on_approve=lambda *a: "ok", agent=agent), agent


ALERT = {
    "alerts": [
        {
            "status": "firing",
            "labels": {"alertname": "ServiceErrorRateHigh", "service_name": "checkout"},
            "annotations": {"summary": "checkout errors"},
            "startsAt": "2026-11-07T10:00:00Z",
        }
    ]
}


def test_api_runs_the_agent_and_resumes_on_decisions(tmp_path, monkeypatch):
    monkeypatch.delenv("COPILOT_WEBHOOK_SECRET", raising=False)
    app, agent = make_app(tmp_path, {"COPILOT_AGENT": "c0", "COPILOT_TRACES_DIR": str(tmp_path / "t")}, {})
    api = TestClient(app)
    created = api.post("/webhooks/alert", json=ALERT).json()["incidents"][0]
    iid = created["id"]
    incident = api.get(f"/incidents/{iid}").json()
    assert incident["agent"]["pending"]["kind"] == "action" and incident["confirmation_code"]
    assert incident["agent"]["pending"].get("confirmation_code") == incident["confirmation_code"]
    code = incident["confirmation_code"]
    assert (
        api.post(
            f"/incidents/{iid}/decision", json={"decision": "approve", "confirmation": "WRONG"}
        ).status_code
        == 400
    )
    assert api.post(f"/incidents/{iid}/decision", json={"decision": "edit", "text": " "}).status_code == 400
    first = api.post(
        f"/incidents/{iid}/decision", json={"decision": "approve", "confirmation": code, "approver": "oncall"}
    )
    assert first.status_code == 200
    assert first.json().get("decision") is None  # stays open for act/verify/later HITL
    second = api.post(
        f"/incidents/{iid}/decision",
        json={"decision": "approve", "confirmation": code, "approver": "incident-commander"},
    ).json()
    assert second.get("decision") is None
    assert second["agent"]["pending"]["kind"] == "comms"
    done = api.post(
        f"/incidents/{iid}/decision", json={"decision": "approve", "approver": "incident-commander"}
    ).json()
    assert done["agent"]["outcome"] == "resolved"
    agent.wait(timeout=10)
    finished = api.get(f"/incidents/{iid}").json()
    # Resolved runs close themselves once the graph ends; otherwise a final approve closes.
    if finished.get("decision") != "approve":
        finished = api.post(f"/incidents/{iid}/decision", json={"decision": "approve"}).json()
    assert finished["decision"] == "approve"
    assert (
        api.post(f"/incidents/{iid}/decision", json={"decision": "edit", "text": "note"}).status_code == 409
    )


def test_decision_while_the_agent_is_still_working_is_refused(tmp_path, monkeypatch):
    monkeypatch.delenv("COPILOT_WEBHOOK_SECRET", raising=False)
    app, agent = make_app(tmp_path, {"COPILOT_AGENT": "c0", "COPILOT_TRACES_DIR": str(tmp_path / "t")}, {})
    api = TestClient(app)
    incident_id = api.post("/webhooks/alert", json=ALERT).json()["incidents"][0]["id"]
    monkeypatch.setattr(agent, "pending", lambda _incident_id: None)
    monkeypatch.setattr(agent, "view", lambda _incident_id: {"running": True})
    response = api.post(f"/incidents/{incident_id}/decision", json={"decision": "approve"})
    assert response.status_code == 409
    assert response.json()["detail"] == "the agent is still working"


def test_finished_escalated_incident_can_be_closed(tmp_path, monkeypatch):
    monkeypatch.delenv("COPILOT_WEBHOOK_SECRET", raising=False)
    app, agent = make_app(tmp_path, {"COPILOT_AGENT": "c0", "COPILOT_TRACES_DIR": str(tmp_path / "t")}, {})
    api = TestClient(app)
    incident_id = api.post("/webhooks/alert", json=ALERT).json()["incidents"][0]["id"]
    monkeypatch.setattr(agent, "pending", lambda _incident_id: None)
    monkeypatch.setattr(
        agent, "view", lambda _incident_id: {"running": False, "outcome": "escalated", "pending": None}
    )
    closed = api.post(f"/incidents/{incident_id}/decision", json={"decision": "approve"})
    assert closed.status_code == 200
    assert closed.json()["decision"] == "approve"
    assert closed.json()["agent"]["outcome"] == "escalated"


def test_live_agent_copies_ticket_drafts_into_the_store(tmp_path, monkeypatch):
    monkeypatch.delenv("COPILOT_WEBHOOK_SECRET", raising=False)
    app, agent = make_app(tmp_path, {"COPILOT_AGENT": "c0", "COPILOT_TRACES_DIR": str(tmp_path / "t")}, {})
    api = TestClient(app)
    iid = api.post("/webhooks/alert", json=ALERT).json()["incidents"][0]["id"]
    agent.deps.tickets.tools(iid)["status_draft"](incident_id=iid, note={"text": "checkout is failing"})
    stored = api.get(f"/incidents/{iid}").json()
    assert stored["tickets"]["drafts"][0]["text"] == "checkout is failing"
    assert agent.deps.knowledge.search("payment") == ["payment-failure"]


def test_hybrid_search_uses_role_two_then_disables_after_failure(monkeypatch):
    class Tool:
        def __call__(self, query):
            return type("Response", (), {"runbook_ids": ["payment-failure"]})()

    monkeypatch.setattr(live, "_default_runbooks_tool", lambda: Tool())
    search = live.HybridSearch()
    assert search("payment down") == ["payment-failure"]
    assert search("again") == ["payment-failure"]

    injected = live.HybridSearch(factory=lambda: Tool())
    assert injected("payment down") == ["payment-failure"]

    broken = live.HybridSearch(factory=lambda: (_ for _ in ()).throw(RuntimeError("no index")))
    assert broken("q") == []
    assert broken("again") == []

    class Boom:
        def __call__(self, query):
            raise RuntimeError("query failed")

    failing = live.HybridSearch(factory=lambda: Boom())
    assert failing("q") == []


def test_default_runbooks_tool_loads_role_two(monkeypatch):
    monkeypatch.setattr(
        "knowledge.retrieval.runbooks_kb_tool.create_runbooks_kb_tool",
        lambda: "runbooks-tool",
    )
    assert live._default_runbooks_tool() == "runbooks-tool"


def test_live_agent_builds_from_the_environment(tmp_path, monkeypatch):
    from incident_api.app import create_app

    created = {}

    class FakeFetch:
        def __init__(self, url, guardrails=None):
            created["url"] = url

        def connect(self):
            return lambda name, args: {"ok": True, "series": []}

    monkeypatch.setattr(live, "McpFetch", FakeFetch)
    monkeypatch.setenv("COPILOT_AGENT", "c0")
    monkeypatch.setenv("COPILOT_MCP_URL", "http://mcp")
    app = create_app(str(tmp_path / "i.sqlite3"), on_approve=lambda *a: "ok")
    assert app.state.agent is not None and created["url"] == "http://mcp"
    monkeypatch.delenv("COPILOT_MCP_URL")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setenv("COPILOT_AGENT", "c2")
    assert (
        create_app(str(tmp_path / "j.sqlite3"), on_approve=lambda *a: "ok").state.agent.deps.models
        is not None
    )


# ---------------------------------------------------------------- CLI and trace report
def test_cli_runs_decides_and_reports(tmp_path):
    out = io.StringIO()
    assert cli.main(["diagram", "--arch", "c2"], out=out) == 0 and "diagnose" in out.getvalue()
    work = str(tmp_path / "w")
    out = io.StringIO()
    cli.main(["run", "--workdir", work, "--case", "dev-f1-50pct", "--arch", "c0"], out=out)
    status = json.loads(out.getvalue()[out.getvalue().index("{") :])
    code = status["pending"]["confirmation_code"]
    for approver in ("eval-oncall", "eval-oncall-2"):
        cli.main(
            ["decide", "--workdir", work, "--decision", "approve", "--approver", approver, "--code", code],
            out=io.StringIO(),
        )
    cli.main(["resume", "--workdir", work], out=io.StringIO())
    out = io.StringIO()
    cli.main(["status", "--workdir", work], out=out)
    assert json.loads(out.getvalue())["pending"]["kind"] == "comms"
    trace = next((tmp_path / "w" / "traces").glob("*.jsonl"))
    out = io.StringIO()
    trace_report.main([str(trace)], out=out)
    text = out.getvalue()
    assert "**Proposal**" in text and "**Engineer decision**" in text and "**Verification**" in text


def test_trace_report_renders_every_event_kind(tmp_path):
    events = [
        {
            "ts": 0,
            "incident": "i",
            "kind": "incident",
            "alert": {},
            "experiment": "e",
            "config": "v",
            "models": {},
        },
        {
            "ts": 1,
            "incident": "i",
            "kind": "plan",
            "plan": {"version": 2, "focus": ["a"], "reason": "r"},
            "replan": True,
        },
        {
            "ts": 1,
            "incident": "i",
            "kind": "tool_call",
            "role": "triage",
            "tool": "t",
            "args": {},
            "ok": True,
            "reason": "cached",
        },
        {
            "ts": 1,
            "incident": "i",
            "kind": "tool_call",
            "role": "triage",
            "tool": "t",
            "args": {},
            "ok": False,
            "reason": "deny",
        },
        {"ts": 1, "incident": "i", "kind": "model_call", "role": "triage", "step": 1, "calls": []},
        {"ts": 1, "incident": "i", "kind": "handoff", "role": "triage", "reason": "submitted", "output": {}},
        {
            "ts": 1,
            "incident": "i",
            "kind": "assess",
            "next": "replan",
            "contradiction": "c",
            "diagnosis": {
                "hypotheses": [{"rank": 1, "service": "a", "fault_type": "b", "status": "refuted"}]
            },
        },
        {"ts": 1, "incident": "i", "kind": "proposal_blocked", "codes": ["x"]},
        {"ts": 1, "incident": "i", "kind": "rollback", "ok": True},
        {"ts": 1, "incident": "i", "kind": "escalate", "reason": "r"},
        {"ts": 1, "incident": "i", "kind": "lessons_recalled", "applicable": []},
        {"ts": 1, "incident": "i", "kind": "lessons_reviewed", "reviewed": []},
        {"ts": 1, "incident": "i", "kind": "other"},
    ]
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
    text = trace_report.render(path)
    assert (
        "Replan v2" in text and "(cached)" in text and "refused (deny)" in text and "Contradiction: c" in text
    )
    path.write_text("", encoding="utf-8")
    assert trace_report.render(path) == "(empty trace)\n"
