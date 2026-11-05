"""Screen live shop data with the hardened injection detector."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from guardrail_core import Decision
from hardened_detector import HardenedInjectionDetector
from input_guardrails import DEFAULT_ALERT_RULES, InputGuardrails

_DOCUMENT_LISTS = ("runbooks", "passages", "postmortem_passages")


def guardrails(
    secret: bytes | None = None,
    allowed_alertnames: frozenset[str] | None = None,
) -> InputGuardrails:
    """Input guardrails that catch the obfuscations the baseline detector misses."""
    names = DEFAULT_ALERT_RULES if allowed_alertnames is None else allowed_alertnames
    return InputGuardrails(
        webhook_secret=secret,
        allowed_alertnames=names,
        detector=HardenedInjectionDetector(),
    )


def screen_log_series(series: Any) -> Any:
    """Redact secrets and quarantine instruction text in log lines and span names."""
    if not isinstance(series, list):
        return series
    return [_screen_log(row) for row in series]


def screen_retrieval(body: Any) -> Any:
    """Quarantine instruction text inside retrieved runbooks and postmortems."""
    if not isinstance(body, dict):
        return body
    screened = dict(body)
    for key in _DOCUMENT_LISTS:
        rows = screened.get(key)
        if not isinstance(rows, list):
            continue
        screened[key] = [_screen_document(row) for row in rows]
    return screened


def require_clean_descriptions(server: str, functions: Iterable[Callable]) -> None:
    """Refuse to register an MCP tool whose description carries an instruction."""
    detector = guardrails().detector
    for function in functions:
        findings = detector.scan(
            function.__doc__ or "",
            f"{server}.{function.__name__}",
            "mcp_tools",
            action=Decision.BLOCK,
        )
        if any(finding.action is Decision.BLOCK for finding in findings):
            raise RuntimeError(f"{server}.{function.__name__} description failed the injection check")


def _screen_log(row: Any) -> Any:
    if not isinstance(row, dict):
        return row
    updated = dict(row)
    quarantined = False
    for field, source in (("body", "log.body"), ("operation", "trace.span_name")):
        value = row.get(field)
        if not isinstance(value, str):
            continue
        replacement, flagged = _screen_string(value, source)
        if replacement is not None:
            updated[field] = replacement
        quarantined = quarantined or flagged
    attributes = row.get("attributes")
    if isinstance(attributes, dict):
        clean, flagged = _screen_attributes(attributes)
        updated["attributes"] = clean
        quarantined = quarantined or flagged
    updated["quarantined"] = quarantined
    return updated


def _screen_attributes(attributes: dict) -> tuple[dict, bool]:
    clean: dict[str, Any] = {}
    quarantined = False
    for key, value in attributes.items():
        if not isinstance(value, str):
            clean[key] = value
            continue
        replacement, flagged = _screen_string(value, "log.attribute")
        clean[key] = value if replacement is None else replacement
        quarantined = quarantined or flagged
    return clean, quarantined


def _screen_document(row: Any) -> Any:
    if not isinstance(row, dict) or not isinstance(row.get("text"), str):
        return row
    replacement, quarantined = _screen_string(row["text"], "runbook.body")
    if replacement is None:
        return {**row, "quarantined": False}
    return {**row, "text": replacement, "quarantined": quarantined}


def _screen_string(text: str, source: str) -> tuple[str | None, bool]:
    result = guardrails().screen_text(text, source, source)
    if result.quarantined:
        return result.wrapped, True
    if result.redactions:
        return result.clean, False
    return None, False
