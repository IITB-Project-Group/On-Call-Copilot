"""Runtime security monitoring and automatic containment (controls MON-01, RS-02).

Detection rules (thresholds from policy/security_policy.yaml -> monitor):
  SM-01 injection burst          >= N prompt injections quarantined within the window      -> alert
  SM-02 denied-call storm        >= N agent tool calls denied by guardrails in the window  -> alert, pause approvals
  SM-03 approver spoofing        authenticated user claims another approver identity       -> alert; >= N -> disable user
  SM-04 rubber-stamp approval    approval faster than min_review_s after the request       -> warn
  SM-05 auth brute force         >= N failed token attempts from one source                -> alert
  SM-06 audit chain broken       AuditLog.verify() fails                                   -> CRITICAL, kill switch
  SM-07 secret in output         secret pattern found in a published note                   -> CRITICAL, pause approvals
Every event is appended to the tamper-evident audit log and counted in TELEMETRY (security.events).
"""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque
from typing import Any, Optional

from guardrail_core import TELEMETRY

DEFAULTS = {
    "window_s": 600,
    "injection_burst": 3,
    "denied_storm": 10,
    "spoof_disable_after": 2,
    "min_review_s": 3,
    "auth_failures": 5,
    "contain": True,
}


class SecurityMonitor:
    def __init__(
        self, approvals: Any = None, audit: Any = None, cfg: Optional[dict] = None, store: Any = None
    ) -> None:
        self.approvals, self.audit, self.store = approvals, audit, store
        self.cfg = {**DEFAULTS, **(cfg or {})}
        self.events: list[dict] = []
        self.containment: list[dict] = []
        self._win: dict[str, deque] = defaultdict(deque)
        self._spoofs: dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()
        TELEMETRY.add_listener(self._on_metric)

    # ------------------------------------------------------------------ plumbing
    def event(self, rule: str, severity: str, data: dict) -> dict:
        e = {"t": time.time(), "rule": rule, "severity": severity, "data": data}
        with self._lock:
            self.events.append(e)
        TELEMETRY.inc("security.events", rule=rule, severity=severity)
        if self.audit is not None:
            self.audit.append(
                "security.event",
                {"rule": rule, "severity": severity, **{k: str(v)[:120] for k, v in data.items()}},
            )
        return e

    def _count(self, key: str) -> int:
        now, q = time.time(), self._win[key]
        q.append(now)
        while q and now - q[0] > self.cfg["window_s"]:
            q.popleft()
        return len(q)

    def contain(self, action: str, reason: str) -> None:
        if not self.cfg["contain"]:
            return
        if action == "pause_approvals" and self.approvals is not None and not self.approvals.paused:
            self.approvals.paused = {"by": "security-monitor", "reason": reason, "at": time.time()}
        elif action == "kill_switch":
            os.environ["ONCALL_COPILOT_KILL_SWITCH"] = "1"
        self.containment.append({"t": time.time(), "action": action, "reason": reason})
        self.event("containment", "high", {"action": action, "reason": reason})

    # ------------------------------------------------------------------ rules
    def _on_metric(self, kind: str, name: str, value: float, labels: dict) -> None:
        if kind != "counter":
            return
        if name == "guardrail.injections" and self._count("inj") == self.cfg["injection_burst"]:
            self.event(
                "SM-01_injection_burst",
                "high",
                {"source": labels.get("source"), "window_s": self.cfg["window_s"]},
            )
        if name == "agent.tool_calls_blocked" and self._count("denied") == self.cfg["denied_storm"]:
            self.event("SM-02_denied_call_storm", "high", {"role": labels.get("role")})
            self.contain("pause_approvals", "agent keeps attempting blocked calls")

    def spoof_attempt(self, user: str, claimed: str, request_id: str) -> None:
        self._spoofs[user] += 1
        self.event(
            "SM-03_approver_spoofing", "high", {"user": user, "claimed": claimed, "request": request_id}
        )
        if self._spoofs[user] >= self.cfg["spoof_disable_after"] and self.store is not None:
            self.store.disable(user)
            self.contain("disable_user", f"{user} repeatedly claimed other identities")

    def approval_decided(self, user: str, req: Any, decision: str) -> None:
        if decision == "allow" and time.time() - req.created_at < self.cfg["min_review_s"]:
            self.event(
                "SM-04_rubber_stamp", "low", {"user": user, "seconds": round(time.time() - req.created_at, 2)}
            )

    def auth_failure(self, source: str, path: str) -> None:
        if self._count(f"auth:{source}") == self.cfg["auth_failures"]:
            self.event("SM-05_auth_bruteforce", "high", {"source": source, "path": path})

    def check_audit(self) -> bool:
        ok = self.audit.verify() if self.audit is not None else True
        if not ok:
            self.event("SM-06_audit_chain_broken", "critical", {})
            self.contain("kill_switch", "audit log tampering detected")
        return ok

    def check_published(self, text: str) -> bool:
        from input_guardrails import SecretRedactor

        _, found = SecretRedactor().redact_text(text)
        if found:
            self.event("SM-07_secret_in_output", "critical", {"kinds": sorted(found)})
            self.contain("pause_approvals", "secret detected in published output")
        return not found
