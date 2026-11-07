"""A telemetry twin of the shop for offline runs: the same tool names, answered from a case's injection.

The twin turns a case's ``inject`` block (flags and variants) into the readings the live tools
would return: per-service metrics, error spans, logs and flag changes. It never exposes
``ground_truth``; the agents see only telemetry. Switching a flag off removes its effect one tick
later, so verification sees a realistic first sample.

It exists for development, tests and CI. The held-out evaluation runs against the live shop with
real fault injection (role 5); results from the twin are reported separately and labelled.
"""

from __future__ import annotations

import hashlib
import math
from datetime import datetime, timedelta, timezone
from typing import Any

from guardrail_core import FAILURE_FLAGS

from agents.toolbox import METRICS, TOPOLOGY, parse_metric_query, vector_response

TICK = timedelta(seconds=15)
RATE = {
    "frontend": 25,
    "frontend-proxy": 25,
    "checkout": 3,
    "payment": 3,
    "cart": 12,
    "valkey-cart": 12,
    "product-catalog": 30,
    "recommendation": 10,
    "ad": 10,
    "currency": 20,
    "shipping": 4,
    "quote": 4,
    "email": 2,
    "image-provider": 15,
    "accounting": 2,
    "fraud-detection": 2,
    "kafka": 6,
}
JVM = ("ad", "kafka", "fraud-detection")


def intensity(variant: str) -> float:
    text = str(variant).strip().lower()
    if text.endswith("%"):
        return float(text[:-1]) / 100
    if text.endswith("sec"):
        return float(text[:-3])
    if text.endswith("x"):
        return float(text[:-1])
    return 1.0


def _hex(*parts: Any, n: int) -> str:
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:n]


class ShopTwin:
    def __init__(self, case: dict, *, start: datetime | None = None):
        self.case = case
        self.start = start or datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=20)
        self.tick = 0
        self.flags = {flag: "off" for flag in FAILURE_FLAGS}
        self.flag_history: list[dict] = []
        self.fixed_at: dict[str, int] = {}
        for item in case.get("inject") or []:
            self.flags[item["flag"]] = str(item.get("variant", "on"))
            self.flag_history.append(
                {"flag": item["flag"], "from": "off", "to": self.flags[item["flag"]], "tick": -8}
            )
        if any(item.get("at") == "after_change" for item in case.get("inject") or []):
            self.flag_history += [
                {"flag": "adFailure", "from": "off", "to": "on", "tick": -40},
                {"flag": "adFailure", "from": "on", "to": "off", "tick": -30},
            ]
        self.load = 2.0 if case.get("load") == "raised" else 1.0

    def to_dict(self) -> dict:
        """Everything needed to rebuild the twin in another process (the stop-and-resume demo)."""
        return {
            "case": self.case,
            "start": self.start.isoformat(),
            "tick": self.tick,
            "flags": self.flags,
            "flag_history": self.flag_history,
            "fixed_at": self.fixed_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ShopTwin:
        twin = cls(data["case"], start=datetime.fromisoformat(data["start"]))
        twin.tick, twin.flags, twin.flag_history = data["tick"], data["flags"], data["flag_history"]
        twin.fixed_at = {k: int(v) for k, v in data["fixed_at"].items()}
        return twin

    # -------------------------------------------------------------- clock
    def now(self) -> datetime:
        return self.start + self.tick * TICK

    def _step(self) -> None:
        self.tick += 1

    def alert(self) -> dict:
        alert = dict(self.case.get("alert") or {})
        alert.setdefault("alert_name", "ServiceErrorRateHigh")
        alert.setdefault("service", "frontend")
        alert["starts_at"] = (self.start + 2 * TICK).isoformat()
        return alert

    # -------------------------------------------------------------- the shop's state
    def _active(self) -> dict[str, float]:
        out = {}
        for flag, variant in self.flags.items():
            if variant != "off":
                out[flag] = intensity(variant)
            elif (
                flag in self.fixed_at and self.tick <= self.fixed_at[flag] + 1
            ):  # effect fades one tick later
                out[flag] = intensity(self._last_on(flag))
        return out

    def _last_on(self, flag: str) -> str:
        return next(
            (h["from"] for h in reversed(self.flag_history) if h["flag"] == flag and h["to"] == "off"), "on"
        )

    def readings(self) -> dict[str, dict[str, float]]:
        m = {
            "error_ratio": {s: 0.002 for s in RATE} | {"frontend": 0.004},
            "request_rate": {s: r * self.load for s, r in RATE.items()},
            "p95_latency_s": {s: 0.12 for s in RATE} | {"frontend": 0.35, "checkout": 0.4},
            "cpu_ratio": {s: 0.25 * (1.3 if self.load > 1 else 1) for s in RATE},
            "memory_growth": {s: 0.01 for s in RATE},
            "kafka_lag": {"accounting": 5.0, "fraud-detection": 5.0},
            "gc_pause_ratio": {s: 0.01 for s in JVM},
        }
        e, lat = m["error_ratio"], m["p95_latency_s"]
        for flag, x in self._active().items():
            if flag == "paymentFailure":
                e["payment"], e["checkout"], e["frontend"] = (
                    max(e["payment"], x),
                    max(e["checkout"], 0.95 * x),
                    max(e["frontend"], 0.5 * x),
                )
            elif flag == "paymentUnreachable":
                e["checkout"], e["frontend"] = 0.9, max(e["frontend"], 0.45)
                m["request_rate"]["payment"] = 0.0
            elif flag == "cartFailure":
                e["cart"], e["frontend"], e["checkout"] = (
                    max(e["cart"], x),
                    max(e["frontend"], 0.6 * x),
                    max(e["checkout"], 0.4 * x),
                )
            elif flag == "productCatalogFailure":
                e["product-catalog"], e["frontend"] = 0.06, max(e["frontend"], 0.03)
            elif flag == "adFailure":
                e["ad"] = 0.1
            elif flag == "adHighCpu":
                m["cpu_ratio"]["ad"], lat["ad"], lat["frontend"] = 0.98, 1.8, max(lat["frontend"], 0.7)
            elif flag == "adManualGc":
                m["gc_pause_ratio"]["ad"], lat["ad"], m["cpu_ratio"]["ad"] = 0.42, 2.4, 0.55
            elif flag == "recommendationCacheFailure":
                m["memory_growth"]["recommendation"], lat["recommendation"] = 0.45, 1.4
                lat["frontend"] = max(lat["frontend"], 0.9)
            elif flag == "kafkaQueueProblems":
                m["kafka_lag"]["accounting"], m["kafka_lag"]["fraud-detection"] = 5200.0, 4800.0
            elif flag == "emailMemoryLeak":
                m["memory_growth"]["email"] = 0.1 + 0.1 * math.log10(max(x, 1.0))
            elif flag == "imageSlowLoad":
                lat["image-provider"], lat["frontend-proxy"] = x, 0.8 * x
            elif flag == "loadGeneratorFloodHomepage":
                m["request_rate"]["frontend"] = m["request_rate"]["frontend-proxy"] = 180.0
                lat["frontend"] = 1.2
        noise = self.case.get("noise")
        if noise == "flagd_stream":
            e["flagd"] = 1.0
        elif noise == "startup_burst" or any(
            i.get("at") == "startup_window" for i in self.case.get("inject") or []
        ):
            burst = max(0.0, 0.03 - 0.008 * self.tick)
            e["frontend"] = max(e["frontend"], 0.004 + burst)
        return m

    # -------------------------------------------------------------- read tools
    def tools(self) -> dict:
        return {
            "promql_query": self.promql_query,
            "log_search": self.log_search,
            "trace_search": self.trace_search,
            "trace_get": self.trace_get,
            "recent_changes": self.recent_changes,
            "service_topology": lambda: TOPOLOGY,
        }

    def promql_query(self, query: str, time: Any = None) -> dict:
        self._step()
        parsed = parse_metric_query(query)
        if parsed is None:
            return vector_response("query", {}, self.now().timestamp())
        values = self.readings()[METRICS[parsed[0]][0]]
        if parsed[1]:
            values = {k: v for k, v in values.items() if k == parsed[1]}
        return vector_response(parsed[0], values, self.now().timestamp())

    def _faulty(self, service: str) -> list[tuple[str, str, str]]:
        """(operation, status, message) for each error the active faults cause in a service."""
        active, out = self._active(), []
        if "paymentFailure" in active and service == "payment":
            out.append(("oteldemo.PaymentService/Charge", "ERROR", "Payment request failed. Invalid token."))
        if "paymentFailure" in active and service == "checkout":
            out.append(
                ("oteldemo.CheckoutService/PlaceOrder", "ERROR", "failed to charge card: Invalid token")
            )
        if "paymentUnreachable" in active and service == "checkout":
            out.append(
                (
                    "oteldemo.CheckoutService/PlaceOrder",
                    "ERROR",
                    "failed to charge card: rpc error: code = Unavailable desc = connection refused (payment)",
                )
            )
        if "cartFailure" in active and service in ("cart", "frontend"):
            out.append(
                (
                    "oteldemo.CartService/AddItem" if service == "cart" else "HTTP POST /api/cart",
                    "ERROR",
                    "Failed to add item to cart: Valkey connection error",
                )
            )
        if "productCatalogFailure" in active and service == "product-catalog":
            out.append(
                (
                    "oteldemo.ProductCatalogService/GetProduct",
                    "ERROR",
                    "Error: Product Catalog Fail Feature Flag Enabled",
                )
            )
        if "adFailure" in active and service == "ad":
            out.append(("oteldemo.AdService/GetAds", "ERROR", "fetch ads failed: ad failure flag"))
        if (
            service in ("ad", "recommendation", "image-provider", "frontend")
            and self.readings()["p95_latency_s"].get(service, 0) >= 1.0
        ):
            out.append((f"{service} request", "OK", "slow response"))
        return out

    def trace_search(
        self, service: str, lookback_s: int, limit: int = 10, status: str | None = None, operation=None
    ) -> list:
        self._step()
        spans = []
        for i, (op, span_status, message) in enumerate(self._faulty(service)[: max(1, limit)]):
            if status == "ERROR" and span_status != "ERROR":
                continue
            trace_id = _hex(self.case.get("id"), service, i, n=32)
            start = int(self.now().timestamp() * 1e9) - 60_000_000_000
            duration = 2_400_000_000 if span_status == "OK" else 35_000_000
            spans.append(
                {
                    "trace_id": trace_id,
                    "span_id": _hex(trace_id, service, n=16),
                    "parent_span_id": None,
                    "service": service,
                    "name": op,
                    "start_ns": start,
                    "end_ns": start + duration,
                    "status": span_status,
                    "attributes": {"status_message": message},
                }
            )
        return spans

    def trace_get(self, trace_id: str) -> list:
        for service in RATE:
            for span in self.trace_search(service, 1800, 10):
                if span["trace_id"] == trace_id:
                    return [span]
        return []

    def log_search(self, index: str, query: str, start: str, end: str, size: int = 20) -> list:
        self._step()
        wanted = index.removeprefix("otel-logs-").rstrip("*")
        services = [wanted] if wanted else list(RATE)
        rows = []
        for service in services:
            for op, span_status, message in self._faulty(service):
                if span_status == "ERROR":
                    rows.append(
                        {
                            "service": service,
                            "timestamp": self.now().isoformat(),
                            "severity": "ERROR",
                            "body": f"{op}: {message}",
                            "attributes": {},
                        }
                    )
        for text in self.case.get("log_lines") or []:
            if not wanted or wanted == text.get("service"):
                rows.append(
                    {
                        "service": text.get("service", "frontend"),
                        "timestamp": self.now().isoformat(),
                        "severity": "INFO",
                        "body": text["body"],
                        "attributes": text.get("attributes", {}),
                    }
                )
        return rows[:size]

    def recent_changes(self, lookback_s: int, service: str | None = None) -> list:
        self._step()
        return [
            {
                "type": "flag_change",
                "source": "flagd",
                "at": (self.start + h["tick"] * TICK).isoformat(),
                "flag": h["flag"],
                "from": h["from"],
                "to": h["to"],
                "actor": "flagd-ui",
                "message": "variant changed",
            }
            for h in self.flag_history
            if (self.tick - h["tick"]) * TICK.total_seconds() <= lookback_s + 900
        ]

    # -------------------------------------------------------------- flag service
    def read_flags(self) -> dict[str, str]:
        return dict(self.flags)

    def write_flag(self, flag: str, variant: str) -> str:
        self._step()
        before = self.flags.get(flag, "off")
        self.flags[flag] = variant
        self.flag_history.append({"flag": flag, "from": before, "to": variant, "tick": self.tick})
        if variant == "off" and before != "off":
            self.fixed_at[flag] = self.tick
        elif variant != "off":
            self.fixed_at.pop(flag, None)
        return f"{flag} is {variant}"
