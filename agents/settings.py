"""Load the versioned agent config and the experiment configs.

Every experiment is a YAML file, not a code branch. A run records the config version, the
experiment name and the exact model IDs it used.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

CONFIG_PATH = Path(__file__).resolve().parent / "config" / "agents.yaml"
SLOTS = ("role", "context", "task", "constraints", "format", "examples")
ARCHITECTURES = ("c0", "c1", "c2")
_PLACEHOLDER = re.compile(r"\{(\w+)\}")


@lru_cache(maxsize=4)
def load_config(path: str | None = None) -> dict[str, Any]:
    with open(path or CONFIG_PATH, encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    for name, prompt in config["prompts"].items():
        if name == "shared_constraints":
            continue
        missing = [slot for slot in SLOTS if slot not in prompt]
        if missing:
            raise ValueError(f"prompt {name} is missing slots {missing}")
    models_file = os.environ.get("COPILOT_MODELS_FILE", "").strip()
    if models_file and Path(models_file).is_file():
        with open(models_file, encoding="utf-8") as handle:
            _merge_models(config, yaml.safe_load(handle) or {})
    return config


def _merge_models(config: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Replace model slots from a ConfigMap file. Unmentioned slots stay as packaged."""
    for role, slot in (overlay.get("models") or {}).items():
        current = config["models"].get(role)
        if isinstance(slot, dict) and isinstance(current, dict):
            config["models"][role] = {**current, **slot}
        else:
            config["models"][role] = slot
    for model_id, price in (overlay.get("pricing") or {}).items():
        config["pricing"][model_id] = price
    if overlay.get("version"):
        config["version"] = str(overlay["version"])
    return config


def render_prompt(name: str, values: dict[str, Any], config: dict[str, Any] | None = None) -> str:
    """Render one six-slot prompt. Only known {placeholders} are replaced; other braces stay."""
    prompt = (config or load_config())["prompts"][name]

    def fill(text: str) -> str:
        return _PLACEHOLDER.sub(
            lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), text
        )

    parts = []
    for slot in SLOTS:
        body = prompt[slot]
        if isinstance(body, list):
            body = "\n".join(f"- {line}" for line in body)
        parts.append(f"## {slot.capitalize()}\n{fill(str(body)).strip()}")
    return "\n\n".join(parts)


@dataclass(frozen=True)
class Experiment:
    """One configuration of the system. Comparisons change one field and keep the rest."""

    name: str = "c2-team"
    architecture: str = "c2"
    parallel: bool = True
    memory: bool = True
    budget: int = 10
    playbook: str | None = None
    playbook_frozen: bool = False
    learn: bool = True
    repeats: int = 1
    models: dict[str, str] = field(default_factory=dict)
    notes: str = ""

    def __post_init__(self) -> None:
        if self.architecture not in ARCHITECTURES:
            raise ValueError(f"architecture must be one of {ARCHITECTURES}")
        if self.budget < 1:
            raise ValueError("budget must be at least 1")

    def model_id(self, role: str, config: dict[str, Any] | None = None) -> str:
        if role in self.models:
            return self.models[role]
        return (config or load_config())["models"][role]["id"]

    def with_budget(self, budget: int) -> Experiment:
        return replace(self, budget=budget, name=f"{self.name}-b{budget}")


def load_experiment(path: str | Path) -> Experiment:
    with open(path, encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return Experiment(**data)


def role_budgets(experiment: Experiment, config: dict[str, Any] | None = None) -> dict[str, int]:
    """Split the investigation budget. Every comparison spends the same total."""
    total = experiment.budget
    if experiment.architecture == "c1":
        return {"investigator": total}
    if experiment.architecture == "c0":
        return {"triage": total}
    split = (config or load_config())["budgets"]["split"]
    triage = max(1, round(total * split["triage"]))
    runbook = max(1, round(total * split["runbook"])) if total > 2 else 0
    diagnosis = max(1, total - triage - runbook)
    return {"triage": triage, "diagnosis": diagnosis, "runbook": runbook}
