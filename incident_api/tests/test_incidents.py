import json

from fastapi.testclient import TestClient

from api.stream import snapshot_event
from incident_api.app import create_app
from tools.actions import FlagWriteError


ALERT = {
    "alerts": [
        {
            "status": "firing",
            "labels": {"alertname": "CheckoutErrorRateHigh", "service": "checkout"},
            "annotations": {
                "expr": 'sum(rate(traces_span_metrics_calls_total{service_name="checkout"}[5m]))'
            },
            "startsAt": "2026-10-19T15:00:00Z",
        },
        {"status": "resolved", "labels": {"alertname": "Other"}, "startsAt": "2026-10-19T15:00:00Z"},
    ]
}


def client(tmp_path, on_approve=None):
    application = create_app(
        str(tmp_path / "incidents.sqlite3"),
        on_approve=on_approve or (lambda: "paymentFailure is off"),
    )
    return TestClient(application)


def test_webhook_stores_firing_alert(tmp_path):
    api = client(tmp_path)
    response = api.post("/webhooks/alert", json=ALERT)
    assert response.status_code == 200
    incidents = response.json()["incidents"]
    assert len(incidents) == 1
    incident = incidents[0]
    assert incident["alert_name"] == "CheckoutErrorRateHigh"
    assert incident["service"] == "checkout"
    assert incident["starts_at"] == "2026-10-19T15:00:00Z"
    assert "traces_span_metrics_calls_total" in incident["expression"]
    assert incident["decision"] is None
    assert incident["command_text"] == "CheckoutErrorRateHigh on checkout, started 2026-10-19T15:00:00Z."
    page = api.get("/")
    assert page.status_code == 200
    assert "A checkout or payment incident also sets paymentFailure to off" in page.text
    assert 'incident.decision !== "approve"' in page.text
    assert 'fetch("/incidents?state=" + view)' in page.text
    assert ">Closed<" in page.text
    assert "Query Prometheus used" in page.text

    again = api.post("/webhooks/alert", json=ALERT)
    assert again.json()["incidents"][0]["id"] == incident["id"]
    assert api.get("/metrics").text.count("copilot_incidents_total") >= 1


def test_stream_event_contains_the_incident(tmp_path):
    api = client(tmp_path)
    incident = api.post("/webhooks/alert", json=ALERT).json()["incidents"][0]
    event = snapshot_event(incident)
    assert event.startswith("data: ")
    payload = json.loads(event.removeprefix("data: ").strip())
    assert payload["id"] == incident["id"]
    assert payload["service"] == "checkout"


def test_edit_clears_approval(tmp_path):
    api = client(tmp_path)
    incident_id = api.post("/webhooks/alert", json=ALERT).json()["incidents"][0]["id"]
    approved = api.post(
        f"/incidents/{incident_id}/decision",
        json={"decision": "approve", "text": "set_flag paymentFailure off"},
    )
    assert approved.status_code == 200
    assert approved.json()["approved_text"] == "set_flag paymentFailure off"
    assert approved.json()["flag_result"] == "paymentFailure is off"

    edited = api.post(
        f"/incidents/{incident_id}/decision",
        json={"decision": "edit", "text": "set_flag paymentFailure off later"},
    )
    assert edited.status_code == 200
    body = edited.json()
    assert body["decision"] == "edit"
    assert body["approved_text"] is None
    assert body["command_text"] == "set_flag paymentFailure off later"


def test_approve_does_not_record_when_the_flag_write_fails(tmp_path):
    def fail():
        raise FlagWriteError("flagd did not accept the write")

    api = client(tmp_path, on_approve=fail)
    incident_id = api.post("/webhooks/alert", json=ALERT).json()["incidents"][0]["id"]
    failed = api.post(
        f"/incidents/{incident_id}/decision",
        json={"decision": "approve", "text": "set_flag paymentFailure off"},
    )
    assert failed.status_code == 502
    stored = api.get(f"/incidents/{incident_id}").json()
    assert stored["decision"] is None
    assert stored["approved_text"] is None


def test_open_query_returns_waiting_incidents_only(tmp_path):
    api = client(tmp_path)
    incident_id = api.post("/webhooks/alert", json=ALERT).json()["incidents"][0]["id"]
    assert [row["id"] for row in api.get("/incidents?state=open").json()] == [incident_id]

    approved = api.post(
        f"/incidents/{incident_id}/decision",
        json={"decision": "approve", "text": "set_flag paymentFailure off"},
    )
    assert approved.status_code == 200
    assert api.get("/incidents?state=open").json() == []
    assert [row["id"] for row in api.get("/incidents?state=closed").json()] == [incident_id]
    assert api.get("/incidents").json()[0]["decision"] == "approve"

    edited = api.post(
        f"/incidents/{incident_id}/decision",
        json={"decision": "edit", "text": "set_flag paymentFailure off later"},
    )
    assert edited.status_code == 200
    assert [row["id"] for row in api.get("/incidents?state=open").json()] == [incident_id]
    assert api.get("/incidents?state=closed").json() == []

    rejected = api.post(
        f"/incidents/{incident_id}/decision",
        json={"decision": "reject", "text": "set_flag paymentFailure off later"},
    )
    assert rejected.status_code == 200
    assert api.get("/incidents?state=open").json() == []
    assert [row["id"] for row in api.get("/incidents?state=closed").json()] == [incident_id]
    assert api.get("/incidents?state=other").status_code == 400


def test_same_alert_on_two_services_creates_two_incidents(tmp_path):
    api = client(tmp_path)
    first = api.post("/webhooks/alert", json=ALERT).json()["incidents"][0]
    other = {
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "ServiceErrorRateHigh", "service": "agent", "service_name": "agent"},
                "annotations": {"summary": "agent error rate is above 5% for 5 minutes."},
                "startsAt": "2026-10-19T15:00:00Z",
            }
        ]
    }
    # The checkout fixture uses a different alert name. Repeat the agent alert name on checkout too.
    checkout = {
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "ServiceErrorRateHigh", "service": "checkout"},
                "annotations": {"summary": "checkout error rate is above 5% for 5 minutes."},
                "startsAt": "2026-10-19T15:00:00Z",
            }
        ]
    }
    checkout_row = api.post("/webhooks/alert", json=checkout).json()["incidents"][0]
    agent_row = api.post("/webhooks/alert", json=other).json()["incidents"][0]
    assert checkout_row["id"] != agent_row["id"]
    assert {checkout_row["service"], agent_row["service"]} == {"checkout", "agent"}
    assert first["id"] != checkout_row["id"]


def test_approve_changes_the_payment_flag_only_for_checkout_or_payment(tmp_path):
    calls = []

    def change():
        calls.append("set")
        return "paymentFailure is off"

    api = client(tmp_path, on_approve=change)
    agent = api.post(
        "/webhooks/alert",
        json={
            "alerts": [
                {
                    "status": "firing",
                    "labels": {"alertname": "ServiceErrorRateHigh", "service": "agent"},
                    "annotations": {"summary": "agent error rate is above 5% for 5 minutes."},
                    "startsAt": "2026-10-26T06:40:00Z",
                }
            ]
        },
    ).json()["incidents"][0]
    approved = api.post(
        f"/incidents/{agent['id']}/decision",
        json={"decision": "approve", "text": "stop the runaway agent"},
    )
    assert approved.status_code == 200
    assert approved.json()["decision"] == "approve"
    assert "flag_result" not in approved.json()
    assert calls == []
