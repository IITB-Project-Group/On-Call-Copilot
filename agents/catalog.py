"""Shop facts the agents and the fixed baseline share: which flag injects which fault, where.

These are domain facts from the in-repo fault catalogue (flags, services, fault types), not
answers to any case. The fixed workflow (C0) uses them as its rules; the model-driven
specialists see the flag list in their prompt and must still find the evidence.
"""

from __future__ import annotations

from guardrail_core import FLAG_SERVICE_MAP

FLAG_FAULT_TYPE: dict[str, str] = {
    "paymentFailure": "error_injection",
    "paymentUnreachable": "dependency_unreachable",
    "cartFailure": "error_injection",
    "productCatalogFailure": "error_injection",
    "recommendationCacheFailure": "memory_leak",
    "kafkaQueueProblems": "queue_backlog",
    "adHighCpu": "resource_exhaustion",
    "adFailure": "error_injection",
    "adManualGc": "resource_exhaustion",
    "emailMemoryLeak": "memory_leak",
    "imageSlowLoad": "latency",
    "loadGeneratorFloodHomepage": "traffic_surge",
}
PRIMARY_SERVICE: dict[str, str] = {flag: sorted(services)[0] for flag, services in FLAG_SERVICE_MAP.items()}
PRIMARY_SERVICE["kafkaQueueProblems"] = "kafka"

# The observation that shows each fault type, as recorded by agents.toolbox.record_observations.
SIGNAL: dict[str, tuple[str, float]] = {
    "error_injection": ("error_ratio", 0.05),
    "dependency_unreachable": ("error_ratio", 0.05),
    "latency": ("p95_latency_s", 1.0),
    "resource_exhaustion": ("p95_latency_s", 1.0),
    "memory_leak": ("memory_growth", 0.1),
    "queue_backlog": ("kafka_lag", 1000.0),
    "traffic_surge": ("request_rate", 50.0),
}


def flags_text() -> str:
    return ", ".join(f"{flag} ({PRIMARY_SERVICE[flag]})" for flag in sorted(FLAG_FAULT_TYPE))
