"""Server-sent events for one incident."""

from __future__ import annotations

import json


def snapshot_event(incident: dict | None) -> str:
    if incident is None:
        return "event: missing\ndata: {}\n\n"
    return f"data: {json.dumps(incident)}\n\n"
