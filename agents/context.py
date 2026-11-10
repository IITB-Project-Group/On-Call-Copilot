"""What every specialist needs for one incident, and helpers to turn state into prompt text."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from agents.react import ReactResult, run_react
from agents.settings import Experiment, render_prompt, role_budgets
from agents.toolbox import METRICS, IncidentTools, RoleToolset


@dataclass
class AgentContext:
    incident_id: str
    executor: Any
    tools: IncidentTools
    models: Any
    experiment: Experiment
    config: dict
    available: set
    recorder: Any = None
    lessons: Any = None

    def react(
        self, role: str, prompt: str, values: dict, task: str, submit, budget: int | None = None
    ) -> ReactResult:
        budgets = self.config["budgets"]
        cap = role_budgets(self.experiment, self.config).get(role)
        if budget is not None and cap is not None:  # the hook's cap is per incident, across replans
            spent = self.executor.mgr.state(self.incident_id).per_role.get(role, 0)
            budget = max(0, min(budget, cap - spent))
        steps = (
            budgets["react_max_steps"]
            if budget is None
            else max(2, min(budgets["react_max_steps"], budget + 2))
        )
        toolset = RoleToolset(
            self.tools, role, self.available, context_max_chars=budgets["context_max_chars"], budget=budget
        )
        if not (self.experiment.memory and self.lessons is not None):
            toolset.specs = [spec for spec in toolset.specs if spec.name != "memory_search"]
        if self.tools.on_activity is not None:
            self.tools.on_activity(f"LLM · {role} is deciding what to do next.")
        result = run_react(
            role=role,
            model=self.models.get(prompt if prompt in ("commander", "replan") else role),
            model_id=self.models.model_id(prompt if prompt in ("commander", "replan") else role),
            executor=self.executor,
            incident_id=self.incident_id,
            system=render_prompt(prompt, values, self.config),
            task=task,
            toolset=toolset,
            submit=submit,
            max_steps=steps,
            context_max_chars=budgets["context_max_chars"],
            recorder=self.recorder,
        )
        if self.recorder is not None:
            output = None if result.output is None else result.output.model_dump()
            self.recorder.event("handoff", role=role, reason=result.reason, steps=result.steps, output=output)
        if result.output is not None and self.tools.on_activity is not None:
            self.tools.on_activity(f"LLM · {role} decided: {_decision_brief(role, result.output)}")
        return result

    def lesson_text(self) -> str:
        """Lessons whose preconditions match what the tools have observed so far."""
        if not (self.experiment.memory and self.lessons is not None):
            return "none (memory off)"
        applicable = self.lessons.applicable(self.tools.observations)
        if self.recorder is not None:
            self.recorder.event("lessons_recalled", applicable=[lesson["id"] for lesson in applicable])
        if self.tools.on_activity is not None:
            ids = ", ".join(lesson["id"] for lesson in applicable[:3]) or "none matched"
            self.tools.on_activity(f"Memory · Recalling applicable lessons: {ids}.")
        return (
            json.dumps([{k: lesson[k] for k in ("id", "lesson", "applies_when")} for lesson in applicable])
            or "[]"
        )


def alert_text(alert: dict) -> str:
    return f"{alert.get('alert_name')} on {alert.get('service')} since {alert.get('starts_at')}"


def metrics_text() -> str:
    return "; ".join(f"{name}: {desc}" for name, (_, desc) in METRICS.items())


def compact(data: Any, limit: int = 1500) -> str:
    text = json.dumps(data, default=str)
    return text if len(text) <= limit else text[:limit] + "...]"


def _decision_brief(role: str, output: Any) -> str:
    """One short line for the console: what the specialist just submitted."""
    data = output.model_dump() if hasattr(output, "model_dump") else dict(output or {})
    if role in ("commander", "replan") or "focus" in data:
        focus = ", ".join(data.get("focus") or []) or "no focus"
        return f"plan focus on {focus}"
    if role == "triage":
        suspects = ", ".join(data.get("suspects") or []) or "none"
        return f"suspects {suspects}"
    if role in ("diagnosis", "investigator"):
        hyps = data.get("hypotheses") or []
        top = hyps[0] if hyps else {}
        label = f"{top.get('service', '?')} / {top.get('fault_type', '?')}"
        flag = top.get("flag")
        return f"top hypothesis {label}" + (f" ({flag})" if flag else "")
    if role == "runbook":
        action = data.get("recommended_action") or {}
        if isinstance(action, dict) and action.get("type"):
            return f"recommend {action.get('type')}"
        ids = ", ".join((data.get("runbook_ids") or [])[:3]) or "no runbook"
        return f"runbooks {ids}"
    if role == "remediation":
        action = data.get("action") or {}
        if hasattr(action, "model_dump"):
            action = action.model_dump()
        if isinstance(action, dict):
            kind = action.get("type") or "?"
            flag = action.get("flag") or (action.get("args") or {}).get("flag")
            return f"propose {kind}" + (f" {flag}" if flag else "")
        return "propose an action"
    if role == "comms":
        return "draft status notes and postmortem"
    text = json.dumps(data, default=str)
    return text if len(text) <= 100 else text[:100] + "…"
