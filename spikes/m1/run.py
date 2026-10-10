"""Run the M1 spike in this checkout's owned Kind cluster; no production resources."""

# Keep sequential protocol assertions together and HTTP arguments explicit.
# ruff: noqa: PLR0913, PLR0917, PLR0915

import base64
import hashlib
import http.client
import json
import os
import secrets
import ssl
import subprocess  # nosec B404 # Harness runs developer tools with argument vectors.
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from uuid import UUID

from odintegration_mediamtx.paths import StreamPath

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STATE = ROOT / ".local/m1"
PACKAGE = ROOT / "src/odintegration_mediamtx"
PACKAGE_MODULES = ("__init__", "auth", "paths", "policy")
NAMESPACE = "mediamtx-m1"
MEDIA_PATH = str(StreamPath(tool="ipcam", owner_id=UUID("00000000-0000-4000-8000-000000000001")))
OTHER_PATH = str(StreamPath(tool="ipcam", owner_id=UUID("00000000-0000-4000-8000-000000000002")))
PREFIX = "/integrations/mediamtx/media/hls"
PUBLISHER = "g_" + "P" * 22
READER = "g_" + "R" * 22
IMAGES = json.loads((HERE / "images.json").read_text())
LOCAL_IMAGES = {name: f"localhost/mediamtx-m1-{name}:{image[-12:]}" for name, image in IMAGES.items()}


def run(*args: str, data: str | None = None) -> str:
    return subprocess.run(args, input=data, text=True, capture_output=True, check=True).stdout  # nosec B603


def kubectl(*args: str, data: str | None = None) -> str:
    cluster = (ROOT / ".local/kind/owner").read_text().strip()
    expected = "mediamtx-" + hashlib.sha256(str(ROOT).encode()).hexdigest()[:12]
    assert cluster == expected, "Refusing a cluster not owned by this checkout"
    return run(
        "kubectl",
        "--kubeconfig",
        str(ROOT / ".local/kind/kubeconfig"),
        "--context",
        "kind-" + cluster,
        "-n",
        NAMESPACE,
        *args,
        data=data,
    )


def apply(resource: dict[str, Any]) -> None:
    kubectl("apply", "-f", "-", data=json.dumps(resource))


def pod(name: str, image: str, command: list[str]) -> dict[str, Any]:
    resource: dict[str, Any] = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": name,
            "labels": {"app": name},
            "annotations": {"linkerd.io/inject": "disabled"},
        },
        "spec": {
            "automountServiceAccountToken": False,
            "restartPolicy": "Never",
            "containers": [
                {
                    "name": name,
                    "image": image,
                    "imagePullPolicy": "Never",
                    "command": command,
                    "volumeMounts": [
                        {"name": "fixtures", "mountPath": "/fixtures", "readOnly": True},
                        {"name": "config", "mountPath": "/config", "readOnly": True},
                    ],
                    "resources": {
                        "requests": {"cpu": "50m", "memory": "64Mi"},
                        "limits": {"cpu": "1", "memory": "256Mi"},
                    },
                }
            ],
            "volumes": [
                {"name": "fixtures", "secret": {"secretName": "fixtures"}},  # pragma: allowlist secret
                {
                    "name": "config",
                    "configMap": {
                        "name": "config",
                        "items": [
                            {"key": name, "path": name} for name in ("callback.py", "mediamtx.yml", "traefik.yml")
                        ]
                        + [
                            {"key": "package-" + module, "path": f"odintegration_mediamtx/{module}.py"}
                            for module in PACKAGE_MODULES
                        ],
                    },
                },
            ],
        },
    }
    port = {"auth": 8443, "media": 8322, "traefik": 8443}.get(name)
    if port is not None:
        resource["spec"]["containers"][0]["readinessProbe"] = {
            "tcpSocket": {"port": port},
            "periodSeconds": 1,
        }
    return resource


def service(name: str, ports: list[int]) -> None:
    apply(
        {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": name},
            "spec": {"selector": {"app": name}, "ports": [{"name": f"p{port}", "port": port} for port in ports]},
        }
    )


def request(
    port: int,
    path: str,
    context: ssl.SSLContext,
    headers: dict[str, str] | None = None,
    method: str = "GET",
    body: str | None = None,
) -> tuple[int, dict[str, str], bytes]:
    connection = http.client.HTTPSConnection("localhost", port, context=context, timeout=15)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def basic(user: str, password: str) -> dict[str, str]:
    value = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": "Basic " + value}


def forward(name: str, ports: list[str], log: Path) -> subprocess.Popen[bytes]:
    cluster = (ROOT / ".local/kind/owner").read_text().strip()
    with log.open("w") as output:
        process = subprocess.Popen(  # nosec B603 B607 # Developer kubectl from PATH, shell-free arguments.
            [
                "kubectl",
                "--kubeconfig",
                str(ROOT / ".local/kind/kubeconfig"),
                "--context",
                "kind-" + cluster,
                "-n",
                NAMESPACE,
                "port-forward",
                "--address",
                "127.0.0.1",
                "pod/" + name,
                *ports,
            ],
            stdout=output,
            stderr=subprocess.STDOUT,
        )
    for _ in range(100):
        if log.read_text().count("Forwarding from") == len(ports):
            return process
        if process.poll() is not None:
            raise RuntimeError("Port forward failed: " + log.read_text()[-1000:])
        time.sleep(0.1)
    process.terminate()
    process.wait(timeout=10)
    raise RuntimeError("Port forward timed out")


def check_protocol(
    context: ssl.SSLContext,
    credentials: dict[str, Any],
    report: dict[str, Any],
    forwards: list[subprocess.Popen[bytes]],
    local: Path,
) -> None:
    control = basic("control", credentials["control"]["password"])
    reader = basic(READER, credentials[READER]["password"])

    def api(path: str, method: str = "GET", body: str | None = None) -> tuple[int, dict[str, str], bytes]:
        return request(19997, "/v3/" + path, context, control | {"Content-Type": "application/json"}, method, body)

    def wait_api(expected_status: int) -> None:
        for _ in range(30):
            # kubectl exits when a forwarded listener closes during configuration reload.
            if forwards[0].poll() is not None:
                forwards[0] = forward("media", ["19997:9997", "18888:8888"], local / "media-forward.log")
            try:
                if api("paths/list")[0] == expected_status:
                    return
            except OSError, http.client.HTTPException:
                pass
            time.sleep(0.2)
        raise AssertionError(f"Control API did not return {expected_status}")

    for _ in range(120):
        status, _, body = api("paths/list")
        if status == 200 and any(item["ready"] for item in json.loads(body)["items"]):
            break
        time.sleep(0.5)
    else:
        raise AssertionError("RTSPS publisher did not become ready")
    report["rtspsPublish"] = True
    assert request(19997, "/v3/paths/list", context, reader)[0] == 401
    assert request(19997, "/v3/paths/list", context)[0] == 401
    report["mediaCredentialDeniedControl"] = True

    index = f"/{MEDIA_PATH}/index.m3u8?cookieCheck=1"
    assert request(18888, index, context)[0] == 401
    assert request(18888, index, context, basic(READER, "wrong-password"))[0] == 401
    assert request(18888, index, context, basic(PUBLISHER, credentials[PUBLISHER]["password"]))[0] == 401
    assert request(18888, index.replace(MEDIA_PATH, OTHER_PATH), context, reader)[0] == 401
    report["missingWrongPasswordActionPathDenied"] = True

    status, _, body = request(18888, index, context, reader)
    assert status == 200, "HLS read failed"
    child = next(line for line in body.decode().splitlines() if line and not line.startswith("#"))
    copied_query_url = urljoin(index, child)
    assert "session=" in copied_query_url
    status, headers, body = request(18888, index, context, reader | {"Cookie": "cookieCheck=1"})
    assert status == 200
    cookie = headers["Set-Cookie"].split(";", 1)[0]
    assert cookie.startswith("hlsSession=")
    child = next(line for line in body.decode().splitlines() if line and not line.startswith("#"))
    copied_cookie_url = urljoin(index, child)
    assert request(18888, copied_query_url, context)[0] == 200
    assert request(18888, copied_cookie_url, context, {"Cookie": cookie})[0] == 200

    kubectl("exec", "auth", "--", "touch", "/tmp/stale-policy")  # nosec B108 # Private fixture flag.
    assert request(18888, index, context, reader)[0] == 401
    assert api("paths/list")[0] == 200
    kubectl("exec", "auth", "--", "rm", "/tmp/stale-policy")  # nosec B108 # Private fixture flag.
    report["staleProjectionDeniesMediaButNotControl"] = True

    # This fixture flag simulates a revoked/expired reader, not a Core resource.
    kubectl("exec", "auth", "--", "touch", "/tmp/deny-read")  # nosec B108 # Private fixture flag.
    assert request(18888, index, context, reader)[0] == 401
    status, _, playlist = request(18888, copied_query_url, context)
    assert status == 200
    segment = next(line for line in playlist.decode().splitlines() if line and not line.startswith("#"))
    copied_segment_url = urljoin(copied_query_url, segment)
    status, _, payload = request(18888, copied_segment_url, context)
    assert status == 200 and len(payload) >= 188 and payload[0] == 0x47
    report["hlsSegmentBytesAfterDenial"] = len(payload)
    assert request(18888, copied_cookie_url, context, {"Cookie": cookie})[0] == 200
    report["denialAloneLeavesExistingHlsSessions"] = True

    sessions = []
    page = 0
    while True:
        status, _, body = api(f"hls/sessions/list?itemsPerPage=1&page={page}")
        assert status == 200
        listing = json.loads(body)
        sessions.extend(item for item in listing["items"] if item["user"] == READER)
        page += 1
        if page >= listing["pageCount"]:
            break
    assert len(sessions) == 2 and page >= 2
    start = time.monotonic()
    for session in sessions:
        assert api("hls/sessions/kick/" + session["id"], "POST")[0] == 200
    assert request(18888, copied_query_url, context)[0] == 401
    assert request(18888, copied_segment_url, context)[0] == 401
    assert request(18888, copied_cookie_url, context, {"Cookie": cookie})[0] == 401
    assert api("hls/sessions/kick/" + sessions[0]["id"], "POST")[0] == 404
    report["hlsKickSeconds"] = round(time.monotonic() - start, 3)
    report["paginatedSessionsMatchedByGrantUsername"] = len(sessions)
    assert json.loads(api("hls/sessions/list")[2])["itemCount"] == 0
    assert request(18888, index, context, reader)[0] == 401

    status, headers, _ = request(28443, PREFIX + f"/{MEDIA_PATH}/index.m3u8", context, reader)
    assert status == 302
    location = headers["Location"]
    assert location.startswith(f"/{MEDIA_PATH}/") and not location.startswith(PREFIX)
    assert request(28443, location, context, reader)[0] == 404
    report["stripPrefixRedirectEscapesPublicRoute"] = True

    event_log = kubectl("exec", "auth", "--", "cat", "/tmp/events.jsonl")  # nosec B108 # Private fixture log.
    for grant in credentials.values():
        assert grant["password"] not in event_log
    events = [json.loads(line) for line in event_log.splitlines()]
    assert any(e["user"] == PUBLISHER and e["protocol"] == "rtsp" and e["status"] == 204 for e in events)
    assert any(e["user"] == READER and e["passwordEqualsToken"] and e["status"] == 204 for e in events)
    assert any(e["action"] == "api" and e["idIsNull"] and e["status"] == 204 for e in events)
    report["callbackShapeVerified"] = True

    kubectl("exec", "auth", "--", "rm", "/tmp/deny-read")  # nosec B108 # Private fixture flag.
    status, _, body = request(18888, index, context, reader)
    assert status == 200
    child = next(line for line in body.decode().splitlines() if line and not line.startswith("#"))
    surviving_url = urljoin(index, child)
    kubectl("delete", "pod", "auth", "--grace-period=1", "--wait=true")
    wait_api(401)
    assert request(18888, index, context, reader)[0] == 401
    assert request(18888, surviving_url, context)[0] == 200
    assert api("paths/list")[0] == 401
    assert request(18888, surviving_url, context)[0] == 200
    report["callbackOutageDeniesNewAccessButNotExistingHls"] = True
    apply(pod("auth", LOCAL_IMAGES["python"], ["python", "/config/callback.py"]))
    kubectl("wait", "--for=condition=Ready", "pod/auth", "--timeout=60s")
    wait_api(200)

    assert api("config/global/patch", "PATCH", json.dumps({"authHTTPFingerprint": "00" * 32}))[0] == 200
    # This configuration update recreates listeners, so allow its brief TLS interruption.
    wait_api(401)
    assert request(18888, index, context, reader)[0] == 401
    assert request(18888, surviving_url, context)[0] == 401
    report["wrongCallbackPinDeniedAfterListenerRestart"] = True


def main() -> None:
    if not __debug__:
        raise RuntimeError("This spike needs assertions; do not run with Python -O")
    os.umask(0o077)
    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / "results.json").unlink(missing_ok=True)
    (STATE / "failure.log").unlink(missing_ok=True)
    for name, image in IMAGES.items():
        archive = STATE / (name + ".tar")
        run("podman", "pull", image)
        run("podman", "tag", image, LOCAL_IMAGES[name])
        run("podman", "save", "--format", "oci-archive", "-o", str(archive), LOCAL_IMAGES[name])
        run("bash", str(ROOT / "scripts/kind.sh"), "load", str(archive))
    package_source = {module: (PACKAGE / (module + ".py")).read_text() for module in PACKAGE_MODULES}
    report: dict[str, Any] = {
        "images": IMAGES,
        "policyImplementation": "odintegration_mediamtx.policy.authorize_media",
        "packageSourceSha256": {
            module: hashlib.sha256(source.encode()).hexdigest() for module, source in package_source.items()
        },
    }
    forwards: list[subprocess.Popen[bytes]] = []
    credentials: dict[str, Any] = {}
    kubectl("create", "namespace", NAMESPACE)
    try:
        with tempfile.TemporaryDirectory(prefix="run-", dir=STATE) as temporary:
            local = Path(temporary)
            run(
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "1",
                "-subj",
                "/CN=localhost",
                "-addext",
                "subjectAltName=DNS:localhost,DNS:auth,DNS:media",
                "-keyout",
                str(local / "server.key"),
                "-out",
                str(local / "server.crt"),
            )
            certificate = (local / "server.crt").read_text()
            fingerprint = hashlib.sha256(ssl.PEM_cert_to_DER_cert(certificate)).hexdigest()
            credentials = {
                "control": {"action": "api", "path": "", "protocols": [""]},
                PUBLISHER: {"action": "publish", "path": MEDIA_PATH, "protocols": ["rtsps"]},
                READER: {"action": "read", "path": MEDIA_PATH, "protocols": ["hls"]},
            }
            for grant in credentials.values():
                grant["password"] = secrets.token_urlsafe(24)
            apply(
                {
                    "apiVersion": "v1",
                    "kind": "Secret",
                    "metadata": {"name": "fixtures"},
                    "stringData": {
                        "server.crt": certificate,
                        "server.key": (local / "server.key").read_text(),
                        "credentials.json": json.dumps(credentials),
                        "publisher-password": credentials[PUBLISHER]["password"],
                    },
                }
            )
            media: dict[str, Any] = {
                "logLevel": "info",
                "authMethod": "http",
                "authHTTPAddress": "https://auth:8443/auth",
                "authHTTPFingerprint": fingerprint,
                "authHTTPExclude": [],
                "api": True,
                "apiEncryption": True,
                "apiServerKey": "/fixtures/server.key",
                "apiServerCert": "/fixtures/server.crt",
                "rtspEncryption": "strict",
                "rtspTransports": ["tcp"],
                "rtspServerKey": "/fixtures/server.key",
                "rtspServerCert": "/fixtures/server.crt",
                "rtmp": False,
                "srt": False,
                "webrtc": False,
                "moq": False,
                "hlsEncryption": True,
                "hlsVariant": "mpegts",
                "hlsServerKey": "/fixtures/server.key",
                "hlsServerCert": "/fixtures/server.crt",
                "paths": {MEDIA_PATH: {}, OTHER_PATH: {}},
            }
            traefik: dict[str, Any] = {
                "http": {
                    "routers": {
                        "hls": {
                            "rule": f"PathPrefix(`{PREFIX}/`)",
                            "service": "media",
                            "middlewares": ["strip"],
                            "tls": {},
                        }
                    },
                    "middlewares": {"strip": {"stripPrefix": {"prefixes": [PREFIX]}}},
                    "services": {
                        "media": {
                            "loadBalancer": {"servers": [{"url": "https://media:8888"}], "serversTransport": "trusted"}
                        }
                    },
                    "serversTransports": {"trusted": {"rootCAs": ["/fixtures/server.crt"]}},
                },
                "tls": {"certificates": [{"certFile": "/fixtures/server.crt", "keyFile": "/fixtures/server.key"}]},
            }
            apply(
                {
                    "apiVersion": "v1",
                    "kind": "ConfigMap",
                    "metadata": {"name": "config"},
                    "data": {
                        "callback.py": (HERE / "callback.py").read_text(),
                        "mediamtx.yml": json.dumps(media),
                        "traefik.yml": json.dumps(traefik),
                    }
                    | {"package-" + module: source for module, source in package_source.items()},
                }
            )
            apply(pod("auth", LOCAL_IMAGES["python"], ["python", "/config/callback.py"]))
            service("auth", [8443])
            apply(pod("media", LOCAL_IMAGES["media"], ["/mediamtx", "/config/mediamtx.yml"]))
            service("media", [8322, 8888, 9997])
            apply(
                pod(
                    "traefik",
                    LOCAL_IMAGES["traefik"],
                    [
                        "traefik",
                        "--entrypoints.websecure.address=:8443",
                        "--providers.file.filename=/config/traefik.yml",
                    ],
                )
            )
            kubectl("wait", "--for=condition=Ready", "pod/auth", "pod/media", "pod/traefik", "--timeout=90s")
            publisher = pod(
                "publisher",
                LOCAL_IMAGES["media"],
                [
                    "/bin/sh",
                    "-ec",
                    "exec ffmpeg -nostdin -loglevel error -re -f lavfi -i testsrc2=size=160x120:rate=10 "
                    "-c:v libx264 -preset ultrafast -tune zerolatency -g 10 -f rtsp -rtsp_transport tcp "
                    "-tls_verify 1 -ca_file /fixtures/server.crt "
                    f'"rtsps://{PUBLISHER}:$(cat /fixtures/publisher-password)@media:8322/{MEDIA_PATH}"',
                ],
            )
            # Service routing can lag Pod readiness; retry a failed initial connection.
            publisher["spec"]["restartPolicy"] = "OnFailure"
            apply(publisher)
            forwards.append(forward("media", ["19997:9997", "18888:8888"], local / "media-forward.log"))
            forwards.append(forward("traefik", ["28443:8443"], local / "traefik-forward.log"))
            check_protocol(
                ssl.create_default_context(cafile=str(local / "server.crt")), credentials, report, forwards, local
            )
            for name in ("publisher", "media", "auth", "traefik"):
                log = kubectl("logs", name)
                for user, grant in credentials.items():
                    assert grant["password"] not in log, "Fixture password found in logs"
                    assert basic(user, grant["password"])["Authorization"].split()[1] not in log
            report["currentPodLogsExcludeCredentials"] = True
            (STATE / "results.json").write_text(json.dumps(report, indent=2) + "\n")
            print(json.dumps(report, indent=2))
    except Exception:
        diagnostics = []
        for name in ("publisher", "media", "auth", "traefik"):
            try:
                log = kubectl("logs", name, "--tail=20")
            except subprocess.CalledProcessError:
                continue
            for user, grant in credentials.items():
                log = log.replace(grant["password"], "<redacted>")
                log = log.replace(basic(user, grant["password"])["Authorization"].split()[1], "<redacted>")
            diagnostics.append(name + ":\n" + log)
        (STATE / "failure.log").write_text("\n".join(diagnostics))
        raise
    finally:
        for process in forwards:
            process.terminate()
            process.wait(timeout=10)
        kubectl("delete", "namespace", NAMESPACE, "--wait=true", "--timeout=90s")


if __name__ == "__main__":
    main()
