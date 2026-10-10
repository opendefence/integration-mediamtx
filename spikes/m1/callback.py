"""Exercise package policy with explicit test projections, not a Core adapter."""

import hmac
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPSServer
from pathlib import Path
from typing import override
from uuid import UUID

from opendefence_integration_mediamtx.paths import parse_path
from opendefence_integration_mediamtx.policy import EffectivePolicy, MediaGrant, authorize_media

FIXTURES = Path("/fixtures")
GRANTS = json.loads((FIXTURES / "credentials.json").read_text())
EVENTS = Path("/tmp/events.jsonl")  # nosec B108 # Private single-container fixture filesystem.
START = datetime.now(UTC)
MEDIA_GRANTS: dict[str, MediaGrant] = {}
POLICIES: dict[str, EffectivePolicy] = {}
for username, record in GRANTS.items():
    if record["action"] == "api":
        continue
    stream = parse_path(record["path"])
    MEDIA_GRANTS[username] = MediaGrant(
        id=username,
        subject_id=stream.owner_id,
        binding_uid=UUID(int=2),
        stream=stream,
        action=record["action"],
        protocols=frozenset(record["protocols"]),
        password=record["password"],
        created_at=START,
        expires_at=START + timedelta(minutes=10),
    )
    POLICIES[username] = EffectivePolicy(
        subject_id=stream.owner_id,
        binding_uid=UUID(int=2),
        approved=True,
        assigned=True,
        revision="fixture-policy-1",
        evaluated_at=START,
        valid_until=START + timedelta(minutes=5),
        approval_deadline=START + timedelta(minutes=10),
        read_paths=frozenset({stream}),
        publish_own=True,
    )


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
            if grant and grant["action"] == "api":
                allowed = bool(
                    hmac.compare_digest(request.get("password", ""), grant["password"])
                    and request.get("action") == "api"
                    and request.get("path") == ""
                    and request.get("protocol") == ""
                )
            else:
                media_grant = MEDIA_GRANTS.get(request.get("user"))
                policy = POLICIES.get(request.get("user"))
                now = datetime.now(UTC)
                if media_grant and media_grant.action == "read" and Path("/tmp/deny-read").exists():  # nosec B108
                    media_grant = replace(media_grant, revoked_at=now)
                if policy and Path("/tmp/stale-policy").exists():  # nosec B108 # Fixture-controlled flag.
                    policy = replace(policy, valid_until=now)
                allowed = authorize_media(
                    request, media_grant, policy, now=now, enabled_protocols=frozenset({"rtsps", "hls"})
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
        ("0.0.0.0", 8443),  # nosec B104 # Private test Pod must accept MediaMTX callbacks.
        Callback,
        certfile=str(FIXTURES / "server.crt"),
        keyfile=str(FIXTURES / "server.key"),
    ).serve_forever()
