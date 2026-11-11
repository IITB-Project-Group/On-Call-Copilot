"""Hardened deployment of the copilot API (controls AC-06, AC-07, IV-04, RS-03, DP-03, IN-01).

``build_hardened_app(store, policy)`` returns a NEW FastAPI app that reuses the copilot's own service objects
(approval service, engineer queue, incident runner) but exposes only authenticated, role-checked endpoints:

  * every endpoint requires a token (except ``/healthz``); the GUI page asks for a token once per session
  * approver identity = authenticated user; a mismatching ``approver`` in the body is a logged spoof attempt
  * ``/alerts`` requires an HMAC-signed webhook (alertmanager service account) -- unsigned alerts are refused
  * ``/demo/*`` does not exist in production mode
  * kill switch ON for on-call/IC/security, OFF only for IC/security; audit for IC/security
  * per-identity rate limits, 64 KB request limit, security headers, no-store caching
  * audit log persisted to a JSONL file (tamper-evident chain) when ``audit_path`` is configured
"""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from .auth import User, UserStore, allowed
from .detectors import hardened_input_guardrails
from .monitor import SecurityMonitor

SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' "
    "https://fonts.googleapis.com; font-src https://fonts.gstatic.com; frame-ancestors 'none'",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}

TOKEN_SHIM = """<script>
(function(){let t=sessionStorage.getItem('copilot_token');if(!t){t=prompt('API token');sessionStorage.setItem('copilot_token',t||'');}
const f=window.fetch;window.fetch=(u,o={})=>{o.headers=Object.assign({},o.headers||{},{'Authorization':'Bearer '+t});return f(u,o)};
const E=window.EventSource;window.EventSource=function(u){return new E(u+(u.includes('?')?'&':'?')+'token='+encodeURIComponent(t))};})();
</script>"""


class RateLimiter:
    def __init__(self, per_minute: int) -> None:
        self.per_minute, self.hits = per_minute, defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.time()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.per_minute:
                return False
            q.append(now)
            return True


def build_hardened_app(
    store: UserStore,
    policy: Optional[dict] = None,
    monitor: Optional[SecurityMonitor] = None,
    audit_path: Optional[str] = None,
) -> FastAPI:
    import oncall_copilot.api.server as srv
    from oncall_copilot.factory import alert_for

    policy = policy or {}
    api = policy.get("api", {})
    secret = (os.getenv("COPILOT_WEBHOOK_SECRET") or api.get("webhook_secret") or "").encode() or None
    if audit_path:  # persist the hash-chained audit trail (folder created if missing)
        os.makedirs(os.path.dirname(os.path.abspath(audit_path)), exist_ok=True)
        srv.AUDIT.path = audit_path
    mon = monitor or SecurityMonitor(srv.APPROVALS, srv.AUDIT, policy.get("monitor", {}))
    limiter = RateLimiter(int(api.get("rate_limit_per_minute", 120)))
    alert_limiter = RateLimiter(int(api.get("alert_rate_limit_per_minute", 30)))
    max_body = int(api.get("max_body_bytes", 64 * 1024))
    app = FastAPI(title="On-Call Copilot (hardened)", version="2.0-hardened")
    app.state.monitor, app.state.store = mon, store

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if int(request.headers.get("content-length") or 0) > max_body:
            mon.event("request_too_large", "medium", {"path": request.url.path})
            return JSONResponse({"detail": "request too large"}, 413, headers=SECURITY_HEADERS)
        tok = (request.headers.get("authorization") or "").removeprefix(
            "Bearer "
        ).strip() or request.query_params.get("token")
        user = store.authenticate(tok)
        request.state.user = user
        key = user.user_id if user else f"anon:{request.client.host if request.client else '?'}"
        if not limiter.allow(key):
            mon.event("rate_limited", "medium", {"who": key, "path": request.url.path})
            return JSONResponse({"detail": "rate limited"}, 429, headers=SECURITY_HEADERS)
        if user is None and request.url.path not in ("/healthz", "/"):
            if tok:
                mon.auth_failure(key, request.url.path)
            return JSONResponse({"detail": "authentication required"}, 401, headers=SECURITY_HEADERS)
        resp = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            resp.headers[k] = v
        return resp

    def need(perm: str):
        def dep(request: Request) -> User:
            u: User = request.state.user
            if u is None or not allowed(u, perm):
                mon.event(
                    "forbidden",
                    "medium",
                    {"who": getattr(u, "user_id", None), "perm": perm, "path": request.url.path},
                )
                raise HTTPException(403, f"requires permission '{perm}'")
            return u

        return dep

    # ---------------------------------------------------------------- pages and read endpoints
    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/", response_class=HTMLResponse)
    def ui():
        page = srv.UI.read_text(encoding="utf-8")
        page = page.replace("<head>", "<head>" + TOKEN_SHIM, 1)
        return page.replace(
            "<h1>On-Call Copilot</h1>",
            "<h1>On-Call Copilot <small style='font-size:12px;color:var(--steel)'>hardened</small></h1>",
        )

    @app.get("/incidents")
    def incidents(u: User = Depends(need("read"))):
        return srv.incidents()

    @app.get("/incidents/{iid}")
    def incident(iid: str, u: User = Depends(need("read"))):
        return srv.incident(iid)

    @app.get("/incidents/{iid}/stream")
    def stream(iid: str, u: User = Depends(need("read"))):
        return srv.stream(iid)

    @app.get("/approvals")
    def approvals(u: User = Depends(need("read"))):
        """Least privilege (red-team finding HC-09): only people who may approve see confirmation codes."""
        out = []
        for r in srv.approvals():
            perm = "approve_comms" if r["kind"] == "external_comms" else "approve_action"
            if not allowed(u, perm):
                r = {k: v for k, v in r.items() if k not in ("confirmation_code", "review_card")}
                r["note"] = "confirmation code hidden: you cannot approve this request"
            out.append(r)
        return out

    @app.get("/roster")
    def roster(u: User = Depends(need("read"))):
        return [{"id": u.user_id, "roles": sorted(u.roles)}]  # you are who your token says

    @app.get("/stats")
    def stats(u: User = Depends(need("read"))):
        return srv.stats()

    @app.get("/control")
    def control(u: User = Depends(need("read"))):
        return srv.control()

    @app.get("/metrics")
    def metrics(u: User = Depends(need("metrics"))):
        return srv.metrics()

    @app.get("/audit")
    def audit(u: User = Depends(need("audit"))):
        return srv.audit()

    @app.get("/security/events")
    def security_events(u: User = Depends(need("security"))):
        return {"events": mon.events[-200:], "contained": mon.containment}

    # ---------------------------------------------------------------- incidents
    @app.post("/alerts")
    async def alerts(request: Request, u: User = Depends(need("ingest_alert"))):
        if not alert_limiter.allow(u.user_id):
            mon.event("alert_flood", "high", {"who": u.user_id})
            raise HTTPException(429, "alert rate limit")
        if secret is None:
            raise HTTPException(503, "webhook secret not configured: refusing unsigned alerts (fail closed)")
        raw = await request.body()
        ig = hardened_input_guardrails(webhook_secret=secret)
        r = ig.check_alert_webhook(
            raw, signature=request.headers.get("X-Signature"), timestamp=request.headers.get("X-Timestamp")
        )
        if r.blocked:
            mon.event("alert_rejected", "high", {"codes": sorted(r.codes)})
            raise HTTPException(422, {"codes": sorted(r.codes)})
        started = []
        for a in r.sanitized["alerts"]:
            if a["status"] == "firing":
                sig = (
                    "p95_ms"
                    if "Latency" in a["alertname"]
                    else "consumer_lag"
                    if "Lag" in a["alertname"]
                    else "error_rate"
                )
                started.append(srv._start(alert_for(a["service"], sig)))
        return {"incidents": started}

    if api.get("allow_demo", False):  # never in production

        @app.post("/demo/{scenario}")
        def demo(scenario: str, u: User = Depends(need("start_incident"))):
            return srv.demo(scenario, None)

    # ---------------------------------------------------------------- approvals: identity from the token
    def _spoof_check(u: User, body: dict, rid: str) -> None:
        claimed = str(body.get("approver") or "").strip().lower()
        if claimed and claimed != u.user_id:
            mon.spoof_attempt(u.user_id, claimed, rid)

    @app.post("/approvals/{rid}/approve")
    async def approve(rid: str, request: Request, u: User = Depends(need("read"))):
        body = await request.json()
        _spoof_check(u, body, rid)
        req = srv.APPROVALS.get(rid)
        if req is None:
            raise HTTPException(404, "unknown request")
        perm = "approve_comms" if req.kind == "external_comms" else "approve_action"
        if not allowed(u, perm):
            mon.event("forbidden", "medium", {"who": u.user_id, "perm": perm, "request": rid})
            raise HTTPException(403, f"requires permission '{perm}'")
        r = srv.APPROVALS.approve(rid, u.user_id, str(body.get("code", "")))
        mon.approval_decided(u.user_id, req, r.decision.value)
        if req.status.value != "pending":
            srv.ENGINEER.done(rid)
        srv._emit(
            srv.REQ_TO_INC.get(rid, "?"),
            "approval_decided",
            {"request_id": rid, "by": u.user_id, "decision": r.decision.value, "codes": sorted(r.codes)},
        )
        return {
            "decision": r.decision.value,
            "codes": sorted(r.codes),
            "status": req.status.value,
            "approver": u.user_id,
        }

    @app.post("/approvals/{rid}/reject")
    async def reject(rid: str, request: Request, u: User = Depends(need("reject"))):
        body = await request.json()
        _spoof_check(u, body, rid)
        r = srv.APPROVALS.reject(rid, u.user_id, str(body.get("reason", "")))
        if not r.blocked:
            srv.ENGINEER.done(rid)
        return {"decision": r.decision.value, "codes": sorted(r.codes)}

    # ---------------------------------------------------------------- controls
    @app.post("/control/kill-switch")
    async def kill(request: Request):
        u: User = request.state.user
        on = bool((await request.json()).get("on"))
        if not allowed(u, "kill_switch_on" if on else "kill_switch_off"):
            mon.event("forbidden", "high", {"who": u.user_id, "perm": "kill_switch", "on": on})
            raise HTTPException(403, "not allowed to change the kill switch in that direction")
        srv.AUDIT.append("control.kill_switch", {"on": on, "by": u.user_id})
        return srv.kill_switch(srv.Toggle(on=on))

    @app.post("/control/pause")
    async def pause(request: Request, u: User = Depends(need("pause"))):
        return {
            "paused": srv.APPROVALS.pause(
                u.user_id, str((await request.json()).get("reason", "change freeze"))
            )
        }

    @app.post("/control/resume")
    async def resume(request: Request, u: User = Depends(need("pause"))):
        return {"resumed": srv.APPROVALS.resume(u.user_id)}

    return app
