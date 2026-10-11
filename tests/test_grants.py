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
from cloudcoil.models.kubernetes.core.v1 import Secret

from opendefence_integration_mediamtx.grants import (
    create_grant_record,
    list_grants_for_subject,
    load_grant,
    revoke_grant,
)
from opendefence_integration_mediamtx.paths import StreamPath
from opendefence_integration_mediamtx.policy import MediaGrant
from opendefence_integration_mediamtx.reservations import Reservation

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
