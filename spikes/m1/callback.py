"""Isolated protocol fixture. This is not the integration's policy implementation."""

import hmac
import json
from http.server import BaseHTTPRequestHandler, HTTPSServer
from pathlib import Path
from typing import override

FIXTURES = Path("/fixtures")
GRANTS = json.loads((FIXTURES / "credentials.json").read_text())
EVENTS = Path("/tmp/events.jsonl")


class Callback(BaseHTTPRequestHandler):
    @override
    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_POST(self) -> None:
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if self.path != "/auth" or not 0 < size <= 32768:
                raise ValueError("Invalid callback request")
            request = json.loads(self.rfile.read(size))
            grant = GRANTS.get(request.get("user"))
            allowed = bool(
                grant
                and hmac.compare_digest(request.get("password", ""), grant["password"])
                and request.get("action") == grant["action"]
                and request.get("path") == grant["path"]
                and request.get("protocol") in grant["protocols"]
                and not (grant["action"] == "read" and Path("/tmp/deny-read").exists())
            )
        except ValueError, TypeError, AttributeError:
            self.send_response(400)
            self.end_headers()
            return
        status = 204 if allowed else (401 if not request.get("user") else 403)
        # Store only the fields needed for assertions; never serialize the request.
        event = {
            "user": request.get("user") if grant else "<unknown>",
            "action": request.get("action") if request.get("action") in ("api", "publish", "read") else "<unknown>",
            "protocol": request.get("protocol") if request.get("protocol") in ("", "rtsp", "hls") else "<unknown>",
            "idIsNull": request.get("id") is None,
            "passwordEqualsToken": bool(request.get("password")) and request.get("password") == request.get("token"),
            "status": status,
        }
        with EVENTS.open("a") as output:
            output.write(json.dumps(event) + "\n")
        self.send_response(status)
        self.end_headers()


if __name__ == "__main__":
    HTTPSServer(
        ("0.0.0.0", 8443),
        Callback,
        certfile=str(FIXTURES / "server.crt"),
        keyfile=str(FIXTURES / "server.key"),
    ).serve_forever()
