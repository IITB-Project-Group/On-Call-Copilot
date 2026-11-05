"""Screen alert webhooks and approve the payment flag write."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

from approval_service import ApprovalService, ApprovalStatus, Approver, ApproverRoster, AuditLog
from hooks import GuardedExecutor, HookManager, default_hooks
from input_guardrails import DEFAULT_ALERT_RULES, InputGuardrails
from output_guardrails import action_hash, validate_plan

logger = logging.getLogger(__name__)

FLAG_SERVICES = frozenset({"checkout", "payment"})
SHOP_ALERTS = DEFAULT_ALERT_RULES | frozenset({"ServiceErrorRateHigh"})
SIGNATURE_CODES = frozenset(
    {
        "missing_signature",
        "invalid_signature",
        "invalid_signature_timestamp",
        "replayed_webhook",
        "signature_requires_raw_body",
    }
)
PAYMENT_ACTION = {"type": "set_flag", "args": {"flag": "paymentFailure", "enabled": False}}
PAYMENT_ROLLBACK = {"type": "set_flag", "args": {"flag": "paymentFailure", "enabled": True}}
PAYMENT_DIAGNOSIS = {
    "hypotheses": [
        {
            "id": "h1",
            "rank": 1,
            "service": "payment",
            "fault_type": "error_injection",
            "status": "supported",
            "evidence": ["span:shop"],
        }
    ]
}


def webhook_secret() -> bytes | None:
    raw = os.environ.get("COPILOT_WEBHOOK_SECRET", "").strip()
    if raw:
        return raw.encode()
    if not getattr(webhook_secret, "logged", False):
        logger.info("COPILOT_WEBHOOK_SECRET is unset; alert webhooks are accepted without a signature")
        webhook_secret.logged = True
    return None


def input_guardrails(secret: bytes | None) -> InputGuardrails:
    return InputGuardrails(webhook_secret=secret, allowed_alertnames=SHOP_ALERTS)


def _error(result) -> str:
    return "alert webhook blocked: " + ", ".join(sorted(result.codes))


def screen_webhook(raw: bytes, signature: str | None, timestamp: str | None) -> tuple[list[dict], str | None]:
    """Return store fields for each firing alert, or an error string."""
    secret = webhook_secret()
    if secret is not None:
        signed = input_guardrails(secret).check_alert_webhook(raw, signature=signature, timestamp=timestamp)
        if signed.codes & SIGNATURE_CODES:
            return [], _error(signed)
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return [], "Body is not valid JSON"
    if not isinstance(payload, dict):
        return [], "Webhook body must be a JSON object"
    firing = [
        alert
        for alert in (payload.get("alerts") or [])
        if isinstance(alert, dict) and alert.get("status") == "firing"
    ]
    if not firing:
        return [], None
    screenable = {"version": str(payload.get("version") or "4"), "status": "firing", "alerts": firing}
    result = input_guardrails(None).check_alert_webhook(json.dumps(screenable).encode())
    if result.blocked:
        return [], _error(result)
    stored = []
    cleaned = result.sanitized["alerts"]
    for original, clean in zip(firing, cleaned):
        annotations = clean.get("annotations") or {}
        expression = annotations.get("expr") or original.get("generatorURL") or ""
        body = {
            "status": "firing",
            "labels": clean.get("labels") or {},
            "annotations": annotations,
            "startsAt": original.get("startsAt") or "",
        }
        stored.append(
            {
                "alert_name": clean["alertname"],
                "service": clean["service"],
                "starts_at": body["startsAt"],
                "expression": expression if isinstance(expression, str) else "",
                "payload": json.dumps(body),
            }
        )
    return stored, None


def _payment_plan():
    return validate_plan(
        {
            "hypothesis_id": "h1",
            "action": PAYMENT_ACTION,
            "rollback": PAYMENT_ROLLBACK,
            "rationale": "Payment or checkout error rate is above the page threshold.",
            "expected_effect": {
                "metric": "error_ratio",
                "comparator": "<",
                "threshold": 0.05,
                "sustain_samples": 3,
            },
            "verification_window_s": 300,
            "dry_run": {"ok": True, "command_hash": action_hash(PAYMENT_ACTION)},
        },
        diagnosis=PAYMENT_DIAGNOSIS,
        previous_state={"flags": {"paymentFailure": True}},
    )


@dataclass
class FlagOutcome:
    ok: bool
    status: int
    detail: str
    result: str | None = None


class SafetyGate:
    """Exact-command approval and a hook-guarded flag write for one process."""

    def __init__(self, write_flag) -> None:
        self.write_flag = write_flag
        self.audit = AuditLog()
        self.approvals = ApprovalService(
            ApproverRoster([Approver("oncall", frozenset({"oncall"}))]),
            audit=self.audit,
        )
        self.ig = InputGuardrails(allowed_alertnames=SHOP_ALERTS)

    def _executor(self) -> GuardedExecutor:
        return GuardedExecutor(
            HookManager(
                default_hooks(input_guardrails=self.ig, approval_gate=self.approvals), audit=self.audit
            ),
            {"ops_set_flag": self._write},
        )

    def _write(self, action, approval_request_id, phase="forward"):
        self.last_result = self.write_flag()
        return self.last_result

    def propose(self, incident_id: str, service: str):
        if service not in FLAG_SERVICES:
            return None
        plan = _payment_plan()
        if plan.blocked:
            return None
        submitted = self.approvals.submit_action(incident_id, plan, "SEV2")
        if submitted.blocked:
            return None
        request = submitted.sanitized
        return request.request_id, request.confirmation_code, request.command

    def release(self, incident_id: str) -> None:
        for request in self.approvals.requests(incident_id):
            if request.status is ApprovalStatus.PENDING:
                self.approvals.cancel(request.request_id, "note edited")
            elif request.status is ApprovalStatus.EXECUTED:
                self.approvals.record_verification(request.request_id, True)

    def execute(self, incident_id: str, request_id: str | None, confirmation: str) -> FlagOutcome:
        if not request_id:
            return FlagOutcome(False, 400, "No approval request is open for this incident")
        current = self.approvals.get(request_id)
        if current is None:
            return FlagOutcome(False, 400, "No approval request is open for this incident")
        if current.status is ApprovalStatus.PENDING:
            approved = self.approvals.approve(request_id, "oncall", confirmation)
            if approved.blocked:
                finding = approved.findings[0]
                return FlagOutcome(False, 400, finding.message)
        elif current.status is not ApprovalStatus.APPROVED:
            return FlagOutcome(False, 400, f"Request is {current.status.value}")
        outcome = self._executor().call_tool(
            incident_id,
            "remediation",
            "ops_set_flag",
            {"action": PAYMENT_ACTION, "approval_request_id": request_id, "phase": "forward"},
        )
        if outcome.ok:
            return FlagOutcome(True, 200, "", str(self.last_result))
        if "kill_switch" in outcome.reason or outcome.reason.startswith("incident_halted"):
            return FlagOutcome(False, 409, outcome.reason)
        return FlagOutcome(False, 502, outcome.reason)
