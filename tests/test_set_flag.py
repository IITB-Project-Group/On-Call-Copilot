import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from tools.actions.set_flag import set_flag


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
    finally:
        server.shutdown()
    written = seen["write"]["data"]
    assert written["$schema"].endswith("flags.json")
    assert written["flags"]["paymentFailure"]["defaultVariant"] == "off"
