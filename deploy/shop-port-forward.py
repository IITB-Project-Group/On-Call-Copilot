"""Publish Prometheus, OpenSearch, and flagd on localhost for the copilot tools.

kubectl drops its listener when the pod connection resets. Each forward restarts.
"""

from __future__ import annotations

import os
import subprocess
import threading
import time


def forwards() -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for item in os.environ["SHOP_FORWARDS"].split(","):
        service, ports = item.split("=", 1)
        local, remote = ports.split(":")
        grouped.setdefault(service, []).append(f"{local}:{remote}")
    return grouped


def run(service: str, mappings: list[str]) -> None:
    command = [
        "kubectl",
        "--context",
        os.environ["KUBE_CONTEXT"],
        "--namespace",
        os.environ["NAMESPACE"],
        "port-forward",
        "--address",
        "127.0.0.1",
        f"svc/{service}",
        *mappings,
    ]
    while True:
        print(f"starting port-forward {service} {' '.join(mappings)}", flush=True)
        process = subprocess.Popen(command)
        code = process.wait()
        print(f"port-forward {service} exited {code}", flush=True)
        time.sleep(0.5)


def main() -> None:
    grouped = forwards()
    for service, mappings in grouped.items():
        threading.Thread(target=run, args=(service, mappings), daemon=True).start()
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
