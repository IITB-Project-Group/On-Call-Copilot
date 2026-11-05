"""paymentFailure from a fixture alert to one dry-run proposal."""

from agents.diagnosis import READ_TOOLS
from graph.steps import run_payment_incident, verify_payment_incident
from schemas.models import Alert
from tools.actions import WRITE_ACTIONS


class Result:
    def __init__(self, ok=True, series=None):
        self.ok = ok
        self.series = [] if series is None else series


class Telemetry:
    def __init__(self, ratio_series, traces, flags, ratio_ok=True, trace_ok=True, flag_ok=True):
        self.ratio_series = ratio_series
        self.traces = traces
        self.flags = flags
        self.ratio_ok = ratio_ok
        self.trace_ok = trace_ok
        self.flag_ok = flag_ok

    def service_error_ratio(self, window):
        assert window == "2m"
        return Result(ok=self.ratio_ok, series=self.ratio_series)

    def get_traces(self, service):
        assert service == "payment"
        return Result(ok=self.trace_ok, series=self.traces)

    def recent_changes(self):
        return Result(ok=self.flag_ok, series=self.flags)


def test_payment_failure_proposes_one_dry_run_and_keeps_diagnosis_read_only(monkeypatch):
    def refuse_write(*args, **kwargs):
        raise AssertionError("flag write")

    monkeypatch.setattr("tools.actions.set_flag.set_flag", refuse_write)
    seen = {}

    def knowledge(query, *, incident_service, incident_failure_family, incident_evidence):
        seen["evidence"] = list(incident_evidence)
        return {
            "runbook_ids": ["payment-failure"],
            "lessons": [
                {"id": "pay-1", "service": "payment", "decision": "apply"},
                {"id": "ad-1", "service": "ad", "decision": "reject"},
            ],
        }

    investigation = run_payment_incident(_alert("payment"), telemetry=_telemetry(0.4), knowledge=knowledge)

    assert investigation["hypothesis"] == "paymentFailure is on"
    assert investigation["proposal"]["action"] == "set_flag"
    assert investigation["proposal"]["arguments"] == {"flag": "paymentFailure", "variant": "off"}
    assert investigation["proposal"]["dry_run"] is True
    assert investigation["follow_up_action"] is None
    assert investigation["lessons"][1]["decision"] == "reject"
    assert "Waiting for approval" in investigation["status_note"]
    assert "40.00%" in investigation["status_note"]
    assert "paymentFailure enabled" in seen["evidence"]
    assert set(READ_TOOLS).isdisjoint(WRITE_ACTIONS)
    assert "set_flag" not in READ_TOOLS

    verified = verify_payment_incident(investigation, telemetry=_telemetry(0.01))
    assert verified["recovered"] is True
    assert verified["follow_up_action"] is None
    still_high = verify_payment_incident(investigation, telemetry=_telemetry(0.2))
    assert still_high["recovered"] is False
    assert still_high["follow_up_action"] is None
    unknown = verify_payment_incident(
        investigation, telemetry=Telemetry(ratio_series=[], traces=[], flags=[])
    )
    assert unknown["recovered"] is False


def test_missing_evidence_does_not_propose_a_flag_change():
    unread = run_payment_incident(
        _alert("payment"),
        telemetry=Telemetry(
            ratio_series=[], traces=[], flags=[], ratio_ok=False, trace_ok=False, flag_ok=False
        ),
        knowledge=_knowledge(),
    )
    assert unread["hypothesis"] == "paymentFailure was not confirmed on"
    assert unread["proposal"] is None
    assert "unavailable" in unread["status_note"]
    assert "No flag change proposed." in unread["status_note"]

    flagged_off = run_payment_incident(
        _alert("payment"),
        telemetry=_telemetry(0.4, flags=[{"flag": "paymentFailure", "variant": "off"}]),
        knowledge=_knowledge(),
    )
    assert flagged_off["hypothesis"] == "paymentFailure is off"
    assert flagged_off["proposal"] is None

    no_errors = run_payment_incident(
        _alert("payment"),
        telemetry=_telemetry(0.05, traces=[{"error": False}]),
        knowledge=_knowledge(),
    )
    assert no_errors["proposal"] is None
    assert "does not support" in no_errors["hypothesis"]

    traces_down = run_payment_incident(
        _alert("payment"),
        telemetry=Telemetry(
            ratio_series=[{"labels": {"service_name": "payment"}, "value": 0.01}],
            traces=[],
            flags=[{"flag": "paymentFailure", "variant": "100%"}],
            trace_ok=False,
        ),
        knowledge=_knowledge(),
    )
    assert traces_down["proposal"] is None

    traces_only = run_payment_incident(
        _alert("payment"),
        telemetry=_telemetry(0.01, traces=[{"error": True}]),
        knowledge=_knowledge(runbooks=["other-runbook"]),
    )
    assert traces_only["proposal"] is None

    other_flag = run_payment_incident(
        _alert("payment"),
        telemetry=_telemetry(0.4, flags=[{"flag": "cartFailure", "variant": "on"}]),
        knowledge=_knowledge(),
    )
    assert other_flag["flag_variant"] is None
    assert other_flag["proposal"] is None

    cart = run_payment_incident(_alert("cart"), telemetry=_telemetry(0.9), knowledge=_knowledge())
    assert cart["hypothesis"] == "This path investigates paymentFailure only."
    assert cart["proposal"] is None


def test_checkout_uses_the_payment_ratio_when_checkout_has_no_series():
    telemetry = Telemetry(
        ratio_series=[
            {"labels": {"service_name": "checkout"}},
            {"labels": {"service_name": "frontend"}, "value": 0.9},
            {"labels": {"service_name": "payment"}, "value": 0.4},
        ],
        traces=[{"error": True}],
        flags=[{"flag": "cartFailure", "variant": "on"}, {"flag": "paymentFailure", "variant": "100%"}],
    )
    investigation = run_payment_incident(_alert("checkout"), telemetry=telemetry, knowledge=_knowledge())
    assert investigation["error_ratio"] == 0.4
    assert investigation["proposal"]["arguments"]["variant"] == "off"

    quiet = Telemetry(ratio_series=[], traces=[], flags=telemetry.flags, trace_ok=False)
    missing = run_payment_incident(_alert("payment"), telemetry=quiet, knowledge=_knowledge())
    assert missing["error_ratio"] is None
    assert missing["proposal"] is None

    verified = verify_payment_incident(
        investigation,
        telemetry=Telemetry(
            ratio_series=[{"labels": {"service_name": "payment"}, "value": 0.01}],
            traces=[],
            flags=[],
        ),
    )
    assert verified["recovered"] is True
    unavailable = verify_payment_incident(
        investigation,
        telemetry=Telemetry(ratio_series=[], traces=[], flags=[], ratio_ok=False),
    )
    assert unavailable["recovered"] is False
    assert unavailable["follow_up_action"] is None


def test_the_default_tools_are_the_in_process_clients(monkeypatch):
    from knowledge.retrieval import incident_knowledge
    from tools.telemetry import client

    ratios = iter([0.4, 0.01])
    monkeypatch.setattr(
        client,
        "service_error_ratio",
        lambda window: Result(series=[{"labels": {"service_name": "payment"}, "value": next(ratios)}]),
    )
    monkeypatch.setattr(
        client,
        "get_traces",
        lambda service, only_errors=True, limit=5: Result(series=[{"error": True}]),
    )
    monkeypatch.setattr(
        client,
        "recent_changes",
        lambda: Result(series=[{"flag": "paymentFailure", "variant": "100%"}]),
    )
    monkeypatch.setattr(
        incident_knowledge,
        "review_incident_knowledge",
        lambda *args, **kwargs: {"runbook_ids": ["payment-failure"], "lessons": []},
    )

    investigation = run_payment_incident(_alert("payment"))
    assert investigation["proposal"]["dry_run"] is True
    verified = verify_payment_incident(investigation)
    assert verified["recovered"] is True


def _alert(service: str) -> Alert:
    return Alert(
        alert_name="ServiceErrorRateHigh",
        service=service,
        starts_at="2026-11-05T12:00:00Z",
        expression="error ratio",
        payload="{}",
    )


def _telemetry(ratio, traces=None, flags=None):
    if traces is None:
        traces = [{"error": True}]
    if flags is None:
        flags = [{"flag": "paymentFailure", "variant": "100%"}]
    return Telemetry(
        ratio_series=[{"labels": {"service_name": "payment"}, "value": ratio}],
        traces=traces,
        flags=flags,
    )


def _knowledge(runbooks=None):
    ids = ["payment-failure"] if runbooks is None else runbooks

    def knowledge(query, *, incident_service, incident_failure_family, incident_evidence):
        return {"runbook_ids": ids, "lessons": []}

    return knowledge
