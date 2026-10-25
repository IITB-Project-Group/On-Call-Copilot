"""Keep localhost:8000 open while kubectl port-forward reconnects.

kubectl exits the whole listener when one streamed connection to the pod
resets. A failure in the shop can cause that reset. This process owns the
local port and dials a second, replaceable forward on port 18000.
"""

from __future__ import annotations

import os
import select
import socket
import subprocess
import threading
import time

LISTEN_PORT = int(os.environ.get("INCIDENT_PORT", "8000"))
UPSTREAM_PORT = 18000
UPSTREAM = ("127.0.0.1", UPSTREAM_PORT)


def run_forward() -> None:
    command = [
        "kubectl",
        "--context",
        os.environ["KUBE_CONTEXT"],
        "--namespace",
        os.environ["NAMESPACE"],
        "port-forward",
        "--address",
        "127.0.0.1",
        "svc/incident-api",
        f"{UPSTREAM_PORT}:8000",
    ]
    while True:
        print("starting kubectl port-forward", flush=True)
        process = subprocess.Popen(command)
        code = process.wait()
        print(f"kubectl port-forward exited {code}", flush=True)
        time.sleep(0.5)


def splice(client: socket.socket, upstream: socket.socket) -> None:
    sockets = [client, upstream]
    try:
        while True:
            readable, _, _ = select.select(sockets, [], [], 30)
            for sock in readable:
                data = sock.recv(65536)
                if not data:
                    return
                target = upstream if sock is client else client
                target.sendall(data)
    finally:
        for sock in (client, upstream):
            try:
                sock.close()
            except OSError:
                pass


def handle(client: socket.socket) -> None:
    upstream = None
    deadline = time.time() + 8
    while time.time() < deadline:
        try:
            upstream = socket.create_connection(UPSTREAM, timeout=1)
            break
        except OSError:
            time.sleep(0.2)
    if upstream is None:
        client.close()
        return
    splice(client, upstream)


def main() -> None:
    threading.Thread(target=run_forward, daemon=True).start()
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", LISTEN_PORT))
    server.listen(64)
    print(f"incident console listening on 127.0.0.1:{LISTEN_PORT}", flush=True)
    while True:
        client, _ = server.accept()
        threading.Thread(target=handle, args=(client,), daemon=True).start()


if __name__ == "__main__":
    main()
