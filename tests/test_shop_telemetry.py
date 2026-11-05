"""Read-only telemetry against recorded shop responses."""

import os

import httpx

from tools.telemetry import client
from tools.telemetry.settings import settings


class Response:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = {} if payload is None else payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeHTTP:
    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def __call__(self, timeout=15.0):
        self.timeout = timeout
        return self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, url, params=None):
        self.calls.append(("GET", url, params or {}))
        result = self.handler("GET", url, params or {}, None)
        if isinstance(result, Exception):
            raise result
        return result

    def post(self, url, json=None):
        self.calls.append(("POST", url, json))
        result = self.handler("POST", url, {}, json)
        if isinstance(result, Exception):
            raise result
        return result


def install(monkeypatch, handler):
    http = FakeHTTP(handler)
    monkeypatch.setattr(client.httpx, "Client", http)
    return http


def prometheus(payload, status="success"):
    return Response(payload={"status": status, "data": {"result": payload}, "error": "bad query"})


def test_settings_read_the_environment(monkeypatch):
    for name in (
        "PROMETHEUS_URL",
        "JAEGER_URL",
        "JAEGER_BASE_PATH",
        "OPENSEARCH_URL",
        "FLAGD_UI_URL",
        "DEFAULT_RANGE_WINDOW",
        "ERROR_RATIO_WINDOW",
        "COPILOT_CA_BUNDLE",
        "SSL_CERT_FILE",
        "REQUESTS_CA_BUNDLE",
    ):
        monkeypatch.delenv(name, raising=False)

    assert settings.PROMETHEUS_URL == "http://localhost:9090"
    assert settings.JAEGER_URL == "http://localhost:8080"
    assert settings.JAEGER_BASE_PATH == "/jaeger/ui"
    assert settings.OPENSEARCH_URL == "http://localhost:9200"
    assert settings.FLAGD_UI_URL == "http://localhost:4000"
    assert settings.DEFAULT_RANGE_WINDOW == "5m"
    assert settings.ERROR_RATIO_WINDOW == "5m"
    settings.apply_ca_bundle_to_env()
    assert "SSL_CERT_FILE" not in os.environ

    monkeypatch.setenv("PROMETHEUS_URL", "http://prom:9090/")
    monkeypatch.setenv("JAEGER_URL", "http://jaeger:16686/")
    monkeypatch.setenv("JAEGER_BASE_PATH", "/jaeger/")
    monkeypatch.setenv("OPENSEARCH_URL", "http://search:9200/")
    monkeypatch.setenv("FLAGD_UI_URL", "http://flags:4000/")
    monkeypatch.setenv("DEFAULT_RANGE_WINDOW", "15m")
    monkeypatch.setenv("ERROR_RATIO_WINDOW", "2m")
    monkeypatch.setenv("COPILOT_CA_BUNDLE", "/certs/ca.pem")
    assert settings.PROMETHEUS_URL == "http://prom:9090"
    assert settings.JAEGER_URL == "http://jaeger:16686"
    assert settings.JAEGER_BASE_PATH == "/jaeger"
    assert settings.OPENSEARCH_URL == "http://search:9200"
    assert settings.FLAGD_UI_URL == "http://flags:4000"
    assert settings.DEFAULT_RANGE_WINDOW == "15m"
    settings.apply_ca_bundle_to_env()
    assert os.environ["SSL_CERT_FILE"] == "/certs/ca.pem"
    assert os.environ["REQUESTS_CA_BUNDLE"] == "/certs/ca.pem"


def test_promql_parses_vectors_and_returns_prometheus_errors(monkeypatch):
    def handler(method, url, params, body):
        assert url.endswith("/api/v1/query")
        if params["query"] == "bad":
            return prometheus([], status="error")
        if params["query"] == "explode":
            return Response(payload=RuntimeError("not json"))
        return prometheus(
            [
                {"metric": {"__name__": "up", "job": "shop"}, "value": [1, "1.5"]},
                {"metric": {"__name__": "up"}, "values": [[1, "2"], [2, "3"]]},
                {"metric": {"__name__": "up"}},
            ]
        )

    install(monkeypatch, handler)

    parsed = client.promql("up")
    assert parsed.ok
    assert parsed.as_dict()["ok"] is True
    assert parsed.series[0]["labels"] == {"job": "shop"}
    assert parsed.series[0]["value"] == 1.5
    assert parsed.series[1]["values"] == [[1.0, 2.0], [2.0, 3.0]]
    assert "value" not in parsed.series[2]

    failed = client.promql("bad")
    assert failed.ok is False
    assert failed.error == "prometheus: bad query"

    unexpected = client.promql("explode")
    assert unexpected.error.startswith("unexpected:")

    def raise_http(method, url, params, body):
        return httpx.HTTPError("down")

    install(monkeypatch, raise_http)
    assert client.promql("up").error.startswith("request failed:")


def test_error_ratio_matches_the_paging_rule_and_keeps_the_rate(monkeypatch):
    seen = []

    def handler(method, url, params, body):
        seen.append(params["query"])
        return prometheus([{"metric": {"service_name": "payment"}, "value": [1, "0.4"]}])

    install(monkeypatch, handler)
    ratio = client.service_error_ratio()
    explicit = client.service_error_ratio("2m")
    rate = client.service_error_rates()
    client.service_error_rates("2m")
    client.service_request_rates()
    client.service_request_rates("2m")

    assert ratio.ok and ratio.series[0]["value"] == 0.4
    assert " / " in ratio.query
    assert "[5m]" in ratio.query
    assert "STATUS_CODE_ERROR" in ratio.query
    assert "[2m]" in explicit.query
    assert " / " not in rate.query
    assert "[5m]" in rate.query
    assert any("[2m]" in query and " / " not in query for query in seen)


def test_latency_uses_the_milliseconds_histogram(monkeypatch):
    def handler(method, url, params, body):
        if "duration_seconds_bucket" in params["query"]:
            raise AssertionError(params["query"])
        if 'service_name="missing"' in params["query"]:
            return prometheus([])
        if "service_name=" in params["query"]:
            return prometheus([{"metric": {"le": "100"}, "value": [1, "1500"]}])
        return prometheus(
            [
                {"metric": {"service_name": "payment"}, "value": [1, "2000"]},
                {"metric": {"service_name": "frontend"}},
            ]
        )

    install(monkeypatch, handler)
    latency = client.service_latency_p95()
    client.service_latency_p95("2m")
    assert "traces_span_metrics_duration_milliseconds_bucket" in latency.query
    assert latency.series[0]["value"] == 2.0
    assert "value" not in latency.series[1]
    assert client.service_p95_latency_s("payment") == 1.5
    assert client.service_p95_latency_s("missing") is None

    install(monkeypatch, lambda *args: prometheus([], status="error"))
    failed = client.service_latency_p95("2m")
    assert failed.ok is False


def test_metric_names_and_scalar_signals(monkeypatch):
    def handler(method, url, params, body):
        if url.endswith("/label/__name__/values"):
            return Response(payload={"data": ["up", "traces_span_metrics_calls_total"]})
        query = params.get("query", "")
        if 'container_name="missing"' in query or 'service_name="missing"' in query:
            return prometheus([])
        if 'container_name="blank"' in query:
            return prometheus([{"metric": {}}])
        if "delta(" in query:
            return prometheus([{"metric": {}, "value": [1, "100"]}])
        if "container_memory" in query:
            return prometheus([{"metric": {}, "value": [1, "150"]}])
        if "container_cpu" in query:
            return prometheus([{"metric": {}, "value": [1, "0.8"]}])
        if "kafka" in query:
            return prometheus([{"metric": {}, "value": [1, "12"]}])
        return prometheus([])

    install(monkeypatch, handler)
    assert [item["name"] for item in client.list_metric_names().series] == [
        "up",
        "traces_span_metrics_calls_total",
    ]
    assert [item["name"] for item in client.list_metric_names("SPAN").series] == [
        "traces_span_metrics_calls_total",
    ]
    assert client.service_cpu_ratio("payment") == 0.8
    assert client.service_memory_growth("payment") == 0.5
    assert client.service_kafka_lag("payment") == 12.0
    assert client.service_cpu_ratio("missing") is None
    assert client.service_cpu_ratio("blank") is None

    install(monkeypatch, lambda *args: httpx.HTTPError("names down"))
    assert client.list_metric_names().ok is False


def test_memory_growth_rejects_unusable_samples(monkeypatch):
    samples = {"now": "0", "before": "100"}

    def handler(method, url, params, body):
        value = samples["before"] if "delta(" in params["query"] else samples["now"]
        if value is None:
            return prometheus([])
        return prometheus([{"metric": {}, "value": [1, value]}])

    install(monkeypatch, handler)
    assert client.service_memory_growth("payment") is None
    samples["now"] = "10"
    samples["before"] = None
    assert client.service_memory_growth("payment") is None
    samples["before"] = "0"
    assert client.service_memory_growth("payment") is None
    samples["before"] = "-1"
    assert client.service_memory_growth("payment") is None


def test_traces_keep_error_spans_and_survive_a_missing_jaeger(monkeypatch):
    monkeypatch.setenv("JAEGER_URL", "http://localhost:8080")
    monkeypatch.setenv("JAEGER_BASE_PATH", "/jaeger")
    trace = {
        "data": [
            {
                "processes": {"p1": {"serviceName": "payment"}},
                "spans": [
                    {
                        "processID": "p1",
                        "operationName": "charge",
                        "duration": 2500,
                        "tags": [{"key": "error", "value": True}],
                    },
                    {
                        "processID": "p1",
                        "operationName": "ok",
                        "tags": [{"key": "error", "value": "false"}],
                    },
                    {"processID": "missing", "operationName": "bare"},
                ],
            }
        ]
    }

    def handler(method, url, params, body):
        assert url == "http://localhost:8080/jaeger/api/traces"
        if params["service"] == "down":
            return Response(status_code=503)
        if params["service"] == "explode":
            return httpx.HTTPError("connection refused")
        return Response(payload=trace)

    install(monkeypatch, handler)
    errors = client.get_traces("payment", limit=1)
    assert errors.ok
    assert errors.series == [{"service": "payment", "operation": "charge", "duration_ms": 2.5, "error": True}]
    mixed = client.get_traces("payment", only_errors=False)
    assert [item["operation"] for item in mixed.series] == ["charge", "ok", "bare"]
    assert mixed.series[2]["duration_ms"] == 0
    unavailable = client.get_traces("down")
    assert unavailable.ok is False
    assert "HTTP 503" in unavailable.error
    refused = client.get_traces("explode")
    assert "connection refused" in refused.error


def test_recent_changes_reads_flagd_and_ignores_flags_that_are_off(monkeypatch):
    monkeypatch.setenv("FLAGD_UI_URL", "http://flagd:4000/")

    def handler(method, url, params, body):
        assert url == "http://flagd:4000/api/read"
        return Response(
            payload={
                "flags": {
                    "paymentFailure": {"defaultVariant": "100%"},
                    "cartFailure": {"defaultVariant": "off"},
                    "adHighCpu": {"defaultVariant": None},
                    "imageSlowLoad": "bad",
                }
            }
        )

    install(monkeypatch, handler)
    changes = client.recent_changes()
    assert changes.series == [{"flag": "paymentFailure", "variant": "100%"}]

    install(monkeypatch, lambda *args: Response(status_code=404))
    assert "HTTP 404" in client.recent_changes().error
    install(monkeypatch, lambda *args: httpx.HTTPError("unreachable"))
    assert "unavailable" in client.recent_changes().error
    install(monkeypatch, lambda *args: Response(payload=["nope"]))
    assert client.recent_changes().error == "flag document has no flags"
    install(monkeypatch, lambda *args: Response(payload={"flags": ["nope"]}))
    assert client.recent_changes().error == "flag document has no flags"


def test_log_search_treats_bodies_as_data(monkeypatch):
    monkeypatch.setenv("OPENSEARCH_URL", "http://logs:9200")

    def handler(method, url, params, body):
        assert url == "http://logs:9200/otel-logs-*/_search"
        query = body["query"]["bool"]["must"][0]["query_string"]["query"]
        if query == "down":
            return Response(status_code=500)
        if query == "explode":
            return RuntimeError("timeout")
        if query == "plain":
            assert "filter" not in body["query"]["bool"]
            return Response(payload={"hits": {"hits": []}})
        assert body["query"]["bool"]["filter"] == [{"match": {"resource.service.name": "payment"}}]
        return Response(
            payload={
                "hits": {
                    "hits": [
                        {
                            "_source": {
                                "@timestamp": "t",
                                "severity": {"text": "ERROR"},
                                "body": "x" * 400,
                                "traceId": "abc",
                            }
                        },
                        {"_source": {"severity": "INFO", "body": None}},
                    ]
                }
            }
        )

    install(monkeypatch, handler)
    found = client.log_search("error", service="payment")
    assert found.ok
    assert found.series[0]["severity"] == "ERROR"
    assert len(found.series[0]["body"]) == 300
    assert found.series[1]["severity"] == "INFO"
    assert found.series[1]["body"] == "None"
    assert client.log_search("plain").series == []
    assert "HTTP 500" in client.log_search("down", service="payment").error
    assert "timeout" in client.log_search("explode", service="payment").error
