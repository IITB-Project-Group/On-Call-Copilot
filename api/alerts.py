"""Turn an Alertmanager payload into stored alerts."""

from __future__ import annotations

import json

from schemas import Alert


def firing_alerts(body: dict) -> list[Alert]:
    found = []
    for alert in body.get("alerts") or []:
        if alert.get("status") != "firing":
            continue
        labels = alert.get("labels") or {}
        annotations = alert.get("annotations") or {}
        found.append(
            Alert(
                alert_name=labels.get("alertname") or "unknown",
                service=labels.get("service") or labels.get("service_name") or "unknown",
                starts_at=alert.get("startsAt") or "",
                expression=annotations.get("expr") or alert.get("generatorURL") or "",
                payload=json.dumps(alert, sort_keys=True),
            )
        )
    return found
