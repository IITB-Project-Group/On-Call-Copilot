"""
approval_service.py — L14 human control for the On-Call Copilot.

The engineer approves the EXACT command an agent will run.

  * Only plans that passed ``output_guardrails.validate_plan`` (decision REQUIRE_APPROVAL) and notes that
    passed ``validate_status_note`` (external audience) can be submitted.
  * The review card shows the exact command, its rollback, expected effect and verification window, and a
    confirmation code derived from the hash of (command, rollback). Typing the code (or the full hash) is the
    approval; anything shown differently produces a different code.
  * Approvers come from a roster of humans with roles. Agents can never be on the roster or approve.
    Actions need an ``oncall`` or ``incident_commander``; external comms need a ``comms_lead`` or
    ``incident_commander``. SEV1 and deploy rollbacks need two different approvers (dual control).
  * One open request per incident; repeated rejections hand the incident to a human; requests escalate when
    nobody answers and expire later. Approvals are single use; the payload executed must hash to what was
    approved. Rollback is allowed once, only after the forward action ran, and even while approvals are paused.
  * Every transition is written to a hash-chained, redacted audit log (optionally JSONL on disk).

``ApprovalService.authorize(request_id, payload, phase)`` is the gate interface used by
``output_guardrails.check_tool_call``.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Iterable

from guardrail_core import (
    AGENT_IDENTITIES, SEVERITY_LEVELS, TELEMETRY, Decision, Finding, GuardrailResult, block, canonical_json,
    guarded, sha256_hex,
)
from input_guardrails import SecretRedactor
from output_guardrails import action_hash, render_command

G = "approval_service"


# ============================================================================
# Roster
# ============================================================================
@dataclass(frozen=True)
class Approver:
    approver_id: str
    roles: frozenset[str]
    active: bool = True


class ApproverRoster:
    """Humans allowed to approve. Agent identities are refused at construction time."""

    def __init__(self, approvers: Iterable[Approver]) -> None:
        self._by_id: dict[str, Approver] = {}
        for a in approvers:
            key = (a.approver_id or "").strip().lower()
            if key in AGENT_IDENTITIES or not key:
                raise ValueError(f"{a.approver_id!r} looks like an agent identity; only humans can approve")
            self._by_id[key] = a

    def get(self, approver_id: str) -> Approver | None:
        return self._by_id.get((approver_id or "").strip().lower())

    def ids(self) -> list[str]:
        return sorted(self._by_id)


# ============================================================================
# Policy, status, request
# ============================================================================
@dataclass(frozen=True)
class ApprovalPolicy:
    escalate_after_s: float = 300           # page the incident commander if nobody answers
    expire_after_s: float = 900             # a request (and an unexecuted approval) dies after this
    max_rejections_per_incident: int = 3    # then the incident is handed to a human
    action_roles: frozenset[str] = frozenset({"oncall", "incident_commander"})
    comms_roles: frozenset[str] = frozenset({"comms_lead", "incident_commander"})
    pause_roles: frozenset[str] = frozenset({"incident_commander", "oncall"})
    dual_control_severities: frozenset[str] = frozenset({"SEV1"})
    dual_control_actions: frozenset[str] = frozenset({"rollback_deploy"})


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    EXECUTED = "executed"
    VERIFIED = "verified"
    ROLLED_BACK = "rolled_back"

    def __str__(self) -> str:  # so f"Request is {status}" reads naturally
        return self.value


_TRANSITIONS: dict[ApprovalStatus, frozenset[ApprovalStatus]] = {
    ApprovalStatus.PENDING: frozenset({ApprovalStatus.APPROVED, ApprovalStatus.REJECTED, ApprovalStatus.EXPIRED,
                                       ApprovalStatus.CANCELLED}),
    ApprovalStatus.APPROVED: frozenset({ApprovalStatus.EXECUTED, ApprovalStatus.EXPIRED, ApprovalStatus.CANCELLED}),
    ApprovalStatus.EXECUTED: frozenset({ApprovalStatus.VERIFIED, ApprovalStatus.ROLLED_BACK}),
    ApprovalStatus.REJECTED: frozenset(), ApprovalStatus.EXPIRED: frozenset(), ApprovalStatus.CANCELLED: frozenset(),
    ApprovalStatus.VERIFIED: frozenset(), ApprovalStatus.ROLLED_BACK: frozenset(),
}
OPEN_STATUSES = frozenset({ApprovalStatus.PENDING, ApprovalStatus.APPROVED, ApprovalStatus.EXECUTED})


class InvalidTransition(RuntimeError):
    pass


@dataclass
class ApprovalRequest:
    request_id: str
    incident_id: str
    kind: str                         # action | external_comms
    severity: str
    command: str
    rollback_command: str
    primary_hash: str
    rollback_hash: str | None
    bundle_hash: str
    required_roles: frozenset[str]
    required_approvals: int
    created_at: float
    expires_at: float
    expected_effect: dict | None = None
    verification_window_s: int | None = None
    hypothesis_id: str | None = None
    action_type: str | None = None
    status: ApprovalStatus = ApprovalStatus.PENDING
    votes: list[dict] = field(default_factory=list)
    rejection: dict | None = None
    escalated: bool = False
    approved_at: float | None = None
    executed_at: float | None = None
    verification: str | None = None   # recovered | not_recovered

    @property
    def confirmation_code(self) -> str:
        return self.bundle_hash[:8].upper()

    def review_card(self) -> str:
        lines = [
            f"Approval request {self.request_id[:12]}  incident={self.incident_id}  severity={self.severity}",
            f"Kind:      {self.kind}",
            f"Command:   {self.command}",
            f"Rollback:  {self.rollback_command}",
        ]
        if self.expected_effect:
            ee = self.expected_effect
            lines.append(f"Expect:    {ee.get('metric')} {ee.get('comparator')} {ee.get('threshold')}"
                         f" (sustained {ee.get('sustain_samples', 1)} samples)")
        if self.verification_window_s:
            lines.append(f"Verify:    within {self.verification_window_s}s, else roll back automatically")
        lines += [f"Approvers: {self.required_approvals} x any of {sorted(self.required_roles)}",
                  f"Expires:   in {int(self.expires_at - self.created_at)}s",
                  f"Type confirmation code {self.confirmation_code} to approve, or 'reject: <reason>'."]
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {"request_id": self.request_id, "incident_id": self.incident_id, "kind": self.kind,
                "severity": self.severity, "command": self.command, "rollback_command": self.rollback_command,
                "confirmation_code": self.confirmation_code, "status": self.status.value,
                "required_approvals": self.required_approvals, "votes": [v["approver"] for v in self.votes],
                "required_roles": sorted(self.required_roles), "escalated": self.escalated,
                "expected_effect": self.expected_effect, "verification_window_s": self.verification_window_s,
                "created_at": self.created_at, "expires_at": self.expires_at, "rejection": self.rejection,
                "review_card": self.review_card()}


# ============================================================================
# Notifier + audit
# ============================================================================
class InMemoryNotifier:
    """Stands in for Slack/PagerDuty. ``messages`` is a list of (kind, payload)."""

    def __init__(self) -> None:
        self.messages: list[tuple[str, dict]] = []
        self.subscribers: list[Callable[[str, dict], None]] = []

    def notify(self, kind: str, payload: dict) -> None:
        self.messages.append((kind, payload))
        for cb in list(self.subscribers):
            try:
                cb(kind, payload)
            except Exception:  # a broken subscriber must never break approvals
                pass


class AuditLog:
    """Append-only, hash-chained, redacted audit trail. ``verify()`` detects any edit."""

    def __init__(self, path: str | None = None, redactor: SecretRedactor | None = None,
                 clock: Callable[[], float] = time.time) -> None:
        self.path, self.clock = path, clock
        if path:  # create the folder for the JSONL trail instead of failing on first write
            import os
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.redactor = redactor or SecretRedactor()
        self._entries: list[dict] = []
        self._lock = threading.Lock()

    @staticmethod
    def _digest(entry: dict) -> str:
        body = {k: entry[k] for k in ("seq", "ts", "event", "data", "prev")}
        return sha256_hex(canonical_json(body))

    def append(self, event: str, data: dict | None = None) -> dict:
        clean, _ = self.redactor.redact_value(json.loads(canonical_json(data or {})))
        with self._lock:
            prev = self._entries[-1]["hash"] if self._entries else "0" * 64
            entry = {"seq": len(self._entries), "ts": self.clock(), "event": event, "data": clean, "prev": prev}
            entry["hash"] = self._digest(entry)
            self._entries.append(entry)
            if self.path:
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(canonical_json(entry) + "\n")
        return entry

    def entries(self) -> list[dict]:
        return list(self._entries)

    def verify(self) -> bool:
        prev = "0" * 64
        for i, e in enumerate(self._entries):
            if e.get("seq") != i or e.get("prev") != prev or self._digest(e) != e.get("hash"):
                return False
            prev = e["hash"]
        return True


# ============================================================================
# Service
# ============================================================================
class ApprovalService:
    def __init__(self, roster: ApproverRoster, policy: ApprovalPolicy | None = None, *,
                 notifier: InMemoryNotifier | None = None, audit: AuditLog | None = None,
                 clock: Callable[[], float] = time.time) -> None:
        self.roster, self.policy = roster, policy or ApprovalPolicy()
        self.notifier = notifier or InMemoryNotifier()
        self.clock = clock
        self.audit = audit or AuditLog(clock=clock)
        self._requests: dict[str, ApprovalRequest] = {}
        self._rejections: dict[str, int] = {}
        self._lock = threading.RLock()
        self.paused: dict | None = None

    # ------------------------------------------------------------------ helpers
    def get(self, request_id: str) -> ApprovalRequest | None:
        return self._requests.get(request_id)

    def requests(self, incident_id: str | None = None) -> list[ApprovalRequest]:
        return [r for r in self._requests.values() if incident_id is None or r.incident_id == incident_id]

    def pending(self) -> list[ApprovalRequest]:
        return [r for r in self._requests.values() if r.status is ApprovalStatus.PENDING]

    def _transition(self, req: ApprovalRequest, new: ApprovalStatus, reason: str) -> None:
        if new not in _TRANSITIONS[req.status]:
            raise InvalidTransition(f"{req.status.value} -> {new.value} not allowed ({reason})")
        old, req.status = req.status, new
        self.audit.append(f"approval.{new.value}", {"request_id": req.request_id, "incident_id": req.incident_id,
                                                    "from": old.value, "reason": reason[:200]})

    def _expire_if_due(self, req: ApprovalRequest) -> bool:
        if req.status in (ApprovalStatus.PENDING, ApprovalStatus.APPROVED) and self.clock() > req.expires_at:
            self._transition(req, ApprovalStatus.EXPIRED, "timeout")
            self.notifier.notify("expired", {"request_id": req.request_id, "incident_id": req.incident_id})
            TELEMETRY.inc("agent.approvals", kind=req.kind, outcome="expired")
            return True
        return False

    def _human(self, approver: str) -> tuple[Approver | None, GuardrailResult | None]:
        who = (approver or "").strip().lower()
        if who in AGENT_IDENTITIES:
            return None, block(G, "self_approval", "An agent cannot approve its own action")
        a = self.roster.get(who)
        if a is None or not a.active:
            return None, block(G, "approver_not_authorized", "Approver not on the active roster")
        return a, None

    def _open_for(self, incident_id: str) -> ApprovalRequest | None:
        for r in self._requests.values():
            if r.incident_id == incident_id and r.kind == "action" and r.status in OPEN_STATUSES:
                if r.status is ApprovalStatus.EXECUTED and r.verification == "recovered":
                    continue
                self._expire_if_due(r)
                if r.status in OPEN_STATUSES:
                    return r
        return None

    def _new_request(self, incident_id: str, kind: str, severity: str, command: str, rollback_command: str,
                     primary_hash: str, rollback_hash: str | None, roles: frozenset[str], approvals: int,
                     **extra: Any) -> ApprovalRequest:
        now = self.clock()
        bundle = sha256_hex(canonical_json({"kind": kind, "incident": incident_id, "command": command,
                                            "p": primary_hash, "r": rollback_hash, "rb": rollback_command}))
        req = ApprovalRequest(uuid.uuid4().hex, incident_id, kind, severity, command, rollback_command,
                              primary_hash, rollback_hash, bundle, roles, approvals, now,
                              now + self.policy.expire_after_s, **extra)
        self._requests[req.request_id] = req
        self.audit.append("approval.requested", {"request_id": req.request_id, "incident_id": incident_id,
                                                 "kind": kind, "command": command, "rollback": rollback_command,
                                                 "bundle_hash": bundle, "required_approvals": approvals})
        self.notifier.notify("requested", {"request_id": req.request_id, "incident_id": incident_id,
                                           "kind": kind, "command": command})
        TELEMETRY.inc("agent.approvals", kind=kind, outcome="requested")
        return req

    # ------------------------------------------------------------------ submit
    @guarded("approval_submit")
    def submit_action(self, incident_id: str, plan_result: GuardrailResult, severity: str) -> GuardrailResult:
        with self._lock:
            if self.paused:
                return block(G, "approvals_paused", f"Approvals paused by {self.paused['by']}")
            if severity not in SEVERITY_LEVELS:
                return block(G, "invalid_severity", "Severity must be SEV1..SEV4")
            if not isinstance(plan_result, GuardrailResult) or not plan_result.needs_approval \
                    or not isinstance(plan_result.sanitized, dict) or "action" not in plan_result.sanitized:
                return block(G, "plan_not_validated", "Only plans that passed validate_plan can be submitted")
            if self._rejections.get(incident_id, 0) >= self.policy.max_rejections_per_incident:
                return block(G, "incident_requires_human", "Too many rejected plans; a human takes over")
            if self._open_for(incident_id):
                return block(G, "one_action_at_a_time", "Incident already has an open action request")
            p = plan_result.sanitized
            action, rb = p["action"], p.get("rollback")
            reversible = isinstance(rb, dict) and rb.get("type") not in (None, "noop")
            rb_cmd = render_command(rb) if reversible else \
                f"none (not reversible: {str((rb or {}).get('reason') or 'no rollback')[:120]})"
            two = severity in self.policy.dual_control_severities or action.get("type") in self.policy.dual_control_actions
            req = self._new_request(incident_id, "action", severity, render_command(action), rb_cmd,
                                    action_hash(action), action_hash(rb) if reversible else None,
                                    self.policy.action_roles, 2 if two else 1,
                                    expected_effect=p.get("expected_effect"),
                                    verification_window_s=p.get("verification_window_s"),
                                    hypothesis_id=p.get("hypothesis_id"), action_type=action.get("type"))
            return GuardrailResult(G, Decision.REQUIRE_APPROVAL,
                                   [Finding(G, "approval_requested", "Waiting for human approval",
                                            Decision.REQUIRE_APPROVAL, "low")], req)

    @guarded("approval_submit")
    def submit_external_comms(self, incident_id: str, note_result: GuardrailResult, severity: str) -> GuardrailResult:
        with self._lock:
            if self.paused:
                return block(G, "approvals_paused", f"Approvals paused by {self.paused['by']}")
            if severity not in SEVERITY_LEVELS:
                return block(G, "invalid_severity", "Severity must be SEV1..SEV4")
            note = (note_result.sanitized or {}).get("note") if isinstance(note_result, GuardrailResult) else None
            if not isinstance(note, dict) or not note_result.needs_approval or note.get("audience") != "external":
                return block(G, "note_not_validated", "Only external notes that passed validate_status_note")
            req = self._new_request(incident_id, "external_comms", severity,
                                    f"publish external status: {str(note.get('title', ''))[:120]}", "none (retract manually)",
                                    sha256_hex(canonical_json(note)), None, self.policy.comms_roles, 1)
            return GuardrailResult(G, Decision.REQUIRE_APPROVAL,
                                   [Finding(G, "approval_requested", "Waiting for comms approval",
                                            Decision.REQUIRE_APPROVAL, "low")], req)

    # ------------------------------------------------------------------ decide
    @guarded("approval")
    def approve(self, request_id: str, approver: str, confirmation: str) -> GuardrailResult:
        with self._lock:
            req = self._requests.get(request_id)
            if req is None:
                return block(G, "unknown_request", "No such approval request")
            if self._expire_if_due(req):
                return block(G, "approval_expired", "Approval request expired; re-plan")
            if req.status is not ApprovalStatus.PENDING:
                return block(G, "not_pending", f"Request is {req.status}")
            person, bad = self._human(approver)
            if bad:
                self.audit.append("approval.denied", {"request_id": request_id, "approver": approver,
                                                      "code": bad.findings[0].code})
                return bad
            if not (person.roles & req.required_roles):
                return block(G, "approver_lacks_role", f"Needs one of {sorted(req.required_roles)}")
            code = (confirmation or "").strip()
            if code.upper() != req.confirmation_code and code.lower() != req.bundle_hash:
                return block(G, "confirmation_mismatch", "Confirmation does not match the exact command shown")
            who = person.approver_id.lower()
            if any(v["approver"] == who for v in req.votes):
                return block(G, "duplicate_approver", "Dual control needs two different people")
            req.votes.append({"approver": who, "at": self.clock()})
            self.audit.append("approval.vote", {"request_id": request_id, "approver": who,
                                                "votes": len(req.votes), "required": req.required_approvals})
            if len(req.votes) < req.required_approvals:
                return GuardrailResult(G, Decision.REQUIRE_APPROVAL,
                                       [Finding(G, "awaiting_second_approver", "One more approver needed",
                                                Decision.REQUIRE_APPROVAL, "low")],
                                       {"request_id": request_id, "votes": len(req.votes)})
            req.approved_at = self.clock()
            self._transition(req, ApprovalStatus.APPROVED, f"approved by {', '.join(v['approver'] for v in req.votes)}")
            TELEMETRY.observe("agent.approval_latency", req.approved_at - req.created_at, kind=req.kind)
            TELEMETRY.inc("agent.approvals", kind=req.kind, outcome="approved")
            self.notifier.notify("approved", {"request_id": request_id, "incident_id": req.incident_id,
                                              "by": [v["approver"] for v in req.votes]})
            return GuardrailResult(G, Decision.ALLOW, [], {"request_id": request_id,
                                                           "approvers": [v["approver"] for v in req.votes]})

    @guarded("approval")
    def reject(self, request_id: str, approver: str, reason: str) -> GuardrailResult:
        with self._lock:
            req = self._requests.get(request_id)
            if req is None:
                return block(G, "unknown_request", "No such approval request")
            if not (reason or "").strip():
                return block(G, "reason_required", "A rejection needs a reason (it feeds replanning)")
            if req.status is not ApprovalStatus.PENDING:
                return block(G, "not_pending", f"Request is {req.status}")
            person, bad = self._human(approver)
            if bad:
                return bad
            req.rejection = {"by": person.approver_id.lower(), "reason": reason.strip()[:500], "at": self.clock()}
            self._transition(req, ApprovalStatus.REJECTED, reason.strip())
            if req.kind == "action":
                self._rejections[req.incident_id] = self._rejections.get(req.incident_id, 0) + 1
            TELEMETRY.inc("agent.approvals", kind=req.kind, outcome="rejected")
            self.notifier.notify("rejected", {"request_id": request_id, "incident_id": req.incident_id,
                                              "reason": req.rejection["reason"]})
            return GuardrailResult(G, Decision.ALLOW, [], {"request_id": request_id, "rejected": True})

    def cancel(self, request_id: str, reason: str = "cancelled by agent (replanned)") -> bool:
        with self._lock:
            req = self._requests.get(request_id)
            if req is None or req.status not in (ApprovalStatus.PENDING, ApprovalStatus.APPROVED):
                return False
            self._transition(req, ApprovalStatus.CANCELLED, reason)
            return True

    def check_timeouts(self) -> list[str]:
        """Escalate unanswered requests once; expire requests past their deadline. Returns escalated ids."""
        out = []
        with self._lock:
            now = self.clock()
            for req in list(self._requests.values()):
                if self._expire_if_due(req):
                    continue
                if req.status is ApprovalStatus.PENDING and not req.escalated \
                        and now - req.created_at > self.policy.escalate_after_s:
                    req.escalated = True
                    self.audit.append("approval.escalated", {"request_id": req.request_id,
                                                             "incident_id": req.incident_id})
                    self.notifier.notify("escalated", {"request_id": req.request_id, "incident_id": req.incident_id})
                    out.append(req.request_id)
        return out

    # ------------------------------------------------------------------ execute / verify / rollback
    @guarded("execution_authorization")
    def authorize(self, request_id: str, payload: Any, phase: str = "forward") -> GuardrailResult:
        """Gate interface for check_tool_call: is THIS payload approved for THIS phase, right now?"""
        with self._lock:
            req = self._requests.get(request_id)
            if req is None:
                return block(G, "unknown_request", "No such approval request")
            if phase == "forward":
                if self.paused:
                    return block(G, "approvals_paused", "Forward actions paused; rollback still allowed")
                if self._expire_if_due(req):
                    return block(G, "approval_expired", "Approval expired before execution")
                if req.status is not ApprovalStatus.APPROVED:
                    return block(G, "not_approved" if req.status is ApprovalStatus.PENDING else "replayed_execution",
                                 f"Request is {req.status}")
                h = action_hash(payload) if req.kind == "action" else sha256_hex(canonical_json(payload))
                if h != req.primary_hash:
                    self.audit.append("approval.mismatch", {"request_id": request_id, "expected": req.primary_hash,
                                                            "got": h})
                    return block(G, "command_changed_after_approval", "Payload differs from what was approved")
                req.executed_at = self.clock()
                self._transition(req, ApprovalStatus.EXECUTED, "forward action authorised")
                self.notifier.notify("executed", {"request_id": request_id, "incident_id": req.incident_id})
                return GuardrailResult(G, Decision.ALLOW, [], {"request_id": request_id, "phase": phase})
            if phase == "rollback":
                if req.kind != "action" or req.status is not ApprovalStatus.EXECUTED:
                    return block(G, "rollback_without_execution", "Rollback only after the approved action ran, once")
                if req.rollback_hash is None or action_hash(payload) != req.rollback_hash:
                    return block(G, "rollback_not_approved", "Rollback differs from approved rollback")
                self._transition(req, ApprovalStatus.ROLLED_BACK, "rollback authorised")
                TELEMETRY.inc("agent.rollbacks")
                self.notifier.notify("rolled_back", {"request_id": request_id, "incident_id": req.incident_id})
                return GuardrailResult(G, Decision.ALLOW, [], {"request_id": request_id, "phase": phase})
            return block(G, "invalid_phase", "phase must be forward|rollback")

    @guarded("verification")
    def record_verification(self, request_id: str, recovered: bool) -> GuardrailResult:
        with self._lock:
            req = self._requests.get(request_id)
            if req is None:
                return block(G, "unknown_request", "No such approval request")
            if req.status is not ApprovalStatus.EXECUTED:
                return block(G, "not_executed", f"Request is {req.status}")
            if recovered:
                req.verification = "recovered"
                self._transition(req, ApprovalStatus.VERIFIED, "metrics recovered")
                return GuardrailResult(G, Decision.ALLOW, [], {"request_id": request_id, "next_step": "close"})
            req.verification = "not_recovered"
            self.audit.append("approval.not_recovered", {"request_id": request_id})
            nxt = "rollback" if req.rollback_hash else "replan"
            return GuardrailResult(G, Decision.ALLOW, [Finding(G, "not_recovered", "No recovery in window",
                                                               Decision.ALLOW, "medium")],
                                   {"request_id": request_id, "next_step": nxt})

    # ------------------------------------------------------------------ pause / resume (change freeze)
    def pause(self, who: str, reason: str) -> bool:
        person, bad = self._human(who)
        if bad or not (person.roles & self.policy.pause_roles):
            return False
        self.paused = {"by": person.approver_id.lower(), "reason": reason, "at": self.clock()}
        self.audit.append("approval.paused", dict(self.paused))
        return True

    def resume(self, who: str) -> bool:
        person, bad = self._human(who)
        if bad or not (person.roles & self.policy.pause_roles):
            return False
        self.paused = None
        self.audit.append("approval.resumed", {"by": person.approver_id.lower()})
        return True


# ============================================================================
# Terminal reviewer (CLI approval)
# ============================================================================
class TerminalReviewer:
    """Shows the review card and reads either the confirmation code or 'reject: <reason>'."""

    def __init__(self, service: ApprovalService, approver: str, input_fn: Callable[[str], str] = input,
                 output_fn: Callable[[str], Any] = print) -> None:
        self.service, self.approver, self.input_fn, self.output_fn = service, approver, input_fn, output_fn

    def review(self, request_id: str) -> GuardrailResult:
        req = self.service.get(request_id)
        if req is None:
            return block(G, "unknown_request", "No such approval request")
        self.output_fn(req.review_card())
        answer = (self.input_fn("confirmation code or 'reject: <reason>': ") or "").strip()
        if answer.lower().startswith("reject"):
            reason = answer.split(":", 1)[1].strip() if ":" in answer else ""
            return self.service.reject(request_id, self.approver, reason)
        return self.service.approve(request_id, self.approver, answer)
