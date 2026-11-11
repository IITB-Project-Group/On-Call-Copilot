"""Hardened deployment of the live On-Call Copilot incident API (controls AC-06, AC-07, IV-04, RS-03, DP-03, MON-01).

``secure_app.build_hardened_app`` hardens the v2 simulator API (``/alerts``, ``/approvals``). The live product
serves ``/webhooks/alert``, ``/incidents`` and ``/incidents/{id}/decision`` from ``incident_api.create_app``.
``HardenedIncidentAPI`` wraps that app WITHOUT editing it:

  * every route except ``/healthz`` needs a token (``Authorization: Bearer`` or ``?token=`` for the SSE stream)
  * least-privilege permissions per route (``protect.auth.PERMISSIONS``); unknown routes are 404 (no demo paths)
  * ``/webhooks/alert`` is for the alertmanager service account only and FAILS CLOSED: with no
    ``COPILOT_WEBHOOK_SECRET`` the webhook answers 503, and a request without ``X-Signature`` is 401
    (the product then verifies the HMAC and the replay window)
  * the approver is the authenticated user: a body ``approver`` naming someone else is a spoof (403, SM-03,
    repeated spoofing disables the account), and the authenticated identity is written to the hash-chained audit
  * confirmation codes are visible only to people who may approve (viewers see ``******``)
  * per-identity rate limits, a webhook rate limit, a request-size limit, ``Cache-Control: no-store``
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Optional
from urllib.parse import parse_qs

from .auth import UserStore, allowed
from .monitor import SecurityMonitor
from .secure_app import RateLimiter

_INCIDENT = re.compile(r"^/incidents/[^/]+$")
_DECISION = re.compile(r"^/incidents/([^/]+)/decision$")
_STREAM = re.compile(r"^/incidents/[^/]+/stream$")
_CODE = re.compile(rb'("confirmation_code":\s*")([^"]*)(")')
_EXTRA_HEADERS = [
    (b"cache-control", b"no-store"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
]
DECISION_PERMISSION = {"approve": "approve_action", "reject": "reject", "edit": "reject"}


def route_permission(method: str, path: str) -> Optional[str]:
    """Permission a route needs; ``"public"`` for health; ``None`` = not exposed (404)."""
    if method == "GET" and path == "/healthz":
        return "public"
    if (
        method == "GET"
        and path in ("/", "/incidents")
        or method == "GET"
        and (_INCIDENT.match(path) or _STREAM.match(path))
    ):
        return "read"
    if method == "GET" and path == "/metrics":
        return "metrics"
    if method == "POST" and path == "/webhooks/alert":
        return "ingest_alert"
    if method == "POST" and _DECISION.match(path):
        return "decide"  # refined per decision once the body is read
    return None


class HardenedIncidentAPI:
    def __init__(
        self,
        app: Any,
        store: UserStore,
        policy: Optional[dict] = None,
        monitor: Optional[SecurityMonitor] = None,
    ) -> None:
        self.app, self.store = app, store
        api = (policy or {}).get("api", {})
        gate = getattr(getattr(app, "state", None), "gate", None)
        self.audit = getattr(gate, "audit", None)
        self.monitor = monitor or SecurityMonitor(
            getattr(gate, "approvals", None), self.audit, (policy or {}).get("monitor", {}), store
        )
        self.limiter = RateLimiter(int(api.get("rate_limit_per_minute", 120)))
        self.alert_limiter = RateLimiter(int(api.get("alert_rate_limit_per_minute", 30)))
        self.max_body = int(api.get("max_body_bytes", 64 * 1024))

    @property
    def state(self):  # so callers can still reach app.state.store / app.state.gate
        return self.app.state

    # ------------------------------------------------------------------ ASGI
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        method, path = scope["method"], scope["path"]
        perm = route_permission(method, path)
        if perm is None:
            return await _reply(send, 404, {"detail": "Not Found"})
        body, too_big = await _read_body(receive, self.max_body)
        if too_big:
            return await _reply(send, 413, {"detail": "request too large"})
        user = None
        if perm != "public":
            user = self.store.authenticate(_token(scope))
            if user is None:
                self.monitor.auth_failure(_client(scope), path)
                return await _reply(send, 401, {"detail": "authentication required"})
            if not self.limiter.allow(user.user_id):
                return await _reply(send, 429, {"detail": "rate limit"})
        if perm == "decide":
            body, err = self._decision(user, path, body)
            if err:
                return await _reply(send, *err)
        elif perm == "ingest_alert":
            if not allowed(user, "ingest_alert"):
                return await _reply(send, 403, {"detail": "forbidden"})
            if not os.getenv("COPILOT_WEBHOOK_SECRET", "").strip():
                return await _reply(send, 503, {"detail": "webhook secret not configured (fail closed)"})
            if not _header(scope, b"x-signature"):
                return await _reply(send, 401, {"detail": "signed webhook required"})
            if not self.alert_limiter.allow(user.user_id):
                return await _reply(send, 429, {"detail": "alert rate limit"})
        elif perm != "public" and not allowed(user, perm):
            return await _reply(send, 403, {"detail": "forbidden"})

        redact = user is not None and not allowed(user, "approve_action")
        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        async def guarded_send(message):
            if message["type"] == "http.response.start":
                headers = [
                    h
                    for h in message.get("headers", [])
                    if h[0].lower() not in {k for k, _ in _EXTRA_HEADERS}
                ]
                message = {**message, "headers": headers + _EXTRA_HEADERS}
            elif message["type"] == "http.response.body" and redact and message.get("body"):
                # same-length mask keeps Content-Length valid for JSON and works per SSE event
                message = {
                    **message,
                    "body": _CODE.sub(
                        lambda m: m.group(1) + b"*" * len(m.group(2)) + m.group(3), message["body"]
                    ),
                }
            await send(message)

        scope = {**scope, "headers": _with_length(scope, len(body))}
        return await self.app(scope, replay, guarded_send)

    # ------------------------------------------------------------------ decisions
    def _decision(self, user, path: str, body: bytes):
        try:
            doc = json.loads(body or b"{}")
        except ValueError:
            return body, (400, {"detail": "invalid JSON"})
        if not isinstance(doc, dict):
            return body, (400, {"detail": "invalid body"})
        need = DECISION_PERMISSION.get(str(doc.get("decision")), "approve_action")
        if not allowed(user, need):
            return body, (403, {"detail": f"forbidden: {need}"})
        incident_id = _DECISION.match(path).group(1)
        claimed = doc.get("approver")
        if claimed not in (None, "", user.user_id):
            self.monitor.spoof_attempt(user.user_id, str(claimed), incident_id)
            return body, (403, {"detail": "approver must be the authenticated user"})
        doc["approver"] = user.user_id
        if self.audit is not None:
            self.audit.append(
                "api.decision",
                {
                    "user": user.user_id,
                    "roles": sorted(user.roles),
                    "incident": incident_id,
                    "decision": str(doc.get("decision")),
                },
            )
        return json.dumps(doc).encode(), None


def build_hardened_incident_app(
    store: UserStore,
    policy: Optional[dict] = None,
    *,
    db_path: Optional[str] = None,
    write_flag=None,
    monitor: Optional[SecurityMonitor] = None,
) -> HardenedIncidentAPI:
    """Create the live incident API and wrap it. ``COPILOT_WEBHOOK_SECRET`` must be set for alerts to be accepted."""
    from incident_api.app import create_app

    app = create_app(db_path, on_approve=write_flag)
    return HardenedIncidentAPI(app, store, policy, monitor)


# ---------------------------------------------------------------------- helpers
async def _read_body(receive, limit: int) -> tuple[bytes, bool]:
    chunks, size = [], 0
    while True:
        m = await receive()
        if m["type"] == "http.disconnect":
            break
        part = m.get("body", b"")
        size += len(part)
        if size > limit:
            return b"", True
        chunks.append(part)
        if not m.get("more_body"):
            break
    return b"".join(chunks), False


async def _reply(send, status: int, doc: dict) -> None:
    raw = json.dumps(doc).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(raw)).encode()),
                (b"x-frame-options", b"DENY"),
                (b"x-content-type-options", b"nosniff"),
            ]
            + _EXTRA_HEADERS,
        }
    )
    await send({"type": "http.response.body", "body": raw})


def _header(scope, name: bytes) -> Optional[str]:
    for k, v in scope.get("headers", []):
        if k.lower() == name:
            return v.decode("latin-1")
    return None


def _token(scope) -> Optional[str]:
    auth = _header(scope, b"authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    q = parse_qs(scope.get("query_string", b"").decode())
    return (q.get("token") or [None])[0]


def _client(scope) -> str:
    c = scope.get("client")
    return c[0] if c else "unknown"


def _with_length(scope, n: int) -> list:
    hs = [(k, v) for k, v in scope.get("headers", []) if k.lower() != b"content-length"]
    return hs + [(b"content-length", str(n).encode())]
