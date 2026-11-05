"""Shared pytest fixtures for the On-Call Copilot test-suite.

* ``now``            fixed incident clock (2026-10-29 12:00 UTC, matching the test telemetry)
* ``ig``             InputGuardrails on that clock
* ``alert_payload``  a valid Alertmanager v4 webhook (checkout error rate above 5% for 5 minutes)
* ``span_exporter``  in-memory OpenTelemetry exporter (cleared per test)
* TELEMETRY is reset before every test so counter assertions are exact.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "safety"))
os.environ.setdefault("COPILOT_LLM", "off")        # deterministic policy in tests / CI
os.environ.setdefault("COPILOT_BACKEND", "sim")

from guardrail_core import TELEMETRY  # noqa: E402

try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    _EXPORTER = InMemorySpanExporter()
    _provider = TracerProvider()
    _provider.add_span_processor(SimpleSpanProcessor(_EXPORTER))
    trace.set_tracer_provider(_provider)
except Exception:  # pragma: no cover - OTel not installed
    _EXPORTER = None

NOW = datetime(2026, 10, 29, 12, 0, 0, tzinfo=timezone.utc)


def make_alert(now: datetime = NOW, alertname: str = "CheckoutErrorRateHigh", service: str = "checkout",
               severity: str = "critical", status: str = "firing") -> dict:
    """A valid Alertmanager v4 webhook body for the walkthrough alert."""
    return {
        "version": "4",
        "groupKey": "{}:{alertname=\"" + alertname + "\"}",
        "status": status,
        "receiver": "oncall-copilot",
        "groupLabels": {"alertname": alertname},
        "commonLabels": {"alertname": alertname, "service": service},
        "externalURL": "http://alertmanager:9093",
        "alerts": [{
            "status": status,
            "labels": {"alertname": alertname, "service": service, "severity": severity},
            "annotations": {"summary": "Checkout error rate above 5% for 5 minutes",
                            "description": "checkout error ratio is 0.18 over the last 5m"},
            "startsAt": (now - timedelta(minutes=6)).isoformat(),
            "endsAt": "0001-01-01T00:00:00Z",
            "generatorURL": "http://prometheus:9090/graph?g0.expr=checkout_error_ratio",
            "fingerprint": "c0ffee1234abcd",
        }],
    }


@pytest.fixture(autouse=True)
def _reset_telemetry():
    TELEMETRY.reset()
    yield


@pytest.fixture
def now() -> datetime:
    return NOW


@pytest.fixture
def ig(now):
    from input_guardrails import InputGuardrails

    return InputGuardrails(clock=lambda: now)


@pytest.fixture
def alert_payload(now) -> dict:
    return make_alert(now)


@pytest.fixture
def span_exporter():
    if _EXPORTER is None:
        pytest.skip("opentelemetry-sdk not installed")
    _EXPORTER.clear()
    yield _EXPORTER
    _EXPORTER.clear()
