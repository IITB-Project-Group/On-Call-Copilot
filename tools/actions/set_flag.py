"""Demo write: set one flag variant through the shop's flag service."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from copy import deepcopy


class FlagWriteError(RuntimeError):
    """The flag service did not accept or serve the requested variant."""


def set_payment_failure_off() -> str:
    return set_flag("paymentFailure", "off")


def set_flag(flag: str, variant: str) -> str:
    ui_url = os.environ.get("FLAGD_UI_URL", "http://flagd:4000").rstrip("/")
    ofrep_url = os.environ.get("FLAGD_OFREP_URL", "http://flagd:8016").rstrip("/")
    document = _request("GET", f"{ui_url}/api/read")
    flags = document.get("flags")
    if not isinstance(flags, dict) or flag not in flags:
        raise FlagWriteError(f"{flag} is not in the flag document")
    if variant not in (flags[flag].get("variants") or {}):
        raise FlagWriteError(f"{flag} has no variant {variant}")
    updated = deepcopy(flags)
    updated[flag]["defaultVariant"] = variant
    _request(
        "POST",
        f"{ui_url}/api/write",
        {
            "data": {
                "$schema": "https://flagd.dev/schema/v0/flags.json",
                "flags": updated,
            }
        },
    )
    _wait_until_served(ofrep_url, flag, variant)
    return f"{flag} is {variant}"


def _wait_until_served(ofrep_url: str, flag: str, variant: str) -> None:
    last = ""
    for attempt in range(8):
        served = _request(
            "POST",
            f"{ofrep_url}/ofrep/v1/evaluate/flags/{flag}",
            {},
        )
        last = str(served.get("variant") or "")
        if last == variant:
            return
        if attempt < 7:
            time.sleep(0.5)
    raise FlagWriteError(f"{flag} is still {last or 'unset'}")


def _request(method: str, url: str, body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            raw = response.read().decode()
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")[:200]
        raise FlagWriteError(f"flag service returned {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise FlagWriteError(f"flag service is unreachable: {error.reason}") from error
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as error:
        raise FlagWriteError("flag service returned a response that is not JSON") from error
    if not isinstance(parsed, dict):
        raise FlagWriteError("flag service returned an unexpected response")
    return parsed
