import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from tools.actions.set_flag import FlagWriteError, set_flag, set_payment_failure_off


FLAGS = {
    "paymentFailure": {
        "defaultVariant": "100%",
        "variants": {"off": 0, "100%": 1},
    }
}


def test_set_flag_writes_the_full_document_and_waits_until_it_is_served(monkeypatch):
    served = {"variant": "100%"}
    seen = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self._send({"flags": FLAGS})

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            if self.path == "/api/write":
                seen["write"] = body
                served["variant"] = body["data"]["flags"]["paymentFailure"]["defaultVariant"]
                self._send({})
                return
            self._send({"key": "paymentFailure", "variant": served["variant"], "value": 0})

        def _send(self, payload):
            raw = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, format, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    monkeypatch.setenv("FLAGD_UI_URL", base)
    monkeypatch.setenv("FLAGD_OFREP_URL", base)
    try:
        assert set_flag("paymentFailure", "off") == "paymentFailure is off"
        assert set_payment_failure_off() == "paymentFailure is off"
    finally:
        server.shutdown()
    written = seen["write"]["data"]
    assert written["$schema"].endswith("flags.json")
    assert written["flags"]["paymentFailure"]["defaultVariant"] == "off"


def _serve(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _point_at(monkeypatch, server):
    base = f"http://127.0.0.1:{server.server_address[1]}"
    monkeypatch.setenv("FLAGD_UI_URL", base)
    monkeypatch.setenv("FLAGD_OFREP_URL", base)
    return server


class _QuietHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def _send(self, payload, status=200):
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def test_set_flag_reports_a_missing_flag_or_variant(monkeypatch):
    class Handler(_QuietHandler):
        def do_GET(self):
            if "/missing" in self.path:
                self._send({"flags": {}})
                return
            if "/list" in self.path:
                self._send({"flags": ["paymentFailure"]})
                return
            self._send({"flags": {"paymentFailure": {"variants": {"100%": 1}}}})

    server = _point_at(monkeypatch, _serve(Handler))
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        monkeypatch.setenv("FLAGD_UI_URL", f"{base}/missing")
        with pytest.raises(FlagWriteError, match="not in the flag document"):
            set_flag("paymentFailure", "off")
        monkeypatch.setenv("FLAGD_UI_URL", f"{base}/list")
        with pytest.raises(FlagWriteError, match="not in the flag document"):
            set_flag("paymentFailure", "off")
        monkeypatch.setenv("FLAGD_UI_URL", base)
        with pytest.raises(FlagWriteError, match="has no variant"):
            set_flag("paymentFailure", "off")
    finally:
        server.shutdown()


def test_set_flag_stops_when_the_variant_never_changes(monkeypatch):
    class Handler(_QuietHandler):
        def do_GET(self):
            self._send({"flags": FLAGS})

        def do_POST(self):
            if self.path == "/api/write":
                self._send({})
                return
            self._send({"variant": "100%"})

    server = _point_at(monkeypatch, _serve(Handler))
    monkeypatch.setattr("tools.actions.set_flag.time.sleep", lambda _seconds: None)
    try:
        with pytest.raises(FlagWriteError, match="still 100%"):
            set_flag("paymentFailure", "off")
    finally:
        server.shutdown()


def test_set_flag_explains_a_bad_flag_service_response(monkeypatch):
    class Handler(_QuietHandler):
        def do_GET(self):
            if "/http" in self.path:
                self.send_error(500, "unavailable")
                return
            if "/empty" in self.path:
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if "/text" in self.path:
                raw = b"nope"
            elif "/list" in self.path:
                raw = b"[]"
            else:
                raw = b"{}"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = _point_at(monkeypatch, _serve(Handler))
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        monkeypatch.setenv("FLAGD_UI_URL", f"{base}/http")
        with pytest.raises(FlagWriteError, match="returned 500"):
            set_flag("paymentFailure", "off")
        monkeypatch.setenv("FLAGD_UI_URL", "http://127.0.0.1:9")
        with pytest.raises(FlagWriteError, match="unreachable"):
            set_flag("paymentFailure", "off")
        monkeypatch.setenv("FLAGD_UI_URL", f"{base}/empty")
        with pytest.raises(FlagWriteError, match="not in the flag document"):
            set_flag("paymentFailure", "off")
        monkeypatch.setenv("FLAGD_UI_URL", f"{base}/text")
        with pytest.raises(FlagWriteError, match="not JSON"):
            set_flag("paymentFailure", "off")
        monkeypatch.setenv("FLAGD_UI_URL", f"{base}/list")
        with pytest.raises(FlagWriteError, match="unexpected response"):
            set_flag("paymentFailure", "off")
    finally:
        server.shutdown()
