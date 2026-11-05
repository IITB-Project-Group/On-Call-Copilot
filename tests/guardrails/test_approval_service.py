"""Tests for approval_service.py. Run: pytest -q"""
import pytest

from approval_service import (
    ApprovalPolicy, ApprovalService, ApprovalStatus, Approver, ApproverRoster, AuditLog,
    InMemoryNotifier, InvalidTransition, TerminalReviewer,
)
from guardrail_core import TELEMETRY, Decision
from output_guardrails import action_hash, check_tool_call, validate_plan, validate_status_note

OFF = {"type": "set_flag", "args": {"flag": "paymentFailure", "enabled": False}}
ON = {"type": "set_flag", "args": {"flag": "paymentFailure", "enabled": True}}
PREV = {"flags": {"paymentFailure": True}, "versions": {"cart": {"current": "1.4.0", "known": ["1.3.0", "1.4.0"]}}}
DIAG = {"hypotheses": [{"id": "h1", "rank": 1, "service": "payment", "fault_type": "error_injection",
                        "status": "supported", "evidence": ["span:00f067aa0ba902b7"]},
                       {"id": "h2", "rank": 2, "service": "cart", "fault_type": "bad_deploy",
                        "status": "proposed", "evidence": ["span:00f067aa0ba902b7"]}]}
NOTE = {"audience": "external", "title": "Checkout errors", "severity": "SEV2",
        "body": "Some customers could not check out between 11:50 and 12:05 UTC. Checkout works normally now."}


def plan_result(action=OFF, rollback=ON, hyp="h1", diag=DIAG):
    return validate_plan({"hypothesis_id": hyp, "action": action, "rollback": rollback, "rationale": "evidence",
                          "expected_effect": {"metric": "checkout_error_rate", "comparator": "<", "threshold": 0.05,
                                              "sustain_samples": 3},
                          "verification_window_s": 300, "dry_run": {"ok": True, "command_hash": action_hash(action)}},
                         diagnosis=diag, previous_state=PREV)


class Clock:
    def __init__(self):
        self.t = 1_000.0

    def __call__(self):
        return self.t


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def notifier():
    return InMemoryNotifier()


@pytest.fixture
def svc(clock, notifier):
    roster = ApproverRoster([Approver("alice", frozenset({"oncall"})), Approver("bob", frozenset({"incident_commander"})),
                             Approver("carol", frozenset({"comms_lead"})), Approver("dave", frozenset({"oncall"}), active=False)])
    return ApprovalService(roster, ApprovalPolicy(), notifier=notifier, clock=clock)


def submit(svc, severity="SEV2", **kw):
    r = svc.submit_action("INC-1", plan_result(**kw), severity)
    assert r.needs_approval, r.to_dict()
    return r.sanitized


# ============================================================ roster
@pytest.mark.parametrize("agent_id", ["remediation", "oncall-copilot", "AGENT", "system", ""])
def test_agents_cannot_join_roster(agent_id):
    with pytest.raises(ValueError):
        ApproverRoster([Approver(agent_id, frozenset({"oncall"}))])


# ============================================================ submission
def test_submit_builds_exact_review_card(svc, notifier):
    req = submit(svc)
    card = req.review_card()
    assert "ops-actions set_flag --enabled false --flag paymentFailure" in card
    assert "Rollback:  ops-actions set_flag --enabled true --flag paymentFailure" in card
    assert req.confirmation_code in card and len(req.confirmation_code) == 8
    assert notifier.messages[0][0] == "requested"


def test_only_validated_plans_accepted(svc):
    bad = validate_plan({"action": {"type": "shell", "args": {}}}, diagnosis=DIAG)
    assert "plan_not_validated" in svc.submit_action("INC-1", bad, "SEV2").codes


def test_one_open_request_per_incident(svc):
    submit(svc)
    assert "one_action_at_a_time" in svc.submit_action("INC-1", plan_result(), "SEV2").codes
    assert svc.submit_action("INC-2", plan_result(), "SEV2").needs_approval


def test_invalid_severity(svc):
    assert "invalid_severity" in svc.submit_action("INC-1", plan_result(), "SEV9").codes


def test_restart_has_no_rollback_command(svc):
    a = {"type": "restart_service", "args": {"service": "payment"}}
    req = submit(svc, action=a, rollback={"type": "noop", "reason": "restart is not reversible"})
    assert req.rollback_hash is None and "not reversible" in req.rollback_command


# ============================================================ approve / reject
def test_approve_with_confirmation_code(svc):
    req = submit(svc)
    r = svc.approve(req.request_id, "alice", req.confirmation_code.lower())
    assert r.allowed and req.status is ApprovalStatus.APPROVED
    assert TELEMETRY.observations("agent.approval_latency")


def test_full_hash_also_accepted(svc):
    req = submit(svc)
    assert svc.approve(req.request_id, "alice", req.bundle_hash).allowed


@pytest.mark.parametrize("who,code,code_name", [
    ("remediation", "ok", "self_approval"),
    ("mallory", "ok", "approver_not_authorized"),
    ("dave", "ok", "approver_not_authorized"),
    ("carol", "ok", "approver_lacks_role"),
    ("alice", "WRONG123", "confirmation_mismatch"),
])
def test_approval_rejections(svc, who, code, code_name):
    req = submit(svc)
    conf = req.confirmation_code if code == "ok" else code
    r = svc.approve(req.request_id, who, conf)
    assert r.blocked and code_name in r.codes and req.status is ApprovalStatus.PENDING


def test_dual_control_for_sev1(svc):
    req = submit(svc, severity="SEV1")
    assert req.required_approvals == 2
    r1 = svc.approve(req.request_id, "alice", req.confirmation_code)
    assert r1.needs_approval and "awaiting_second_approver" in r1.codes
    assert "duplicate_approver" in svc.approve(req.request_id, "alice", req.confirmation_code).codes
    assert svc.approve(req.request_id, "bob", req.confirmation_code).allowed
    assert req.status is ApprovalStatus.APPROVED


def test_dual_control_for_deploy_rollback(svc):
    diag = {"hypotheses": [{"id": "h1", "rank": 1, "service": "cart", "fault_type": "bad_deploy",
                            "status": "supported", "evidence": ["span:00f067aa0ba902b7"]}]}
    a = {"type": "rollback_deploy", "args": {"service": "cart", "to_version": "1.3.0"}}
    rb = {"type": "rollback_deploy", "args": {"service": "cart", "to_version": "1.4.0"}}
    req = submit(svc, action=a, rollback=rb, diag=diag)
    assert req.required_approvals == 2


def test_reject_needs_reason_and_counts(svc, notifier):
    req = submit(svc)
    assert "reason_required" in svc.reject(req.request_id, "alice", "  ").codes
    assert svc.reject(req.request_id, "alice", "Evidence points at cart, not payment").allowed
    assert req.status is ApprovalStatus.REJECTED and notifier.messages[-1][0] == "rejected"
    assert "not_pending" in svc.approve(req.request_id, "alice", req.confirmation_code).codes


def test_too_many_rejections_hands_incident_to_human(svc):
    for _ in range(3):
        req = submit(svc)
        svc.reject(req.request_id, "alice", "no")
    assert "incident_requires_human" in svc.submit_action("INC-1", plan_result(), "SEV2").codes


def test_expiry_and_escalation(svc, clock, notifier):
    req = submit(svc)
    clock.t += 301
    assert req.request_id in svc.check_timeouts()
    assert req.escalated and notifier.messages[-1][0] == "escalated"
    assert svc.check_timeouts() == []  # escalates only once
    clock.t += 700
    assert "approval_expired" in svc.approve(req.request_id, "alice", req.confirmation_code).codes
    assert req.status is ApprovalStatus.EXPIRED
    assert svc.submit_action("INC-1", plan_result(), "SEV2").needs_approval  # slot freed


def test_cancel_frees_slot(svc):
    req = submit(svc)
    assert svc.cancel(req.request_id) and not svc.cancel(req.request_id)
    assert svc.submit_action("INC-1", plan_result(), "SEV2").needs_approval


# ============================================================ execution
def approved(svc):
    req = submit(svc)
    svc.approve(req.request_id, "alice", req.confirmation_code)
    return req


def test_execute_once(svc):
    req = approved(svc)
    assert svc.authorize(req.request_id, OFF).allowed and req.status is ApprovalStatus.EXECUTED
    assert "replayed_execution" in svc.authorize(req.request_id, OFF).codes


def test_execution_requires_approval(svc):
    req = submit(svc)
    assert "not_approved" in svc.authorize(req.request_id, OFF).codes


def test_command_swap_after_approval_blocked(svc):
    req = approved(svc)
    swapped = {"type": "set_flag", "args": {"flag": "cartFailure", "enabled": False}}
    assert "command_changed_after_approval" in svc.authorize(req.request_id, swapped).codes
    assert any(e["event"] == "approval.mismatch" for e in svc.audit.entries())


def test_approved_but_not_executed_in_time_expires(svc, clock):
    req = approved(svc)
    clock.t += 1000
    assert "approval_expired" in svc.authorize(req.request_id, OFF).codes


def test_verification_then_close(svc):
    req = approved(svc)
    svc.authorize(req.request_id, OFF)
    r = svc.record_verification(req.request_id, recovered=True)
    assert r.sanitized["next_step"] == "close" and req.status is ApprovalStatus.VERIFIED


def test_no_recovery_leads_to_single_rollback(svc):
    req = approved(svc)
    assert "rollback_without_execution" in svc.authorize(req.request_id, ON, "rollback").codes
    svc.authorize(req.request_id, OFF)
    r = svc.record_verification(req.request_id, recovered=False)
    assert r.sanitized["next_step"] == "rollback"
    assert "rollback_not_approved" in svc.authorize(req.request_id, OFF, "rollback").codes
    assert svc.authorize(req.request_id, ON, "rollback").allowed
    assert req.status is ApprovalStatus.ROLLED_BACK
    assert svc.authorize(req.request_id, ON, "rollback").blocked
    assert TELEMETRY.get("agent.rollbacks") == 1


def test_pause_blocks_forward_but_allows_rollback(svc):
    req = approved(svc)
    svc.authorize(req.request_id, OFF)
    assert not svc.pause("remediation", "agent cannot pause")
    assert svc.pause("bob", "change freeze")
    assert svc.authorize(req.request_id, ON, "rollback").allowed
    assert "approvals_paused" in svc.submit_action("INC-9", plan_result(), "SEV2").codes
    assert svc.resume("bob") and svc.submit_action("INC-9", plan_result(), "SEV2").needs_approval


def test_invalid_transition_guard(svc):
    req = submit(svc)
    with pytest.raises(InvalidTransition):
        svc._transition(req, ApprovalStatus.VERIFIED, "x")


# ============================================================ external comms
def test_external_comms_flow(svc):
    nr = validate_status_note(NOTE, incident_verified=True)
    req = svc.submit_external_comms("INC-1", nr, "SEV2").sanitized
    assert "approver_lacks_role" in svc.approve(req.request_id, "alice", req.confirmation_code).codes
    assert svc.approve(req.request_id, "carol", req.confirmation_code).allowed
    edited = {**NOTE, "body": NOTE["body"] + " Sorry!"}
    assert "command_changed_after_approval" in svc.authorize(req.request_id, edited).codes
    assert svc.authorize(req.request_id, NOTE).allowed


def test_internal_or_blocked_notes_not_submittable(svc):
    internal = validate_status_note({**NOTE, "audience": "internal"}, incident_verified=True)
    leaky = validate_status_note({**NOTE, "body": "10.0.0.5 is down"}, incident_verified=True)
    assert "note_not_validated" in svc.submit_external_comms("INC-1", internal, "SEV2").codes
    assert "note_not_validated" in svc.submit_external_comms("INC-1", leaky, "SEV2").codes


def test_service_plugs_into_check_tool_call(svc):
    req = approved(svc)
    args = {"action": OFF, "approval_request_id": req.request_id}
    assert check_tool_call("remediation", "ops_set_flag", args, approval_gate=svc, previous_state=PREV).allowed
    assert check_tool_call("remediation", "ops_set_flag", args, approval_gate=svc, previous_state=PREV).blocked


# ============================================================ audit
def test_audit_chain_and_tamper_detection(svc):
    req = approved(svc)
    svc.authorize(req.request_id, OFF)
    events = [e["event"] for e in svc.audit.entries()]
    assert events[:3] == ["approval.requested", "approval.vote", "approval.approved"]
    assert svc.audit.verify()
    svc.audit._entries[1]["data"]["approver"] = "mallory"
    assert not svc.audit.verify()


def test_audit_redacts_and_writes_jsonl(tmp_path):
    log = AuditLog(path=str(tmp_path / "audit.jsonl"))
    log.append("x", {"note": "password=hunter22"})
    text = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "hunter22" not in text and log.verify()


# ============================================================ terminal reviewer
def test_terminal_reviewer_approve(svc):
    req = submit(svc)
    shown = []
    r = TerminalReviewer(svc, "alice", input_fn=lambda _: req.confirmation_code, output_fn=shown.append).review(req.request_id)
    assert r.allowed and "ops-actions set_flag" in shown[0]


def test_terminal_reviewer_reject(svc):
    req = submit(svc)
    r = TerminalReviewer(svc, "alice", input_fn=lambda _: "reject: wrong service", output_fn=lambda _: None).review(req.request_id)
    assert r.allowed and req.rejection["reason"] == "wrong service"
