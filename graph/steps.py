"""Commander steps for one paymentFailure incident.

Other faults stop after scope. This slice proposes one dry-run flag change and
does not take a second action when verification fails.
"""

from __future__ import annotations

from schemas.models import ActionProposal, Alert

STEPS = ("scope", "hypotheses", "test", "act", "verify", "communicate")

PAYMENT_SERVICES = frozenset({"payment", "checkout"})
FLAG = "paymentFailure"
RATIO_LIMIT = 0.05


def run_payment_incident(alert: Alert, *, telemetry=None, knowledge=None) -> dict:
    """Investigate one alert and propose paymentFailure off only when the evidence agrees."""
    telemetry = _telemetry() if telemetry is None else telemetry
    knowledge = _knowledge() if knowledge is None else knowledge
    service = alert.service
    ratio_result = telemetry.service_error_ratio("2m")
    trace_result = telemetry.get_traces("payment")
    change_result = telemetry.recent_changes()
    log_result = telemetry.log_search("error", service="payment")
    variant = _flag_variant(change_result)
    observed = _relevant_ratio(ratio_result, service)
    log_count, logs_error = _payment_logs(log_result)
    review = knowledge(
        f"{service} errors during checkout",
        incident_service="payment" if service in PAYMENT_SERVICES else service,
        incident_failure_family="payment_failure" if service in PAYMENT_SERVICES else "",
        incident_evidence=_evidence(observed, variant, trace_result, log_count),
    )
    proposal = _proposal(service, variant, observed, trace_result, review["runbook_ids"])
    hypothesis = _hypothesis(service, variant, proposal)
    return {
        "service": service,
        "hypothesis": hypothesis,
        "error_ratio": observed,
        "flag_variant": variant,
        "log_count": log_count,
        "logs_error": logs_error,
        "runbook_ids": list(review["runbook_ids"]),
        "lessons": list(review["lessons"]),
        "proposal": None if proposal is None else proposal.model_dump(),
        "status_note": _status_note(service, hypothesis, observed, variant, proposal),
        "recovered": None,
        "follow_up_action": None,
    }


def verify_payment_incident(investigation: dict, *, telemetry=None) -> dict:
    """Re-read the error ratio. A ratio that stays high does not create another action."""
    telemetry = _telemetry() if telemetry is None else telemetry
    result = telemetry.service_error_ratio("2m")
    observed = _relevant_ratio(result, investigation["service"])
    recovered = bool(result.ok and observed is not None and observed <= RATIO_LIMIT)
    return {
        **investigation,
        "error_ratio": observed,
        "recovered": recovered,
        "follow_up_action": None,
    }


def _proposal(
    service: str, variant: str | None, ratio: float | None, traces, runbook_ids
) -> ActionProposal | None:
    if service not in PAYMENT_SERVICES:
        return None
    if variant in (None, "off"):
        return None
    if not _errors_present(ratio, traces):
        return None
    if "payment-failure" not in runbook_ids:
        return None
    return ActionProposal(
        action="set_flag",
        arguments={"flag": FLAG, "variant": "off"},
        expected_effect="Payment errors decrease and the checkout error ratio returns below 5%.",
        rollback=f"Set {FLAG} back to {variant}.",
        dry_run=True,
    )


def _hypothesis(service: str, variant: str | None, proposal: ActionProposal | None) -> str:
    if service not in PAYMENT_SERVICES:
        return "This path investigates paymentFailure only."
    if proposal is not None:
        return "paymentFailure is on"
    if variant in (None, "off"):
        return "paymentFailure is off" if variant == "off" else "paymentFailure was not confirmed on"
    return "paymentFailure is on, and the evidence does not support a flag change"


def _errors_present(ratio: float | None, traces) -> bool:
    if ratio is not None and ratio > RATIO_LIMIT:
        return True
    if not traces.ok:
        return False
    return any(item.get("error") for item in traces.series)


def _payment_logs(result) -> tuple[int | None, str | None]:
    """Record that logs were read. Log text stays out of the decision."""
    if not result.ok:
        return None, result.error
    return len(result.series), None


def _evidence(ratio: float | None, variant: str | None, traces, log_count: int | None) -> list[str]:
    evidence = []
    if ratio is not None and ratio > RATIO_LIMIT:
        evidence.append("payment service traces show errors")
    if variant not in (None, "off"):
        evidence.append("paymentFailure enabled")
    if traces.ok and any(item.get("error") for item in traces.series):
        evidence.append("payment trace errors")
    if log_count:
        evidence.append("payment service logs show errors")
    return evidence


def _relevant_ratio(result, service: str) -> float | None:
    primary = _service_ratio(result, service)
    if primary is not None:
        return primary
    if service != "payment":
        return _service_ratio(result, "payment")
    return None


def _service_ratio(result, service: str) -> float | None:
    if not result.ok:
        return None
    for series in result.series:
        labels = series.get("labels") or {}
        if labels.get("service_name") == service and series.get("value") is not None:
            return float(series["value"])
    return None


def _flag_variant(result) -> str | None:
    if not result.ok:
        return None
    for item in result.series:
        if item.get("flag") == FLAG:
            return item.get("variant")
    return None


def _status_note(service: str, hypothesis: str, ratio: float | None, variant: str | None, proposal) -> str:
    ratio_text = "unavailable" if ratio is None else f"{ratio:.2%}"
    flag_text = variant or "off or unread"
    if proposal is None:
        action = "No flag change proposed."
    else:
        action = "Waiting for approval to set paymentFailure off."
    return f"{service}: {hypothesis} Error ratio {ratio_text}. paymentFailure is {flag_text}. {action}"


def _telemetry():
    from tools.telemetry import client

    return client


def _knowledge():
    from knowledge.retrieval.incident_knowledge import review_incident_knowledge

    return review_incident_knowledge
