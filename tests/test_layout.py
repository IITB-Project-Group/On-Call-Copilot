import importlib

from agents.diagnosis import READ_TOOLS
from eval.cases import load_cases
from graph import STEPS
from tools.actions import WRITE_ACTIONS


PACKAGES = [
    "schemas",
    "api",
    "ui",
    "knowledge",
    "tools",
    "tools.telemetry",
    "tools.runbooks",
    "tools.tickets",
    "tools.actions",
    "graph",
    "agents",
    "agents.triage",
    "agents.diagnosis",
    "agents.runbook",
    "agents.comms",
    "agents.remediation",
    "agents.memory",
    "eval",
]


def test_packages_import():
    for name in PACKAGES:
        importlib.import_module(name)


def test_diagnosis_has_no_write_tools():
    assert set(READ_TOOLS).isdisjoint(WRITE_ACTIONS)


def test_commander_steps_cover_the_incident():
    assert STEPS == ("scope", "hypotheses", "test", "act", "verify", "communicate")


def test_eval_suite_has_only_development_cases():
    cases = load_cases()
    assert len(cases) == 20
    assert {case["split"] for case in cases} == {"dev"}
    assert load_cases("heldout") == []
