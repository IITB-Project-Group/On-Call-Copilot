"""Chat models: OpenRouter for real runs, a scripted model for tests.

Roles map to the model slots in agents.yaml: the commander (and replanning) uses the stronger
model, the specialists share one model, reflection and the judge have their own.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from langchain_core.messages import AIMessage

from agents.settings import Experiment, load_config

MODEL_SLOT = {
    "commander": "commander",
    "replan": "commander",
    "triage": "specialist",
    "diagnosis": "specialist",
    "runbook": "specialist",
    "remediation": "specialist",
    "comms": "specialist",
    "investigator": "specialist",
    "reflection": "reflection",
    "judge": "judge",
}


def openrouter_chat(model_id: str, slot: dict, config: dict, api_key: str | None = None):
    """A LangChain chat model for one OpenRouter model id."""
    from langchain_openai import ChatOpenAI

    key = api_key or os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("Set OPENROUTER_API_KEY to run the agents with a model")
    return ChatOpenAI(
        model=model_id,
        base_url=os.environ.get("OPENROUTER_BASE_URL") or config["models"]["base_url"],
        api_key=key,
        temperature=slot.get("temperature", 0.0),
        max_tokens=slot.get("max_tokens", 1000),
        max_retries=6,  # with back-off; a dropped connection should not fail a whole run
        timeout=120,
        default_headers={"X-Title": "On-Call Copilot"},
    )


class ModelFactory:
    """Hands each role its model and records which model id it used."""

    def __init__(
        self, experiment: Experiment, config: dict | None = None, builder: Callable[..., Any] | None = None
    ):
        self.experiment, self.config = experiment, config or load_config()
        self.builder = builder or openrouter_chat
        self._cache: dict[str, Any] = {}

    def model_id(self, role: str) -> str:
        return self.experiment.model_id(MODEL_SLOT[role], self.config)

    def get(self, role: str):
        slot_name = MODEL_SLOT[role]
        if slot_name not in self._cache:
            model_id = self.model_id(role)
            self._cache[slot_name] = self.builder(model_id, self.config["models"][slot_name], self.config)
        return self._cache[slot_name]


def tool_call(
    name: str, args: dict, call_id: str | None = None, *, tokens: tuple[int, int] = (300, 60)
) -> AIMessage:
    """An AIMessage that calls one tool, as a real model would return it."""
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id or f"call_{name}"}],
        usage_metadata={"input_tokens": tokens[0], "output_tokens": tokens[1], "total_tokens": sum(tokens)},
    )


class ScriptedChatModel:
    """A stand-in chat model for tests: ``script(role, messages)`` returns the next AIMessage.

    It is never used for reported results. It exists so the graph, the hooks and the coverage
    gate can be exercised without network calls.
    """

    def __init__(self, role: str, script: Callable[[str, list], AIMessage]):
        self.role, self.script = role, script
        self.bound_tools: list[dict] = []

    def bind_tools(self, tools: list[dict]) -> ScriptedChatModel:
        bound = ScriptedChatModel(self.role, self.script)
        bound.bound_tools = list(tools)
        return bound

    def invoke(self, messages: list) -> AIMessage:
        return self.script(self.role, list(messages))


def scripted_builder(scripts: dict[str, Callable[[str, list], AIMessage]]):
    """A ModelFactory builder that serves one script per role (keyed by role, then by model slot)."""

    class Factory(ModelFactory):
        def get(self, role: str):
            script = scripts.get(role) or scripts[MODEL_SLOT[role]]
            return ScriptedChatModel(role, script)

    return Factory
