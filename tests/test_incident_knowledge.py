"""In-process runbook and lesson review."""

import pytest

from knowledge.memory.models import Incident, IncidentMatch
from knowledge.retrieval import incident_knowledge
from knowledge.retrieval.contracts import RetrievalResponse, RetrievedRunbook
from knowledge.retrieval.incident_knowledge import review_incident_knowledge


def test_review_returns_the_runbook_and_rejects_the_misleading_lesson():
    calls = {}

    def find(query, top_k=5):
        calls["query"] = query
        return [
            IncidentMatch(incident=_incident(), score=0.9),
            IncidentMatch(
                incident=_incident(
                    id="ad-1",
                    service="ad",
                    failure_family="ad_high_cpu",
                    preconditions=("ad service cpu is high",),
                    lesson="Restart the ad service whenever checkout is slow.",
                ),
                score=0.4,
            ),
        ]

    found = review_incident_knowledge(
        "  payment errors  ",
        incident_service="payment",
        incident_failure_family="payment_failure",
        incident_evidence=["payment service traces show errors", "paymentFailure enabled"],
        runbooks_kb=lambda query: _response(),
        find_incidents=find,
    )

    assert found["query"] == "payment errors"
    assert found["runbook_ids"] == ["payment-failure"]
    assert "paymentFailure feature flag" in found["runbooks"][0]["text"]
    assert found["retrieval_error"] is None
    assert found["memory_error"] is None
    assert [item["decision"] for item in found["lessons"]] == ["apply", "reject"]
    assert calls["query"] == "payment errors"


def test_blank_query_is_rejected_before_retrieval():
    def unused(query):
        raise AssertionError("retrieval should not run")

    with pytest.raises(ValueError, match="query must not be empty"):
        review_incident_knowledge(
            "  ",
            incident_service="payment",
            incident_failure_family="payment_failure",
            incident_evidence=[],
            runbooks_kb=unused,
            find_incidents=unused,
        )


def test_retrieval_and_memory_failures_stay_in_the_result():
    def raise_runtime(query):
        raise RuntimeError("index empty")

    def raise_value(query, top_k=5):
        raise ValueError("encoder unavailable")

    found = review_incident_knowledge(
        "payment errors",
        incident_service="payment",
        incident_failure_family="payment_failure",
        incident_evidence=[],
        runbooks_kb=raise_runtime,
        find_incidents=raise_value,
    )
    assert found["runbook_ids"] == []
    assert found["lessons"] == []
    assert found["retrieval_error"] == "index empty"
    assert found["memory_error"] == "encoder unavailable"

    def raise_blank(query):
        raise ValueError("blank")

    def raise_memory(query, top_k=5):
        raise RuntimeError("memory down")

    other = review_incident_knowledge(
        "payment errors",
        incident_service="payment",
        incident_failure_family="payment_failure",
        incident_evidence=[],
        runbooks_kb=raise_blank,
        find_incidents=raise_memory,
    )
    assert other["retrieval_error"] == "blank"
    assert other["memory_error"] == "memory down"


def test_defaults_use_the_in_process_factories(monkeypatch):
    def tool(query):
        return _response()

    def find(query, top_k=5):
        return []

    monkeypatch.setattr("knowledge.retrieval.runbooks_kb_tool.create_runbooks_kb_tool", lambda: tool)
    assert incident_knowledge._default_runbooks() is tool
    monkeypatch.setattr("knowledge.memory.incidents.search_incidents", find)
    assert incident_knowledge._default_find_incidents() is find

    monkeypatch.setattr(incident_knowledge, "_default_runbooks", lambda: tool)
    monkeypatch.setattr(incident_knowledge, "_default_find_incidents", lambda: find)
    found = review_incident_knowledge(
        "payment errors",
        incident_service="payment",
        incident_failure_family="payment_failure",
        incident_evidence=[],
    )
    assert found["runbook_ids"] == ["payment-failure"]
    assert found["lessons"] == []


def test_review_does_not_save_a_lesson(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("lesson saved")

    monkeypatch.setattr("knowledge.memory.incidents.save_incident", refuse)
    review_incident_knowledge(
        "payment errors",
        incident_service="payment",
        incident_failure_family="payment_failure",
        incident_evidence=["paymentFailure enabled"],
        runbooks_kb=lambda query: _response(),
        find_incidents=lambda query, top_k=5: [],
    )


def _response():
    text = "Disable the paymentFailure feature flag after engineer approval."
    return RetrievalResponse(
        runbook_ids=["payment-failure"],
        postmortem_ids=[],
        query="payment errors",
        runbooks=[
            RetrievedRunbook(
                id="payment-failure",
                title="Payment service failures",
                source="runbooks/payment-failure.md",
                source_date="2026-01-01",
                service="payment",
                failure_family="payment_failure",
                text=text,
            )
        ],
    )


def _incident(**overrides):
    values = {
        "service": "payment",
        "symptom": "checkout error ratio above 5 percent",
        "root_cause": "paymentFailure enabled",
        "preconditions": ("payment service traces show errors", "paymentFailure enabled"),
        "lesson": "Turn paymentFailure off when payment traces and the flag agree.",
        "fix": "Set paymentFailure off",
        "reviewed_by": "on-call lead",
        "failure_family": "payment_failure",
        "id": "pay-1",
    }
    values.update(overrides)
    return Incident(**values)
