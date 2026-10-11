"""Exercise callsign credentials and live User role changes through the callback."""

import asyncio
import base64
import json
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

import httpx
import pytest
from cloudcoil.apimachinery import ObjectMeta
from cloudcoil.client import AsyncAPIClient
from cloudcoil.models.kubernetes.core.v1 import Secret
from lib_opendefence_core.models.v1alpha1 import User, UserSpec

from opendefence_integration_mediamtx.callback import AuthCallback
from opendefence_integration_mediamtx.credentials import ensure_user_password

NAMESPACE = "integration-mediamtx"
SUBJECT = UUID(int=1)
NOW = datetime(2026, 10, 11, tzinfo=UTC)
ROUTE = "/internal/mediamtx/auth"


class Kubernetes:
    def __init__(self) -> None:
        self.user = User(
            kind="User",
            metadata=ObjectMeta(name="alpha", uid=str(SUBJECT), resource_version="1"),
            spec=UserSpec(callsign="alpha", approved_at=NOW),
        ).model_dump(mode="json", by_alias=True, exclude_none=True)
        self.secrets: dict[str, dict[str, Any]] = {}
        self.user_code = 200
        self.requests: list[httpx.Request] = []

    async def respond(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        await asyncio.sleep(0)
        if "/users/" in request.url.path:
            assert request.method == "GET"
            assert request.url.path.endswith("/users/alpha")
            return httpx.Response(self.user_code, json=self.user)
        assert f"/namespaces/{NAMESPACE}/secrets" in request.url.path
        if request.method == "POST":
            body = json.loads(request.content)
            name = body["metadata"]["name"]
            if name in self.secrets:
                return httpx.Response(409, json={"reason": "AlreadyExists"})
            body["metadata"].update(uid=str(UUID(int=2)), resourceVersion="1")
            self.secrets[name] = body
            return httpx.Response(201, json=body)
        assert request.method == "GET"
        stored = self.secrets.get(request.url.path.rsplit("/", 1)[-1])
        return httpx.Response(200, json=stored) if stored else httpx.Response(404, json={"reason": "NotFound"})


def clients(http: httpx.AsyncClient) -> tuple[AsyncAPIClient[User], AsyncAPIClient[Secret]]:
    return (
        AsyncAPIClient(
            api_version="platform.opendefence.fi/v1alpha1",
            kind=User,
            resource="users",
            subresources=[],
            default_namespace=NAMESPACE,
            namespaced=False,
            client=http,
        ),
        AsyncAPIClient(
            api_version="v1",
            kind=Secret,
            resource="secrets",
            subresources=[],
            default_namespace=NAMESPACE,
            namespaced=True,
            client=http,
        ),
    )


@pytest.mark.asyncio
async def test_password_creation_is_atomic_and_restarts_reuse_the_stored_password() -> None:
    kube = Kubernetes()
    async with httpx.AsyncClient(
        base_url="https://kubernetes.test", transport=httpx.MockTransport(kube.respond)
    ) as http:
        _, passwords = clients(http)
        user = User.model_validate(kube.user)
        issued = await asyncio.gather(*(ensure_user_password(user, passwords) for _ in range(8)))
        assert len(set(issued)) == 1 and len(issued[0]) == 43
        assert await ensure_user_password(user, clients(http)[1]) == issued[0]
    assert len(kube.secrets) == 1
    secret = next(iter(kube.secrets.values()))
    assert secret["metadata"]["annotations"]["mediamtx.opendefence.fi/user-uuid"] == str(SUBJECT)
    assert "ownerReferences" not in secret["metadata"]


@pytest.mark.asyncio
async def test_callback_uses_current_roles_and_callsign_rules_without_a_media_role() -> None:
    kube = Kubernetes()
    async with httpx.AsyncClient(
        base_url="https://kubernetes.test", transport=httpx.MockTransport(kube.respond)
    ) as http:
        users, passwords = clients(http)
        password = await ensure_user_password(User.model_validate(kube.user), passwords)
        app = AuthCallback(users, passwords)
        async with httpx.AsyncClient(
            base_url="https://callback.test", transport=httpx.ASGITransport(app=cast(Any, app))
        ) as callback:
            payload = {
                "user": "alpha",
                "password": password,
                "token": password,
                "action": "read",
                "path": "live/ipcam/bravo",
                "protocol": "hls",
            }
            assert (await callback.post(ROUTE, json=payload)).status_code == 204
            for protocol in ("rtsp", "rtmp", "hls", "webrtc", "srt", "moq"):
                assert (await callback.post(ROUTE, json=payload | {"protocol": protocol})).status_code == 204
            assert (
                await callback.post(ROUTE, json=payload | {"action": "playback", "protocol": ""})
            ).status_code == 204
            publish = payload | {"action": "publish", "protocol": "rtsp", "path": "live/ipcam/alpha"}
            assert (await callback.post(ROUTE, json=publish)).status_code == 204
            for path in ("live/ipcam/alpha2", "live/ipcam/alpha/extra", "live/ipcam/%61lpha"):
                assert (await callback.post(ROUTE, json=publish | {"path": path})).status_code == 403
            control = payload | {"action": "api", "path": "", "protocol": ""}
            assert (await callback.post(ROUTE, json=control)).status_code == 403
            kube.user["spec"]["roleRefs"] = [{"name": "superadmin"}]
            kube.user["status"] = {"groups": [{"name": "superadmin", "uid": str(UUID(int=3))}]}
            assert (await callback.post(ROUTE, json=control)).status_code == 403
            kube.user["status"]["roles"] = [{"name": "superadmin", "uid": str(UUID(int=4))}]
            for action in ("api", "metrics", "pprof"):
                response = await callback.post(ROUTE, json=control | {"action": action})
                assert response.status_code == 204 and response.content == b""
                assert response.headers["cache-control"] == "no-store"
            assert (await callback.post(ROUTE, json=control | {"action": "unknown"})).status_code == 403
            assert (await callback.post(ROUTE, json=publish | {"path": "admin/any/path"})).status_code == 204
            assert (
                await callback.post(ROUTE, json=control | {"password": password + "x", "token": password + "x"})
            ).status_code == 403
            kube.user["status"]["roles"] = []
            assert (await callback.post(ROUTE, json=control)).status_code == 403
            kube.user["status"]["roles"] = [{"name": "superadmin", "uid": str(UUID(int=4))}]
            kube.user["spec"]["revokedAt"] = NOW.isoformat()
            assert (await callback.post(ROUTE, json=control)).status_code == 403
            assert (await callback.post(ROUTE, json=payload)).status_code == 403


@pytest.mark.parametrize("state", ["unapproved", "revoked"])
@pytest.mark.asyncio
async def test_inactive_users_cannot_create_a_password(state: str) -> None:
    kube = Kubernetes()
    if state == "unapproved":
        kube.user["spec"].pop("approvedAt")
    else:
        kube.user["spec"]["revokedAt"] = NOW.isoformat()
    async with httpx.AsyncClient(
        base_url="https://kubernetes.test", transport=httpx.MockTransport(kube.respond)
    ) as http:
        with pytest.raises(ValueError):
            await ensure_user_password(User.model_validate(kube.user), clients(http)[1])
    assert not kube.requests


@pytest.mark.parametrize("change", ["unapproved", "missing", "replaced", "deleting", "wrong-owner", "bad-secret"])
@pytest.mark.asyncio
async def test_invalid_user_or_credential_never_authorizes(change: str) -> None:
    kube = Kubernetes()
    async with httpx.AsyncClient(
        base_url="https://kubernetes.test", transport=httpx.MockTransport(kube.respond)
    ) as http:
        users, passwords = clients(http)
        password = await ensure_user_password(User.model_validate(kube.user), passwords)
        if change == "unapproved":
            kube.user["spec"].pop("approvedAt")
        elif change == "missing":
            kube.user_code = 404
        elif change == "replaced":
            kube.user["metadata"]["uid"] = str(UUID(int=8))
        elif change == "deleting":
            kube.user["metadata"]["deletionTimestamp"] = NOW.isoformat()
        elif change == "wrong-owner":
            next(iter(kube.secrets.values()))["metadata"]["labels"] = {}
        else:
            next(iter(kube.secrets.values()))["data"] = {"password": base64.b64encode(b"short").decode()}
        async with httpx.AsyncClient(
            base_url="https://callback.test",
            transport=httpx.ASGITransport(app=cast(Any, AuthCallback(users, passwords))),
        ) as callback:
            response = await callback.post(
                ROUTE,
                json={
                    "user": "alpha",
                    "password": password,
                    "action": "read",
                    "path": "live/ipcam/alpha",
                    "protocol": "hls",
                },
            )
            assert response.status_code == 403 and response.content == b""


@pytest.mark.asyncio
async def test_callback_rejects_bad_requests_and_denies_during_kubernetes_outage() -> None:
    kube = Kubernetes()
    async with httpx.AsyncClient(
        base_url="https://kubernetes.test", transport=httpx.MockTransport(kube.respond)
    ) as http:
        users, passwords = clients(http)
        password = await ensure_user_password(User.model_validate(kube.user), passwords)
        async with httpx.AsyncClient(
            base_url="https://callback.test",
            transport=httpx.ASGITransport(app=cast(Any, AuthCallback(users, passwords))),
        ) as callback:
            assert (await callback.get(ROUTE)).status_code == 405
            assert (await callback.post("/other")).status_code == 404
            for body in (b"not json", b"x" * 32769):
                assert (await callback.post(ROUTE, content=body)).status_code == 400
            payload = {
                "user": "alpha",
                "password": password,
                "action": "read",
                "path": "live/ipcam/alpha",
                "protocol": "hls",
            }
            for change in (
                {"user": "../alpha"},
                {"action": "unknown"},
                {"protocol": "unknown"},
                {"password": chr(0xD800)},
                {"token": password + "x"},
            ):
                assert (await callback.post(ROUTE, content=json.dumps(payload | change))).status_code == 403
            kube.user_code = 503
            response = await callback.post(ROUTE, json=payload)
            assert response.status_code == 503 and response.content == b""
