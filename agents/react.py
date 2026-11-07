"""The ReAct loop every specialist runs: think, call a tool, read the result, repeat, submit.

The loop ends when the model calls ``submit`` with arguments that validate against the
specialist's hand-off model. A submission that fails validation is returned to the model as an
error (self-correction). Model calls go through ``GuardedExecutor.call_model`` so cost and
wall-clock budgets apply; tool calls go through ``RoleToolset`` and the hooks.

Short-term memory: when tool results grow past ``context_max_chars``, the oldest results are
replaced by a line listing the evidence ids they contained.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, ValidationError

_EVIDENCE = re.compile(r"(?:span|log|metric|change):[\w:.-]+|runbook_get:[0-9a-f]+")
ELIDED = "[older result elided to save context; evidence ids: {ids}]"


@dataclass
class ReactResult:
    output: BaseModel | None
    steps: int = 0
    halted: bool = False
    reason: str = ""
    tool_calls: list[str] = field(default_factory=list)


def submit_schema(model: type[BaseModel]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": "submit",
            "description": f"Submit your final {model.__name__}. Call this exactly once, when you are done.",
            "parameters": model.model_json_schema(),
        },
    }


def trim_tool_results(messages: list, max_chars: int) -> int:
    """Elide the oldest tool results until the rest fit. Returns how many were elided."""
    tool_messages = [m for m in messages if isinstance(m, ToolMessage)]
    total = sum(len(str(m.content)) for m in tool_messages)
    elided = 0
    for message in tool_messages[:-1]:
        if total <= max_chars:
            break
        if str(message.content).startswith("[older result elided"):
            continue
        ids = sorted(set(_EVIDENCE.findall(str(message.content))))[:20]
        replacement = ELIDED.format(ids=", ".join(ids) or "none")
        total -= len(str(message.content)) - len(replacement)
        message.content = replacement
        elided += 1
    return elided


def _usage(message: Any) -> dict:
    usage = getattr(message, "usage_metadata", None) or {}
    return {
        "input_tokens": int(usage.get("input_tokens", 0)),
        "output_tokens": int(usage.get("output_tokens", 0)),
    }


def run_react(
    *,
    role: str,
    model: Any,
    model_id: str,
    executor: Any,
    incident_id: str,
    system: str,
    task: str,
    toolset: Any,
    submit: type[BaseModel],
    max_steps: int = 8,
    context_max_chars: int = 6000,
    recorder: Any = None,
) -> ReactResult:
    bound = model.bind_tools(toolset.schemas() + [submit_schema(submit)])
    messages: list = [SystemMessage(system), HumanMessage(task)]
    result = ReactResult(None)
    for step in range(max_steps):
        result.steps = step + 1
        if step == max_steps - 1:
            messages.append(HumanMessage("This is your last step. Call submit now with what you have."))
        estimate = sum(len(str(m.content)) for m in messages) // 4

        def invoke() -> tuple[Any, dict]:
            reply = bound.invoke(messages)
            return reply, _usage(reply)

        outcome = executor.call_model(incident_id, role, model_id, estimate, 400, invoke)
        if not outcome.ok:
            result.halted, result.reason = True, outcome.reason
            return result
        reply = outcome.result
        messages.append(reply)
        calls = list(getattr(reply, "tool_calls", None) or [])
        if recorder is not None:
            recorder.event(
                "model_call",
                role=role,
                model=model_id,
                step=step + 1,
                usage=_usage(reply),
                calls=[c["name"] for c in calls],
                text=str(reply.content)[:300],
            )
        if not calls:
            messages.append(HumanMessage("Call a tool, or call submit with your result."))
            continue
        for call in calls:
            if call["name"] == "submit":
                try:
                    result.output = submit.model_validate(call["args"])
                    result.reason = "submitted"
                    return result
                except ValidationError as exc:
                    problems = [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:5]]
                    messages.append(
                        ToolMessage(
                            json.dumps({"error": "invalid submission", "problems": problems}),
                            tool_call_id=call["id"],
                        )
                    )
                    continue
            result.tool_calls.append(call["name"])
            messages.append(ToolMessage(toolset.call(call["name"], call["args"]), tool_call_id=call["id"]))
        trim_tool_results(messages, context_max_chars)
    result.reason = "max_steps"
    return result
