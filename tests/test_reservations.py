"""Exercise Secret-backed reservation limits and idempotent retries."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest
from cloudcoil.client import AsyncAPIClient
from cloudcoil.models.kubernetes.core.v1 import Secret

from opendefence_integration_mediamtx.reservations import (
    MAX_ACTIVE,
    MAX_RETAINED,
    mark_cleanup_complete,
    reserve_grant,
)

SUBJECT = UUID("01234567-89ab-cdef-0123-456789abcdef")
NOW = datetime(2026, 10, 11, 12, tzinfo=UTC)
NAMESPACE = "integration-mediamtx"
DIGEST = "a" * 64


class Kubernetes:
    def __init__(self) -> None:
        self.secret: dict[str, Any] | None = None
        self.creates = 0
        self.patches = 0
        self.conflicts = 0

    def respond(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
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
            self.secret["metadata"].update(uid=str(UUID(int=1)), resourceVersion="1")
            return httpx.Response(201, json=self.secret)
        assert request.method == "PATCH" and self.secret
        operations = json.loads(request.content)
        assert operations[:2] == [
            {"op": "test", "path": "/metadata/uid", "value": str(UUID(int=1))},
            {"op": "test", "path": "/metadata/resourceVersion", "value": self.secret["metadata"]["resourceVersion"]},
        ]
        assert operations[2:] == [{"op": "replace", "path": "/data/reservations.json", "value": operations[2]["value"]}]
        if self.conflicts:
            self.conflicts -= 1
            return httpx.Response(409, json={"reason": "Conflict"})
        self.patches += 1
        self.secret["data"]["reservations.json"] = operations[2]["value"]
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


def test_concurrent_equal_keys_keep_one_random_grant_id() -> None:
    kube = Kubernetes()

    async def run() -> None:
        async with httpx.AsyncClient(
            base_url="https://kubernetes.test", transport=httpx.MockTransport(kube.respond)
        ) as http:
            records = await asyncio.gather(
                *(
                    reserve_grant(
                        client(http), SUBJECT, "same-key", DIGEST, now=NOW, expires_at=NOW + timedelta(hours=1)
                    )
                    for _ in range(8)
                )
            )
            assert {record.grant_id for record in records} == {records[0].grant_id}

    asyncio.run(run())
    assert kube.creates == 1
    assert kube.patches == 0
    assert kube.secret and kube.secret["metadata"]["name"] == f"mediamtx-reservations-{SUBJECT.hex}"
    assert kube.secret["metadata"]["namespace"] == NAMESPACE
    assert kube.secret["data"].keys() == {"reservations.json"}
    assert "same-key" not in json.dumps(kube.secret)


def test_distinct_keys_use_version_guarded_quota() -> None:
    kube = Kubernetes()

    async def run() -> None:
        async with httpx.AsyncClient(
            base_url="https://kubernetes.test", transport=httpx.MockTransport(kube.respond)
        ) as http:
            secrets = client(http)
            records = []
            for index in range(MAX_ACTIVE):
                if index == 1:
                    kube.conflicts = 1
                records.append(
                    await reserve_grant(
                        secrets, SUBJECT, f"key-{index}", DIGEST, now=NOW, expires_at=NOW + timedelta(hours=1)
                    )
                )
            assert len({record.grant_id for record in records}) == MAX_ACTIVE
            with pytest.raises(ValueError, match="limit"):
                await reserve_grant(secrets, SUBJECT, "one-more", DIGEST, now=NOW, expires_at=NOW + timedelta(hours=1))
            with pytest.raises(ValueError, match="different request"):
                await reserve_grant(secrets, SUBJECT, "key-0", "b" * 64, now=NOW, expires_at=NOW + timedelta(hours=1))
            assert (
                await reserve_grant(secrets, SUBJECT, "key-0", DIGEST, now=NOW, expires_at=NOW + timedelta(hours=1))
                == records[0]
            )

    asyncio.run(run())
    assert kube.creates == 1
    assert kube.patches == MAX_ACTIVE - 1


def test_expired_or_mismatched_records_fail_closed() -> None:
    kube = Kubernetes()

    async def run() -> None:
        async with httpx.AsyncClient(
            base_url="https://kubernetes.test", transport=httpx.MockTransport(kube.respond)
        ) as http:
            secrets = client(http)
            await reserve_grant(secrets, SUBJECT, "key", DIGEST, now=NOW, expires_at=NOW + timedelta(hours=1))
            with pytest.raises(ValueError, match="no longer active"):
                await reserve_grant(
                    secrets, SUBJECT, "key", DIGEST, now=NOW + timedelta(hours=1), expires_at=NOW + timedelta(hours=2)
                )
            assert kube.secret
            kube.secret["metadata"]["labels"] = {}
            with pytest.raises(ValueError, match="ownership mismatch"):
                await reserve_grant(secrets, SUBJECT, "key", DIGEST, now=NOW, expires_at=NOW + timedelta(hours=1))

    asyncio.run(run())


def test_cleanup_completion_releases_active_quota_but_keeps_retry_history() -> None:
    kube = Kubernetes()

    async def run() -> None:
        async with httpx.AsyncClient(
            base_url="https://kubernetes.test", transport=httpx.MockTransport(kube.respond)
        ) as http:
            secrets = client(http)
            first = await reserve_grant(secrets, SUBJECT, "key-0", DIGEST, now=NOW, expires_at=NOW + timedelta(hours=1))
            with pytest.raises(ValueError, match="mismatch"):
                await mark_cleanup_complete(secrets, SUBJECT, first.key_digest, "g_" + "b" * 22)
            kube.conflicts = 1
            complete = await mark_cleanup_complete(client(http), SUBJECT, first.key_digest, first.grant_id)
            assert complete.cleanup_complete
            assert await mark_cleanup_complete(client(http), SUBJECT, first.key_digest, first.grant_id) == complete
            with pytest.raises(ValueError, match="no longer active"):
                await reserve_grant(secrets, SUBJECT, "key-0", DIGEST, now=NOW, expires_at=NOW + timedelta(hours=1))
            for index in range(1, MAX_RETAINED):
                key = f"key-{index}"
                record = await reserve_grant(
                    secrets, SUBJECT, key, DIGEST, now=NOW, expires_at=NOW + timedelta(hours=1)
                )
                await mark_cleanup_complete(secrets, SUBJECT, record.key_digest, record.grant_id)
            with pytest.raises(ValueError, match="limit"):
                await reserve_grant(secrets, SUBJECT, "key-64", DIGEST, now=NOW, expires_at=NOW + timedelta(hours=1))

    asyncio.run(run())
    assert kube.creates == 1
    assert kube.patches == MAX_RETAINED * 2 - 1


@pytest.mark.parametrize("key,digest", [("", DIGEST), ("non-ascii-ä", DIGEST), ("good", "bad")])
def test_invalid_inputs_make_no_request(key: str, digest: str) -> None:
    kube = Kubernetes()

    async def run() -> None:
        async with httpx.AsyncClient(
            base_url="https://kubernetes.test", transport=httpx.MockTransport(kube.respond)
        ) as http:
            with pytest.raises(ValueError, match="scope"):
                await reserve_grant(client(http), SUBJECT, key, digest, now=NOW, expires_at=NOW + timedelta(hours=1))

    asyncio.run(run())
    assert kube.secret is None
