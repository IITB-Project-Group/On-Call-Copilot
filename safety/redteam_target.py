"""Adapter the API-layer checks use against this repo's incident API.

The Nov 5 red team drives ``oncall_copilot.api.server``. This target exposes the
same hooks for the checks that only need the webhook and the approval code:
``ig``, ``client``, ``post_alert``, ``pending_action``, and ``headers``.
"""

from __future__ import annotations

import json
import time

from fastapi.testclient import TestClient

from api.safety_gate import input_guardrails
from incident_api.app import create_app


class IncidentTarget:
    def __init__(self, db_path: str, write_flag=None, webhook_secret: str | None = None) -> None:
        self.webhook_secret = webhook_secret
        self.app = create_app(db_path, on_approve=write_flag or (lambda: "paymentFailure is off"))
        self._client = TestClient(self.app)

    def ig(self):
        secret = self.webhook_secret.encode() if self.webhook_secret else None
        return input_guardrails(secret)

    def client(self) -> TestClient:
        return self._client

    def headers(self) -> dict:
        return {}

    def post_alert(self, body: dict, *, sign: bool = True):
        raw = json.dumps(body).encode()
        headers = {"Content-Type": "application/json"}
        if sign and self.webhook_secret:
            from input_guardrails import sign_webhook

            timestamp = int(time.time())
            headers["X-Signature"] = sign_webhook(raw, self.webhook_secret.encode(), timestamp)
            headers["X-Timestamp"] = str(timestamp)
        return self._client.post("/webhooks/alert", content=raw, headers=headers)

    def pending_action(self, incident_id: str) -> tuple[str, str]:
        incident = self._client.get(f"/incidents/{incident_id}").json()
        return incident["approval_request_id"], incident["confirmation_code"]
