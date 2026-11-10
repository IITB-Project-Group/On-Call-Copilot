"""Render an incident trace (JSONL from agents.observability.Recorder) as Markdown evidence.

python -m graph.trace_report traces/dev-f1-50pct-demo.jsonl > docs/agents/traces/stop-and-resume.md
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _line(event: dict) -> str | None:
    kind = event["kind"]
    if kind == "plan":
        plan = event["plan"]
        tag = "Replan" if event.get("replan") else "Plan"
        return f"**{tag} v{plan['version']}**: focus {plan['focus']}. {plan['reason']}"
    if kind == "tool_call":
        verdict = "ok" if event["ok"] else f"refused ({event['reason']})"
        cached = " (cached)" if event.get("reason") == "cached" else ""
        return f"`{event['role']}` called `{event['tool']}` {json.dumps(event['args'])[:140]} -> {verdict}{cached}"
    if kind == "model_call":
        return f"`{event['role']}` model step {event['step']}: calls {event['calls']}"
    if kind == "handoff":
        return f"`{event['role']}` handed off ({event['reason']}): {json.dumps(event['output'])[:300]}"
    if kind == "assess":
        tops = [
            f"{h['rank']}. {h['service']} {h['fault_type']} {h.get('flag') or ''} [{h['status']}]"
            for h in event["diagnosis"].get("hypotheses", [])[:3]
        ]
        extra = f" Contradiction: {event['contradiction']}" if event.get("contradiction") else ""
        return f"**Assess** -> `{event['next']}`. Hypotheses: {'; '.join(tops) or 'none'}.{extra}"
    if kind == "proposal":
        p = event["proposal"]
        return f"**Proposal** `{p['command']}` (rollback `{p['rollback_command']}`, {p['severity']}, code {p['confirmation_code']})"
    if kind == "proposal_blocked":
        return f"**Proposal refused** by the guardrails: {event['codes']} {event.get('detail', '')}"
    if kind == "decision":
        return f"**Engineer decision** on {event['about']}: {json.dumps(event['decision'])}"
    if kind == "verification":
        return f"**Verification** samples {event['samples']} -> recovered={event['recovered']}"
    if kind in ("action", "rollback"):
        return f"**{kind.capitalize()}** ok={event['ok']} {event.get('reason') or ''}"
    if kind in ("escalate", "no_fault", "replan_refused"):
        return f"**{kind}** {event.get('reason', '')}"
    if kind == "lessons_recalled":
        return f"Lessons whose preconditions match: {event['applicable']}"
    if kind == "lessons_reviewed":
        return f"**Lessons reviewed**: {json.dumps(event['reviewed'])[:300]}"
    return None


def render(path: str | Path) -> str:
    events = [
        json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    if not events:
        return "(empty trace)\n"
    head = events[0]
    lines = [f"# Trace {head['incident']}", ""]
    if head["kind"] == "incident":
        lines += [
            f"Alert: {head['alert']}. Experiment `{head['experiment']}`, config `{head['config']}`, "
            f"models {head['models']}.",
            "",
        ]
    t0 = head["ts"]
    for n, event in enumerate(events, 1):
        text = _line(event)
        if text:
            lines.append(f"{n}. +{event['ts'] - t0:.2f}s {text}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None, out=sys.stdout) -> int:
    args = argv if argv is not None else sys.argv[1:]
    print(render(args[0]), file=out, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
