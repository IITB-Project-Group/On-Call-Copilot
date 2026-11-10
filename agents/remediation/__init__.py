"""Remediation specialist: propose one allow-listed action, then code dry-runs, validates and gates it.

The model only proposes. Code builds the plan the guardrails check (expected effect,
verification window, rollback that restores the state read before the action, dry run), and the
action runs only after a person approves the exact command. Diagnosis agents never reach this.
"""

from __future__ import annotations

from output_guardrails import action_hash

from agents.context import AgentContext, compact
from agents.handoffs import RemediationProposal


def run_remediation(
    ctx: AgentContext,
    hypothesis: dict,
    advice: dict,
    flags: dict,
    note: str = "",
    executable: tuple[str, ...] = ("set_flag",),
) -> RemediationProposal | None:
    task = "Propose one action for the top hypothesis and submit a RemediationProposal."
    if note:
        task += f" The engineer edited the previous proposal and wrote: {note}"
    result = ctx.react(
        "remediation",
        "remediation",
        {
            "hypothesis": compact(hypothesis, 600),
            "advice": compact(advice, 800),
            "flags": compact(flags, 600),
            "executable": ", ".join(executable),
        },
        task,
        RemediationProposal,
        budget=0,
    )
    return result.output


def inverse(action: dict, previous_state: dict) -> dict:
    """The rollback that restores the state read before the action."""
    if action["type"] == "set_flag":
        flag = action["args"]["flag"]
        return {
            "type": "set_flag",
            "args": {"flag": flag, "enabled": bool(previous_state.get("flags", {}).get(flag))},
        }
    if action["type"] == "scale_service":
        service = action["args"]["service"]
        return {
            "type": "scale_service",
            "args": {"service": service, "replicas": previous_state.get("replicas", {}).get(service, 1)},
        }
    if action["type"] == "rollback_deploy":
        service = action["args"]["service"]
        current = previous_state.get("versions", {}).get(service, {}).get("current", "0.0.0")
        return {"type": "rollback_deploy", "args": {"service": service, "to_version": current}}
    return {"type": "noop", "reason": "a restart cannot be undone; verification decides the next step"}


def build_plan(
    hypothesis: dict, action: dict, rationale: str, dry_run: dict, effects: dict, verification: dict
) -> dict:
    effect = dict(effects.get(hypothesis["fault_type"], effects["error_injection"]))
    effect["sustain_samples"] = verification["sustain_samples"]
    return {
        "hypothesis_id": hypothesis["id"],
        "action": action,
        "rollback": inverse(action, dry_run.get("previous_state") or {}),
        "rationale": rationale,
        "expected_effect": effect,
        "verification_window_s": verification["window_s"],
        "dry_run": {
            "ok": bool(dry_run.get("ok")),
            "command_hash": dry_run.get("command_hash") or action_hash(action),
        },
    }
