import json

from fastapi.testclient import TestClient

from api.stream import snapshot_event
from incident_api.app import create_app


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


def client(tmp_path):
    application = create_app(str(tmp_path / "incidents.sqlite3"))
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
    assert "Approve note" in page.text
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

    edited = api.post(
        f"/incidents/{incident_id}/decision",
        json={"decision": "edit", "text": "set_flag paymentFailure off later"},
    )
    assert edited.status_code == 200
    body = edited.json()
    assert body["decision"] == "edit"
    assert body["approved_text"] is None
    assert body["command_text"] == "set_flag paymentFailure off later"
