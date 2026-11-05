"""
guardrail_core.py — shared vocabulary for the On-Call Copilot guardrails.

Imported by input_guardrails.py, output_guardrails.py, approval_service.py and hooks.py.

  * Domain constants: the Astronomy Shop services, flagd failure flags, fault taxonomy,
    allow-listed action types, protected / critical-path services, severities.
  * Decision / Finding / GuardrailResult: one result type for every guardrail.
  * @guarded(name): fail-closed wrapper. Any exception becomes a BLOCK; every call emits
    a span ``guardrail.<name>`` and counters, and NEVER carries raw content (codes only).
  * TELEMETRY: in-process metrics registry (counters + observations) that is also exported
    to Prometheus by oncall_copilot/observability.
  * canonical_json / sha256_hex / parse_timestamp helpers.
"""
from __future__ import annotations

import functools
import hashlib
import json
import math
import threading
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Iterable

# ============================================================================
# Domain constants (OpenTelemetry Astronomy Shop)
# ============================================================================
SHOP_SERVICES = frozenset({
    "frontend", "frontend-proxy", "checkout", "payment", "cart", "valkey-cart", "product-catalog",
    "recommendation", "ad", "email", "image-provider", "currency", "shipping", "quote", "kafka",
    "accounting", "fraud-detection", "load-generator",
})
PLATFORM_SERVICES = frozenset({"flagd", "otel-collector", "prometheus", "grafana", "jaeger", "opensearch"})
KNOWN_SERVICES = SHOP_SERVICES | PLATFORM_SERVICES
# The control and observability plane: the agent may read from it, never act on it.
PROTECTED_SERVICES = PLATFORM_SERVICES
ACTIONABLE_SERVICES = SHOP_SERVICES - {"load-generator"}
CRITICAL_PATH_SERVICES = frozenset({"frontend", "frontend-proxy", "checkout", "payment", "cart",
                                    "product-catalog", "currency", "shipping"})

FLAG_SERVICE_MAP: dict[str, frozenset[str]] = {
    "paymentFailure": frozenset({"payment"}),
    "paymentUnreachable": frozenset({"payment"}),
    "cartFailure": frozenset({"cart"}),
    "productCatalogFailure": frozenset({"product-catalog"}),
    "recommendationCacheFailure": frozenset({"recommendation"}),
    "kafkaQueueProblems": frozenset({"kafka", "accounting", "fraud-detection"}),
    "adHighCpu": frozenset({"ad"}),
    "adFailure": frozenset({"ad"}),
    "adManualGc": frozenset({"ad"}),
    "emailMemoryLeak": frozenset({"email"}),
    "imageSlowLoad": frozenset({"image-provider"}),
    "loadGeneratorFloodHomepage": frozenset({"frontend"}),
}
FAILURE_FLAGS = frozenset(FLAG_SERVICE_MAP)

FAULT_TAXONOMY = frozenset({
    "error_injection",        # a flag makes a service return errors (paymentFailure, cartFailure, ...)
    "bad_deploy",             # a release introduced errors -> roll back
    "crash",                  # process down -> restart
    "hang",                   # process alive but not answering -> restart
    "latency",                # slow dependency (imageSlowLoad)
    "resource_exhaustion",    # CPU saturation (adHighCpu)
    "memory_leak",            # emailMemoryLeak, recommendationCacheFailure
    "queue_backlog",          # kafkaQueueProblems
    "dependency_unreachable", # paymentUnreachable
    "traffic_surge",          # load spike -> scale
    "config_error",
    "no_fault",               # noisy alert: correct answer is "no action"
})

ALLOWED_ACTION_TYPES = frozenset({"set_flag", "restart_service", "scale_service", "rollback_deploy", "noop"})
SEVERITY_LEVELS = ("SEV1", "SEV2", "SEV3", "SEV4")
WILDCARD_TOKENS = frozenset({"*", "all", "any", "every", "everything", "all-services", "all_services",
                             "every-service", "services", "cluster", "*.*", "%"})
# Identities that must never count as a human reviewer / approver (case-insensitive).
AGENT_IDENTITIES = frozenset({
    "", "agent", "system", "assistant", "oncall-copilot", "copilot", "commander", "triage", "diagnosis",
    "investigator", "runbook", "remediation", "comms", "reflexion", "reflection", "reflector", "evaluator",
    "judge", "planner", "bot", "llm", "auto", "agent-reflection", "gpt-4.1-mini",
})


# ============================================================================
# Results
# ============================================================================
class Decision(str, Enum):
    ALLOW = "allow"
    REDACT = "redact"                       # passed, with content removed
    QUARANTINE = "quarantine"               # kept as evidence, flagged, never actionable
    REQUIRE_APPROVAL = "require_approval"   # needs a human
    BLOCK = "block"                         # rejected

    @property
    def rank(self) -> int:
        return _RANK[self]


_RANK = {Decision.ALLOW: 0, Decision.REDACT: 1, Decision.QUARANTINE: 2, Decision.REQUIRE_APPROVAL: 3,
         Decision.BLOCK: 4}


@dataclass
class Finding:
    guardrail: str
    code: str
    message: str
    action: Decision = Decision.ALLOW
    severity: str = "low"            # low | medium | high
    location: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"guardrail": self.guardrail, "code": self.code, "message": self.message,
                "action": self.action.value, "severity": self.severity, "location": self.location}


@dataclass
class GuardrailResult:
    guardrail: str
    decision: Decision
    findings: list[Finding] = field(default_factory=list)
    sanitized: Any = None

    @classmethod
    def from_findings(cls, guardrail: str, findings: Iterable[Finding], sanitized: Any = None) -> "GuardrailResult":
        findings = list(findings)
        decision = max((f.action for f in findings), key=lambda d: d.rank, default=Decision.ALLOW)
        return cls(guardrail, decision, findings, sanitized)

    # -- convenience views ---------------------------------------------------
    @property
    def allowed(self) -> bool:
        """Content may proceed (possibly redacted / quarantined as evidence)."""
        return self.decision in (Decision.ALLOW, Decision.REDACT, Decision.QUARANTINE)

    @property
    def blocked(self) -> bool:
        return self.decision is Decision.BLOCK

    @property
    def needs_approval(self) -> bool:
        return self.decision is Decision.REQUIRE_APPROVAL

    @property
    def quarantined(self) -> bool:
        return self.decision is Decision.QUARANTINE

    @property
    def codes(self) -> set[str]:
        """Set of finding codes (supports ``"x" in r.codes`` and ``{"a", "b"} <= r.codes``)."""
        return {f.code for f in self.findings}

    def to_dict(self) -> dict[str, Any]:
        return {"guardrail": self.guardrail, "decision": self.decision.value,
                "findings": [f.to_dict() for f in self.findings], "sanitized": self.sanitized}


def block(guardrail: str, code: str, message: str, sanitized: Any = None, severity: str = "high",
          location: str = "") -> GuardrailResult:
    return GuardrailResult(guardrail, Decision.BLOCK,
                           [Finding(guardrail, code, message, Decision.BLOCK, severity, location)], sanitized)


# ============================================================================
# Telemetry (metrics registry; spans via OpenTelemetry when installed)
# ============================================================================
def _key(labels: dict[str, Any]) -> tuple:
    return tuple(sorted((str(k), str(v)) for k, v in labels.items()))


class Telemetry:
    """Thread-safe counters and observations with label subsets.

    ``get(name, **labels)`` sums every series whose labels include the given ones, so
    ``get("agent.actions", classification="harmful")`` counts all harmful actions of any type.
    Values are numbers and short codes only -- never raw telemetry content.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, Counter] = defaultdict(Counter)
        self._obs: dict[str, list[tuple[tuple, float]]] = defaultdict(list)
        self._listeners: list[Callable[[str, str, float, dict], None]] = []

    def inc(self, name: str, value: float = 1, **labels: Any) -> None:
        with self._lock:
            self._counters[name][_key(labels)] += value
        for cb in list(self._listeners):
            cb("counter", name, value, labels)

    def observe(self, name: str, value: float, **labels: Any) -> None:
        with self._lock:
            self._obs[name].append((_key(labels), float(value)))
        for cb in list(self._listeners):
            cb("observation", name, float(value), labels)

    def get(self, name: str, **labels: Any) -> float:
        want = set(_key(labels))
        with self._lock:
            return sum(v for k, v in self._counters.get(name, {}).items() if want <= set(k))

    def observations(self, name: str, **labels: Any) -> list[float]:
        want = set(_key(labels))
        with self._lock:
            return [v for k, v in self._obs.get(name, []) if want <= set(k)]

    def record_redactions(self, redactions: Counter | dict) -> None:
        for kind, n in dict(redactions).items():
            self.inc("guardrail.redactions", n, kind=kind)

    def record_injection(self, source: str, code: str) -> None:
        self.inc("guardrail.injections", source=source, code=code)

    def add_listener(self, cb: Callable[[str, str, float, dict], None]) -> None:
        self._listeners.append(cb)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"counters": {n: {"|".join(f"{k}={v}" for k, v in key) or "_": val for key, val in c.items()}
                                 for n, c in self._counters.items()},
                    "observations": {n: [v for _, v in vals] for n, vals in self._obs.items()}}

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._obs.clear()


TELEMETRY = Telemetry()

try:  # OpenTelemetry is optional at runtime; tests install an in-memory exporter
    from opentelemetry import trace as _otel_trace

    def _tracer():
        return _otel_trace.get_tracer("oncall_copilot.guardrails")
except Exception:  # pragma: no cover
    _otel_trace = None

    def _tracer():
        return None


class _NullSpan:
    def set_attribute(self, *a: Any) -> None:
        pass

    def __enter__(self) -> "_NullSpan":
        return self

    def __exit__(self, *a: Any) -> None:
        return None


def start_span(name: str):
    t = _tracer()
    return t.start_as_current_span(name) if t is not None else _NullSpan()


def guarded(name: str) -> Callable:
    """Decorator: fail closed, count decisions/findings, emit a content-free span."""

    def deco(fn: Callable[..., GuardrailResult]) -> Callable[..., GuardrailResult]:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> GuardrailResult:
            with start_span(f"guardrail.{name}") as span:
                try:
                    result = fn(*args, **kwargs)
                    if not isinstance(result, GuardrailResult):
                        raise TypeError(f"{fn.__name__} must return GuardrailResult")
                except Exception as e:  # fail closed: a crashing guardrail never lets content through
                    result = block(name, "guardrail_error", f"{type(e).__name__} in guardrail; failed closed")
                TELEMETRY.inc("guardrail.decisions", guardrail=name, decision=result.decision.value)
                for code in dict.fromkeys(f.code for f in result.findings):
                    TELEMETRY.inc("guardrail.findings", guardrail=name, code=code)
                span.set_attribute("guardrail.name", name)
                span.set_attribute("guardrail.decision", result.decision.value)
                span.set_attribute("guardrail.codes", ",".join(dict.fromkeys(f.code for f in result.findings))[:512])
                span.set_attribute("guardrail.findings", len(result.findings))
                return result
        return wrapper
    return deco


# ============================================================================
# Helpers
# ============================================================================
def _default(o: Any) -> Any:
    if isinstance(o, datetime):
        return o.isoformat()
    if isinstance(o, (set, frozenset)):
        return sorted(o)
    if isinstance(o, Enum):
        return o.value
    return str(o)


def canonical_json(obj: Any) -> str:
    """Deterministic JSON (sorted keys, no whitespace) used for hashing."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_default)


def sha256_hex(data: str | bytes) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


def parse_timestamp(value: Any) -> datetime | None:
    """ISO-8601 string (with Z / offset), datetime or epoch seconds -> aware UTC datetime, else None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, (int, float)):
            if not math.isfinite(value):
                return None
            dt = datetime.fromtimestamp(float(value), tz=timezone.utc)
        elif isinstance(value, str):
            s = value.strip()
            if not s or len(s) > 40:
                return None
            if s.endswith(("Z", "z")):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
        else:
            return None
    except (ValueError, OverflowError, OSError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
