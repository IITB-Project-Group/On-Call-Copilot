"""What every specialist needs for one incident, and helpers to turn state into prompt text."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from agents.react import ReactResult, run_react
from agents.settings import Experiment, render_prompt
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
        return result

    def lesson_text(self) -> str:
        """Lessons whose preconditions match what the tools have observed so far."""
        if not (self.experiment.memory and self.lessons is not None):
            return "none (memory off)"
        applicable = self.lessons.applicable(self.tools.observations)
        if self.recorder is not None:
            self.recorder.event("lessons_recalled", applicable=[lesson["id"] for lesson in applicable])
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
