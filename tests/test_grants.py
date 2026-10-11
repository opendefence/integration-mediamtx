"""Exercise atomic grant storage and durable revocation."""

import asyncio
import base64
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest
from cloudcoil.client import AsyncAPIClient
from cloudcoil.errors import APIError
from cloudcoil.models.kubernetes.core.v1 import Secret

from opendefence_integration_mediamtx.grants import (
    create_grant_record,
    list_grants_for_subject,
    load_grant,
    prune_retired_grants,
    retire_grant,
    revoke_grant,
)
from opendefence_integration_mediamtx.paths import StreamPath
from opendefence_integration_mediamtx.policy import MediaGrant
from opendefence_integration_mediamtx.reservations import Reservation, mark_cleanup_complete, reserve_grant

SUBJECT = UUID(int=1)
BINDING = UUID(int=2)
NOW = datetime(2026, 10, 11, 12, tzinfo=UTC)
NAMESPACE = "integration-mediamtx"
RESERVATION = Reservation(
    grant_id="g_" + "A" * 22,
    key_digest="a" * 64,
    request_digest="b" * 64,
    created_at=NOW,
    expires_at=NOW + timedelta(hours=1),
)
GRANT = MediaGrant(
    id=RESERVATION.grant_id,
    subject_id=SUBJECT,
    binding_uid=BINDING,
    stream=StreamPath(tool="ipcam", owner_callsign="alpha"),
    action="read",
    protocols=frozenset({"hls"}),
    password="A" * 24,  # nosec B105 # pragma: allowlist secret - Test-only credential
    created_at=NOW,
    expires_at=NOW + timedelta(hours=1),
)


class Kubernetes:
    def __init__(self) -> None:
        self.secret: dict[str, Any] | None = None
        self.creates = 0
        self.patches = 0
        self.conflicts = 0

    def respond(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            if request.url.path.endswith("/secrets"):
                assert request.url.params["labelSelector"] == (
                    f"app.kubernetes.io/managed-by=odintegration-mediamtx,mediamtx.opendefence.fi/subject-uid={SUBJECT}"
                )
                return httpx.Response(
                    200,
                    json={
                        "apiVersion": "v1",
                        "kind": "SecretList",
                        "metadata": {},
                        "items": [self.secret] if self.secret else [],
                    },
                )
            return (
                httpx.Response(200, json=self.secret)
                if self.secret
                else httpx.Response(404, json={"reason": "NotFound"})
            )
        if request.method == "POST":
            if self.secret:
                return httpx.Response(409, json={"reason": "AlreadyExists"})
            self.creates += 1
            self.secret = json.loads(request.content)
            self.secret["metadata"].update(uid=str(UUID(int=3)), resourceVersion="1")
            return httpx.Response(201, json=self.secret)
        assert request.method == "PATCH" and self.secret
        operations = json.loads(request.content)
        assert operations[:2] == [
            {"op": "test", "path": "/metadata/uid", "value": str(UUID(int=3))},
            {"op": "test", "path": "/metadata/resourceVersion", "value": self.secret["metadata"]["resourceVersion"]},
        ]
        assert operations[2:] == [{"op": "replace", "path": "/data/grant.json", "value": operations[2]["value"]}]
        if self.conflicts:
            self.conflicts -= 1
            return httpx.Response(409, json={"reason": "Conflict"})
        self.patches += 1
        self.secret["data"]["grant.json"] = operations[2]["value"]
        self.secret["metadata"]["resourceVersion"] = str(self.patches + 1)
        return httpx.Response(200, json=self.secret)


class LifecycleKubernetes:
    def __init__(self, events: list[str]) -> None:
        self.secrets: dict[str, dict[str, Any]] = {}
        self.events = events
        self.fail_ledger_patch_once = False

    def respond(self, request: httpx.Request) -> httpx.Response:  # noqa: PLR0911 - Mock each Kubernetes method.
        name = request.url.path.rsplit("/", 1)[-1]
        if request.method == "GET":
            secret = self.secrets.get(name)
            return httpx.Response(200, json=secret) if secret else httpx.Response(404, json={"reason": "NotFound"})
        if request.method == "POST":
            secret = json.loads(request.content)
            name = secret["metadata"]["name"]
            if name in self.secrets:
                return httpx.Response(409, json={"reason": "AlreadyExists"})
            secret["metadata"].update(uid=str(UUID(int=len(self.secrets) + 3)), resourceVersion="1")
            self.secrets[name] = secret
            self.events.append(f"create:{name}")
            return httpx.Response(201, json=secret)
        if request.method == "DELETE":
            secret = self.secrets.get(name)
            if secret is None:
                return httpx.Response(404, json={"reason": "NotFound"})
            assert json.loads(request.content)["preconditions"] == {
                "uid": secret["metadata"]["uid"],
                "resourceVersion": secret["metadata"]["resourceVersion"],
            }
            del self.secrets[name]
            self.events.append(f"delete:{name}")
            return httpx.Response(200, json={"apiVersion": "v1", "kind": "Status", "status": "Success"})
        assert request.method == "PATCH"
        secret = self.secrets[name]
        operations = json.loads(request.content)
        assert operations[:2] == [
            {"op": "test", "path": "/metadata/uid", "value": secret["metadata"]["uid"]},
            {
                "op": "test",
                "path": "/metadata/resourceVersion",
                "value": secret["metadata"]["resourceVersion"],
            },
        ]
        assert len(operations) == 3 and operations[2]["op"] == "replace"
        if name.startswith("mediamtx-reservations-") and self.fail_ledger_patch_once:
            self.fail_ledger_patch_once = False
            return httpx.Response(503, json={"reason": "ServiceUnavailable"})
        data_key = operations[2]["path"].removeprefix("/data/")
        secret["data"][data_key] = operations[2]["value"]
        secret["metadata"]["resourceVersion"] = str(int(secret["metadata"]["resourceVersion"]) + 1)
        self.events.append(f"patch:{name}")
        return httpx.Response(200, json=secret)


def client(http: httpx.AsyncClient, namespace: str = NAMESPACE) -> AsyncAPIClient[Secret]:
    return AsyncAPIClient(
        api_version="v1",
        kind=Secret,
        resource="secrets",
        subresources=[],
        default_namespace=namespace,
        namespaced=True,
        client=http,
    )


def test_concurrent_create_returns_only_the_stored_password() -> None:
    kube = Kubernetes()

    async def run() -> None:
        async with httpx.AsyncClient(
            base_url="https://kubernetes.test", transport=httpx.MockTransport(kube.respond)
        ) as http:
            first, second = await asyncio.gather(
                create_grant_record(client(http), RESERVATION, GRANT, now=NOW),
                create_grant_record(client(http), RESERVATION, replace(GRANT, password="B" * 24), now=NOW),
            )
            loaded = await load_grant(client(http), GRANT.id)
            assert first.password == second.password == loaded.password
            assert loaded.media_grant() == replace(GRANT, password=loaded.password)
            assert await list_grants_for_subject(client(http), SUBJECT) == [loaded]
            assert "B" * 24 not in repr(loaded)

    asyncio.run(run())
    assert kube.creates == 1 and kube.secret
    assert kube.secret["metadata"]["namespace"] == NAMESPACE
    assert kube.secret["metadata"]["labels"]["mediamtx.opendefence.fi/subject-uid"] == str(SUBJECT)
    assert GRANT.password not in json.dumps(kube.secret)


def test_mismatched_retry_and_tampered_secret_fail_closed() -> None:
    kube = Kubernetes()

    async def run() -> None:
        async with httpx.AsyncClient(
            base_url="https://kubernetes.test", transport=httpx.MockTransport(kube.respond)
        ) as http:
            secrets = client(http)
            await create_grant_record(secrets, RESERVATION, GRANT, now=NOW)
            with pytest.raises(ValueError, match="does not match"):
                await create_grant_record(secrets, RESERVATION, replace(GRANT, binding_uid=UUID(int=4)), now=NOW)
            with pytest.raises(ValueError, match="does not match"):
                await create_grant_record(
                    secrets, RESERVATION.model_copy(update={"request_digest": "c" * 64}), GRANT, now=NOW
                )
            with pytest.raises(ValueError, match="active reservation"):
                await create_grant_record(secrets, RESERVATION, GRANT, now=GRANT.expires_at)
            assert kube.secret
            kube.secret["data"]["grant.json"] = base64.b64encode(b"{}").decode()
            with pytest.raises(ValueError, match="Invalid grant Secret"):
                await load_grant(secrets, GRANT.id)

    asyncio.run(run())


def test_revocation_is_guarded_and_never_reopens_a_grant() -> None:
    kube = Kubernetes()

    async def run() -> None:
        async with httpx.AsyncClient(
            base_url="https://kubernetes.test", transport=httpx.MockTransport(kube.respond)
        ) as http:
            secrets = client(http)
            await create_grant_record(secrets, RESERVATION, GRANT, now=NOW)
            with pytest.raises(ValueError, match="subject"):
                await revoke_grant(secrets, UUID(int=5), GRANT.id, now=NOW)
            kube.conflicts = 1
            revoked = await revoke_grant(secrets, SUBJECT, GRANT.id, now=NOW + timedelta(minutes=1))
            assert revoked.revoked_at == NOW + timedelta(minutes=1)
            assert await revoke_grant(secrets, SUBJECT, GRANT.id, now=NOW + timedelta(minutes=2)) == revoked
            with pytest.raises(ValueError, match="does not match"):
                await create_grant_record(secrets, RESERVATION, GRANT, now=NOW + timedelta(minutes=2))

    asyncio.run(run())
    assert kube.patches == 1


def test_retirement_keeps_quota_pending_until_every_instance_drains() -> None:  # noqa: PLR0915 - One lifecycle.
    events: list[str] = []
    kube = LifecycleKubernetes(events)
    session_id = str(UUID(int=9))
    first_kicked = False
    second_fails = True
    grant_id = ""

    def first_media(request: httpx.Request) -> httpx.Response:
        nonlocal first_kicked
        events.append(f"first:{request.method}")
        if request.method == "POST":
            first_kicked = True
            return httpx.Response(404)
        return httpx.Response(
            200,
            json={
                "pageCount": 1,
                "items": [] if first_kicked else [{"id": session_id, "user": grant_id}],
            },
        )

    def second_media(request: httpx.Request) -> httpx.Response:
        events.append(f"second:{request.method}")
        if second_fails:
            return httpx.Response(503)
        return httpx.Response(200, json={"pageCount": 0, "items": []})

    async def run() -> None:
        nonlocal second_fails, grant_id
        async with (
            httpx.AsyncClient(base_url="https://kubernetes.test", transport=httpx.MockTransport(kube.respond)) as http,
            httpx.AsyncClient(base_url="https://first.test", transport=httpx.MockTransport(first_media)) as first,
            httpx.AsyncClient(base_url="https://second.test", transport=httpx.MockTransport(second_media)) as second,
        ):
            secrets = client(http)
            reservation = await reserve_grant(
                secrets, SUBJECT, "request-1", "b" * 64, now=NOW, expires_at=NOW + timedelta(hours=1)
            )
            grant = replace(GRANT, id=reservation.grant_id)
            grant_id = grant.id
            await create_grant_record(secrets, reservation, grant, now=NOW)
            with pytest.raises(ValueError, match="instance"):
                await retire_grant(secrets, SUBJECT, grant.id, (), now=NOW)
            assert (await load_grant(secrets, grant.id)).revoked_at is None
            with pytest.raises(httpx.HTTPStatusError):
                await retire_grant(secrets, SUBJECT, grant.id, (first, second), now=NOW + timedelta(minutes=1))
            assert (await load_grant(secrets, grant.id)).revoked_at == NOW + timedelta(minutes=1)
            reservation_name = f"mediamtx-reservations-{SUBJECT.hex}"

            def cleanup_complete() -> bool:
                encoded = kube.secrets[reservation_name]["data"]["reservations.json"]
                ledger = json.loads(base64.b64decode(encoded))
                return bool(ledger["entries"][reservation.key_digest]["cleanup_complete"])

            assert not cleanup_complete()
            second_fails = False
            retired = await retire_grant(secrets, SUBJECT, grant.id, (first, second), now=NOW + timedelta(minutes=2))
            assert retired.revoked_at == NOW + timedelta(minutes=1)
            assert cleanup_complete()
            with pytest.raises(ValueError, match="no longer active"):
                await reserve_grant(
                    secrets,
                    SUBJECT,
                    "request-1",
                    "b" * 64,
                    now=NOW + timedelta(minutes=2),
                    expires_at=NOW + timedelta(hours=1),
                )
            grant_name = next(name for name in kube.secrets if name.startswith("mediamtx-grant-"))
            assert events.index(f"patch:{grant_name}") < events.index("first:GET")
            assert events.index(f"patch:{reservation_name}") > events.index("second:GET")
            assert await prune_retired_grants(secrets, SUBJECT, now=NOW + timedelta(hours=23)) == 0
            kube.fail_ledger_patch_once = True
            with pytest.raises(APIError):
                await prune_retired_grants(secrets, SUBJECT, now=NOW + timedelta(hours=24))
            assert grant_name not in kube.secrets and cleanup_complete()
            assert await prune_retired_grants(secrets, SUBJECT, now=NOW + timedelta(hours=24)) == 1
            ledger = json.loads(base64.b64decode(kube.secrets[reservation_name]["data"]["reservations.json"]))
            assert ledger["entries"] == {}
            renewed = await reserve_grant(
                secrets,
                SUBJECT,
                "request-1",
                "b" * 64,
                now=NOW + timedelta(hours=24),
                expires_at=NOW + timedelta(hours=25),
            )
            assert renewed.grant_id != grant.id

    asyncio.run(run())


def test_pruning_rejects_a_grant_without_persisted_revocation() -> None:
    kube = LifecycleKubernetes([])

    async def run() -> None:
        async with httpx.AsyncClient(
            base_url="https://kubernetes.test", transport=httpx.MockTransport(kube.respond)
        ) as http:
            secrets = client(http)
            reservation = await reserve_grant(
                secrets, SUBJECT, "request-1", "b" * 64, now=NOW, expires_at=NOW + timedelta(hours=1)
            )
            await create_grant_record(secrets, reservation, replace(GRANT, id=reservation.grant_id), now=NOW)
            await mark_cleanup_complete(secrets, SUBJECT, reservation.key_digest, reservation.grant_id)
            with pytest.raises(ValueError, match="completed reservation"):
                await prune_retired_grants(secrets, SUBJECT, now=NOW + timedelta(hours=24))
            assert (await load_grant(secrets, reservation.grant_id)).revoked_at is None

    asyncio.run(run())
