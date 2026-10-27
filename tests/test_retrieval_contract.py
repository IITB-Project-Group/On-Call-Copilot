from knowledge.retrieval.contracts import (
    RetrievalRequest,
    RetrievalResponse,
    check_lesson_policy,
)


def test_retrieval_request_and_response_shape():
    """The retrieval contract should accept incident context and return candidate results."""
    request = RetrievalRequest(query="Payment authorization requests are failing.")

    response = RetrievalResponse(
        runbook_ids=["payment-failure"],
        postmortem_ids=["pm-001"],
    )

    assert request.query == "Payment authorization requests are failing."
    assert response.runbook_ids == ["payment-failure"]
    assert response.postmortem_ids == ["pm-001"]


def test_policy_accepts_matching_preconditions():
    """A lesson with matching service, failure family, and evidence should be applied."""
    result = check_lesson_policy(
        lesson_service="payment",
        lesson_failure_family="payment_failure",
        lesson_preconditions=["payment service traces show errors", "paymentFailure enabled"],
        incident_service="payment",
        incident_failure_family="payment_failure",
        incident_evidence=["payment trace errors", "paymentFailure enabled"],
    )

    assert result == "apply"


def test_policy_rejects_misleading_lesson():
    """A lesson with the wrong service or evidence should be rejected even if it looks relevant."""
    result = check_lesson_policy(
        lesson_service="ad",
        lesson_failure_family="ad_high_cpu",
        lesson_preconditions=["ad service cpu is high"],
        incident_service="payment",
        incident_failure_family="payment_failure",
        incident_evidence=["payment trace errors", "paymentFailure enabled"],
    )

    assert result == "reject"
