import pytest

from knowledge.retrieval.contracts import check_lesson_policy


def _check(**overrides):
    arguments = {
        "lesson_service": "payment",
        "lesson_failure_family": "config",
        "lesson_preconditions": ["feature flag enabled"],
        "incident_service": "payment",
        "incident_failure_family": "config",
        "incident_evidence": ["Feature flag enabled in production"],
    }
    arguments.update(overrides)
    return check_lesson_policy(**arguments)


def test_policy_applies_when_service_family_and_evidence_match():
    assert _check() == "apply"


def test_policy_rejects_a_different_service():
    assert _check(incident_service="cart") == "reject"


def test_policy_rejects_a_different_failure_family():
    assert _check(incident_failure_family="latency") == "reject"


def test_policy_rejects_when_evidence_does_not_cover_preconditions():
    assert _check(incident_evidence=["unrelated observation"]) == "reject"


@pytest.mark.parametrize("preconditions", [[], ["   "], ["single"]])
def test_policy_ignores_blank_and_single_token_preconditions(preconditions):
    assert _check(lesson_preconditions=preconditions, incident_evidence=[]) == "apply"
