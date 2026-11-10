"""The incident graph end to end on the shop twin: C0, C1 and C2, approvals, replans, rollbacks."""

from __future__ import annotations

import json

import agents_support as S
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from agents.llm import tool_call
from agents.settings import Experiment
from eval.cases import load_cases
from eval.runner import SimulatedEngineer, build_twin_run, drive, run_case
from graph.incident_graph import build_graph

CASES = {case["id"]: case for case in load_cases("dev")}
F2 = {
    "id": "test-f2",
    "split": "dev",
    "inject": [{"flag": "paymentUnreachable", "variant": "on", "at": "steady_state"}],
    "alert": {"alert_name": "ServiceErrorRateHigh", "service": "checkout"},
    "ground_truth": {
        "faults": [
            {
                "service": "payment",
                "fault_type": "dependency_unreachable",
                "fix": {"type": "set_flag", "args": {"flag": "paymentUnreachable", "enabled": False}},
            }
        ]
    },
    "expected": {"severity": "SEV1"},
}


def run(case, exp, scripts=None, reviewer=None, tmp_path=None):
    models = None if exp.architecture == "c0" else S.models(exp, **(scripts or {}))
    twin, deps, iid = build_twin_run(case, exp, models=models, traces_dir=str(tmp_path) if tmp_path else None)
    graph = build_graph(deps, InMemorySaver())
    state, interrupts = drive(graph, iid, twin.alert(), reviewer or SimulatedEngineer())
    return state, deps, iid, twin


@pytest.mark.parametrize("case_id", sorted(CASES))
def test_fixed_workflow_resolves_every_development_case(case_id):
    row = run_case(CASES[case_id], Experiment(name="c0", architecture="c0", learn=False))
    assert row["error"] is None
    assert row["success"], row
    assert row["harmful_actions"] == 0


@pytest.mark.parametrize("arch,parallel", [("c2", True), ("c2", False), ("c1", False)])
def test_model_driven_architectures_fix_the_payment_fault(arch, parallel, tmp_path):
    exp = Experiment(name=arch, architecture=arch, parallel=parallel, learn=False)
    state, deps, iid, twin = run(CASES["dev-f1-50pct"], exp, tmp_path=tmp_path)
    assert state["outcome"] == "resolved"
    assert twin.flags["paymentFailure"] == "off"
    assert state["plan"]["steps"][0]["status"] == "done"
    trace = (tmp_path / f"{iid}.jsonl").read_text(encoding="utf-8")
    assert '"kind": "model_call"' in trace and '"kind": "handoff"' in trace


def test_two_supported_hypotheses_get_two_approved_actions():
    exp = Experiment(name="c2", architecture="c2", learn=False)

    def triage(role, messages):
        args = {
            "suspects": ["payment", "ad"],
            "affected_services": ["payment"],
            "error_rate": 0.5,
            "summary": "two",
        }
        return tool_call("submit", args)

    state, *_ = run(CASES["dev-pair-f1-f9"], exp, {"triage": triage})
    assert sorted(p["action"]["args"]["flag"] for p in state["proposals"]) == ["adHighCpu", "paymentFailure"]
    assert len(state["resolved"]) == 2


def test_wrong_first_hypothesis_is_refuted_and_the_team_replans(tmp_path):
    exp = Experiment(name="c2", architecture="c2", parallel=False, learn=False)
    state, deps, iid, twin = run(
        F2, exp, {"diagnosis": S.make_diagnosis(wrong_first=True)}, tmp_path=tmp_path
    )
    assert state["outcome"] == "resolved"
    assert [p["version"] for p in state["plan_history"]] == [1, 2]
    assert state["proposals"][0]["action"]["args"]["flag"] == "paymentUnreachable"
    events = [
        json.loads(line) for line in (tmp_path / f"{iid}.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    first = next(e for e in events if e["kind"] == "assess")
    assert first["next"] == "replan" and first["diagnosis"]["hypotheses"][0]["status"] == "refuted"


def test_noise_ends_without_action():
    exp = Experiment(name="c2", architecture="c2", learn=False)
    state, *_ = run(CASES["dev-noise-flagd-stream"], exp)
    assert state["outcome"] == "no_action" and not state.get("proposals")


class Scripted:
    """A reviewer that plays a list of decisions for the action, then approves the rest."""

    def __init__(self, *decisions, then=None):
        self.decisions, self.seen = list(decisions), []
        self.then = then or SimulatedEngineer()

    def __call__(self, payload):
        self.seen.append(payload)
        if payload["kind"] == "action" and self.decisions:
            decision = self.decisions.pop(0)
            return {**decision, "confirmation": decision.get("confirmation", payload["confirmation_code"])}
        return self.then(payload)


def test_edit_cancels_the_approval_and_a_wrong_code_is_refused():
    exp = Experiment(name="c0", architecture="c0", learn=False)
    reviewer = Scripted(
        {"decision": "edit", "text": "check again"},
        {"decision": "approve", "confirmation": "WRONG"},
        {"decision": "approve", "approver": "eval-oncall"},
        {"decision": "approve", "approver": "eval-oncall-2"},
    )
    state, deps, iid, _ = run(CASES["dev-f1-50pct"], exp, reviewer=reviewer)
    requests = deps.approvals.requests(iid)
    assert [r.status.value for r in requests if r.kind == "action"][0] == "cancelled"
    assert state["outcome"] == "resolved"
    ids = [p["request_id"] for p in reviewer.seen if p["kind"] == "action"]
    assert ids[0] != ids[1]  # the edit cancelled the first request and opened a new one


def test_rejection_replans_and_then_escalates_for_the_fixed_workflow():
    reviewer = Scripted({"decision": "reject", "text": "not now"})
    state, *_ = run(
        CASES["dev-f1-50pct"], Experiment(name="c0", architecture="c0", learn=False), reviewer=reviewer
    )
    assert state["outcome"] == "escalated"
    reviewer = Scripted(*[{"decision": "reject", "text": "no"}] * 6)
    state, *_ = run(
        CASES["dev-f1-50pct"], Experiment(name="c2", architecture="c2", learn=False), reviewer=reviewer
    )
    assert state["outcome"] == "escalated" and len(state["plan_history"]) > 1


def test_failed_verification_rolls_back_and_escalates():
    exp = Experiment(name="c0", architecture="c0", learn=False)
    twin, deps, iid = build_twin_run(CASES["dev-f1-50pct"], exp)
    deps.ops.write_flag = lambda flag, variant: "pretend"  # the flag service accepts but nothing changes
    graph = build_graph(deps, InMemorySaver())
    state, _ = drive(graph, iid, twin.alert(), SimulatedEngineer())
    assert state["outcome"] == "escalated"
    assert deps.session(iid).executor.mgr.state(iid).rollbacks == 1
    assert state["verification"]["recovered"] is False


def test_team_replans_after_a_failed_fix_then_escalates():
    exp = Experiment(name="c2", architecture="c2", learn=False)
    twin, deps, iid = build_twin_run(CASES["dev-f1-50pct"], exp, models=S.models(exp))
    deps.ops.write_flag = lambda flag, variant: "pretend"
    state, _ = drive(build_graph(deps, InMemorySaver()), iid, twin.alert(), SimulatedEngineer())
    assert state["outcome"] in ("escalated", "rolled_back")
    assert len(state["plan_history"]) >= 2


def test_blocked_proposal_is_counted_and_escalates():
    def bad(role, messages):
        action = {"type": "restart_service", "service": "all"}
        return tool_call(
            "submit", {"hypothesis_id": "h1", "rationale": "restart everything", "action": action}
        )

    exp = Experiment(name="c2", architecture="c2", learn=False)
    state, *_ = run(CASES["dev-f1-50pct"], exp, {"remediation": bad})
    assert all(p["blocked"] for p in state["proposals"])
    assert state["outcome"] == "escalated"
    by_name = {step["name"]: step["status"] for step in state["plan"]["steps"]}
    assert by_name["propose"] == "failed"
    assert by_name["approve"] == "skipped"
    assert by_name["act"] == "skipped"
    assert by_name["verify"] == "skipped"


def test_no_proposal_and_unfinished_specialists_fall_back():
    exp = Experiment(name="c2", architecture="c2", learn=False)
    state, *_ = run(
        CASES["dev-f3-50pct"],
        exp,
        {
            "remediation": S.chatter,
            "commander": S.chatter,
            "triage": S.chatter,
            "comms": S.chatter,
            "runbook": S.chatter,
        },
    )
    assert state["proposals"][0]["codes"] == ["no_action_proposed"]
    assert state["plan"]["reason"].startswith("Replan did not finish")
    exp1 = Experiment(name="c1", architecture="c1", learn=False)
    state, *_ = run(CASES["dev-f1-50pct"], exp1, {"investigator": S.chatter})
    assert state["outcome"] == "escalated"


def test_lessons_are_reviewed_and_stored_or_rejected():
    exp = Experiment(name="c2", architecture="c2")
    state, deps, iid, _ = run(CASES["dev-f1-50pct"], exp, reviewer=SimulatedEngineer(keep_lessons=True))
    assert state["lessons_reviewed"][0]["stored"] is True
    assert any(lesson["reviewed_by"] == "eval-oncall" for lesson in deps.lessons.all())

    engineer = SimulatedEngineer()

    def pick(payload):
        if payload["kind"] == "lessons":
            return {
                "decision": "approve",
                "approve": [5],
                "approver": "eval-oncall",
                "text": "not general enough",
            }
        return engineer(payload)

    state, *_ = run(CASES["dev-f1-50pct"], exp, reviewer=pick)
    assert state["lessons_reviewed"][0] == {
        "lesson": "Switch the flag off after checking traces.",
        "stored": False,
        "reason": "not general enough",
    }


def test_comms_edit_revalidates_and_rejection_does_not_publish():
    exp = Experiment(name="c0", architecture="c0", learn=False)
    answers = iter([{"decision": "edit", "text": "Fixed. Root cause: 10.0.0.1 host"}, {"decision": "reject"}])
    engineer = SimulatedEngineer()

    def reviewer(payload):
        return next(answers) if payload["kind"] == "comms" else engineer(payload)

    state, deps, iid, _ = run(CASES["dev-f1-50pct"], exp, reviewer=reviewer)
    assert "internal_detail_private_ip" in state["comms"]["external_findings"]
    assert state["comms"]["published"] is False
    assert deps.tickets.records[iid]["published"] == []


def test_publish_refused_without_a_comms_approver():
    exp = Experiment(name="c0", architecture="c0", learn=False)
    engineer = SimulatedEngineer()
    state, deps, iid, _ = run(
        CASES["dev-f1-50pct"],
        exp,
        reviewer=lambda p: {"decision": "approve", "comms_approver": "eval-oncall"}
        if p["kind"] == "comms"
        else engineer(p),
    )
    assert state["comms"]["published"] is False


def test_lost_approval_request_is_proposed_again():
    exp = Experiment(name="c0", architecture="c0", learn=False)
    twin, deps, iid = build_twin_run(CASES["dev-f1-50pct"], exp)
    graph = build_graph(deps, InMemorySaver())
    config = {"configurable": {"thread_id": iid}}
    first = graph.invoke({"incident_id": iid, "alert": twin.alert()}, config)["__interrupt__"][0].value
    deps.approvals._requests.clear()  # what a restart of the in-memory approval service looks like
    second = graph.invoke(
        Command(resume={"decision": "approve", "confirmation": first["confirmation_code"]}), config
    )
    assert second["__interrupt__"][0].value["request_id"] != first["request_id"]


def test_halted_incident_cannot_replan(monkeypatch):
    exp = Experiment(name="c2", architecture="c2", learn=False)
    twin, deps, iid = build_twin_run(CASES["dev-f1-50pct"], exp, models=S.models(exp))
    graph = build_graph(deps, InMemorySaver())
    config = {"configurable": {"thread_id": iid}}
    graph.invoke({"incident_id": iid, "alert": twin.alert()}, config)
    deps.session(iid).executor.mgr.halt(iid, "kill_switch")
    state = graph.invoke(Command(resume={"decision": "reject", "text": "stop"}), config)
    while "__interrupt__" in state:
        state = graph.invoke(Command(resume={"decision": "reject"}), config)
    assert graph.get_state(config).values["outcome"] == "escalated"


def test_action_failure_escalates():
    exp = Experiment(name="c0", architecture="c0", learn=False)
    twin, deps, iid = build_twin_run(CASES["dev-f1-50pct"], exp)

    def broken(flag, variant):
        raise RuntimeError("flag service down")

    deps.ops.write_flag = broken
    state, _ = drive(build_graph(deps, InMemorySaver()), iid, twin.alert(), SimulatedEngineer())
    assert state["outcome"] == "escalated"
    assert "Action failed" in state["contradiction"]


def test_approvals_paused_blocks_the_proposal():
    exp = Experiment(name="c0", architecture="c0", learn=False)
    twin, deps, iid = build_twin_run(CASES["dev-f1-50pct"], exp)
    assert deps.approvals.pause("eval-oncall", "change freeze")
    state, _ = drive(build_graph(deps, InMemorySaver()), iid, twin.alert(), SimulatedEngineer())
    assert state["proposals"][0]["codes"] == ["approvals_paused"]
