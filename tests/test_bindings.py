"""Exercise the real resource client against atomic-create and guarded-write responses."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest
from cloudcoil.apimachinery import ObjectMeta, Time
from cloudcoil.client import AsyncAPIClient
from cloudcoil.errors import APIError, ResourceConflict
from pydantic import ValidationError

from opendefence_integration_mediamtx.bindings import (
    USER_UUID_ANNOTATION,
    CoreUser,
    PlatformCondition,
    UserBinding,
    UserBindingStatus,
    ensure_binding,
    set_binding_synced,
)

SUBJECT = UUID("01234567-89ab-cdef-0123-456789abcdef")
BINDING_UID = "01234567-89ab-cdef-0123-456789abcdea"
NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)
NAMESPACE = "integration-mediamtx"
NAME = f"mediamtx-{SUBJECT.hex}"


def user(subject: UUID = SUBJECT) -> CoreUser:
    return CoreUser(
        metadata=ObjectMeta(name="user-alpha", uid=str(subject), resource_version="5"),
        spec={"callsign": "ALPHA", "roleRefs": [{"name": "read-all"}]},
    )


def stored_binding() -> UserBinding:
    return UserBinding.model_validate(
        {
            "metadata": {
                "name": NAME,
                "namespace": NAMESPACE,
                "uid": BINDING_UID,
                "resourceVersion": "8",
                "generation": 2,
                "annotations": {USER_UUID_ANNOTATION: str(SUBJECT)},
                "labels": {"app.kubernetes.io/managed-by": "odintegration-mediamtx"},
            },
            "spec": {"userRef": {"name": "user-alpha"}},
        }
    )


def client(http: httpx.AsyncClient, namespace: str = NAMESPACE) -> AsyncAPIClient[UserBinding]:
    return AsyncAPIClient(
        api_version="platform.opendefence.fi/v1alpha1",
        kind=UserBinding,
        resource="userbindings",
        subresources=["status"],
        default_namespace=namespace,
        namespaced=True,
        client=http,
    )


def test_concurrent_create_returns_the_persisted_winner() -> None:
    records: dict[str, dict[str, Any]] = {}
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            body = json.loads(request.content)
            name = body["metadata"]["name"]
            if name in records:
                return httpx.Response(409, json={"reason": "AlreadyExists"})
            body["metadata"].update(uid=BINDING_UID, resourceVersion="1", generation=1)
            records[name] = body
            return httpx.Response(201, json=body)
        assert request.method == "GET"
        return httpx.Response(200, json=records[request.url.path.rsplit("/", 1)[-1]])

    async def run() -> None:
        async with httpx.AsyncClient(
            base_url="https://kubernetes.test", transport=httpx.MockTransport(respond)
        ) as http:
            bindings = await asyncio.gather(*(ensure_binding(user(), client(http)) for _ in range(8)))
        assert {binding.metadata.uid for binding in bindings if binding.metadata} == {BINDING_UID}
        assert all(binding.status is None for binding in bindings)

    asyncio.run(run())
    assert len(records) == 1
    record = records[NAME]
    assert record["spec"] == {"userRef": {"name": "user-alpha"}}
    assert "ownerReferences" not in record["metadata"]
    assert "status" not in record
    assert len([request for request in requests if request.method == "GET"]) == 7


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("metadata", "name", "another-binding"),
        ("metadata", "namespace", "another-integration"),
        ("metadata", "annotations", {USER_UUID_ANNOTATION: str(UUID(int=3))}),
        ("metadata", "labels", {}),
        ("metadata", "uid", None),
        ("metadata", "resourceVersion", None),
        ("metadata", "generation", 0),
        ("metadata", "deletionTimestamp", NOW.isoformat()),
        ("spec", "userRef", {"name": "another-user"}),
    ],
)
def test_does_not_adopt_or_retarget_mismatched_bindings(section: str, key: str, value: Any) -> None:
    body = stored_binding().model_dump(mode="json", by_alias=True, exclude_none=True)
    body[section][key] = value

    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={}) if request.method == "POST" else httpx.Response(200, json=body)

    async def run() -> None:
        async with httpx.AsyncClient(
            base_url="https://kubernetes.test", transport=httpx.MockTransport(respond)
        ) as http:
            with pytest.raises(ValueError):
                await ensure_binding(user(), client(http))

    asyncio.run(run())


def test_recreated_user_gets_a_separate_binding_even_with_the_same_resource_name() -> None:
    names: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        names.append(body["metadata"]["name"])
        body["metadata"].update(uid=BINDING_UID, resourceVersion="1", generation=1)
        return httpx.Response(201, json=body)

    async def run() -> None:
        async with httpx.AsyncClient(
            base_url="https://kubernetes.test", transport=httpx.MockTransport(respond)
        ) as http:
            await ensure_binding(user(), client(http))
            await ensure_binding(user(UUID(int=3)), client(http))

    asyncio.run(run())
    assert names == [NAME, f"mediamtx-{UUID(int=3).hex}"]


def test_synced_writes_only_status_with_uid_and_version_guards() -> None:
    requests: list[httpx.Request] = []
    original = stored_binding()

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        patch = json.loads(request.content)
        assert patch[:2] == [
            {"op": "test", "path": "/metadata/uid", "value": BINDING_UID},
            {"op": "test", "path": "/metadata/resourceVersion", "value": "8"},
        ]
        assert patch[2]["path"] == "/status"
        assert len(patch) == 3
        status = patch[2]["value"]
        assert set(status) == {"conditions", "observedGeneration"}
        assert status["observedGeneration"] == 2
        condition = status["conditions"][0]
        assert condition["type"] == "Synced"
        assert condition["observedGeneration"] == 2
        assert condition["status"] == "True"
        body = original.model_dump(mode="json", by_alias=True, exclude_none=True)
        body["status"] = status
        body["metadata"]["resourceVersion"] = "9"
        return httpx.Response(200, json=body)

    async def run() -> None:
        async with httpx.AsyncClient(
            base_url="https://kubernetes.test", transport=httpx.MockTransport(respond)
        ) as http:
            updated = await set_binding_synced(original, user(), client(http), synced=True, now=NOW)
            unchanged = await set_binding_synced(
                updated, user(), client(http), synced=True, now=NOW + timedelta(hours=1)
            )
            assert unchanged is updated
            assert updated.status and updated.status.conditions[0].last_transition_time == NOW

    asyncio.run(run())
    assert original.status is None
    assert len(requests) == 1
    assert requests[0].method == "PATCH" and requests[0].url.path.endswith(f"/{NAME}/status")
    assert requests[0].headers["content-type"] == "application/json-patch+json"


def test_status_change_preserves_other_conditions_and_updates_transition_time() -> None:
    binding = stored_binding()
    binding.status = UserBindingStatus(
        observed_generation=1,
        conditions=[
            PlatformCondition(
                type="Synced",
                status="True",
                reason="Reconciled",
                message="Provisioning is complete.",
                last_transition_time=NOW - timedelta(hours=1),
                observed_generation=1,
            ),
            PlatformCondition(
                type="SessionsDrained",
                status="False",
                reason="Pending",
                message="Session cleanup is pending.",
                last_transition_time=NOW - timedelta(hours=1),
            ),
        ],
    )

    def respond(request: httpx.Request) -> httpx.Response:
        patch = json.loads(request.content)
        changes = {operation["path"]: operation["value"] for operation in patch if operation["op"] != "test"}
        conditions = changes["/status/conditions"]
        assert conditions[1]["type"] == "SessionsDrained"
        assert conditions[0]["status"] == "False"
        assert conditions[0]["lastTransitionTime"] == "2026-10-10T12:00:00Z"
        assert changes["/status/observedGeneration"] == 2
        return httpx.Response(200, json=binding.model_dump(mode="json", by_alias=True, exclude_none=True))

    async def run() -> None:
        async with httpx.AsyncClient(
            base_url="https://kubernetes.test", transport=httpx.MockTransport(respond)
        ) as http:
            await set_binding_synced(binding, user(), client(http), synced=False, now=NOW)

    asyncio.run(run())


@pytest.mark.parametrize("code", [409, 422, 503])
def test_failed_status_write_propagates_without_retrying_stale_observations(code: int) -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(code, json={"reason": "Conflict"})

    async def run() -> None:
        async with httpx.AsyncClient(
            base_url="https://kubernetes.test", transport=httpx.MockTransport(respond)
        ) as http:
            with pytest.raises(ResourceConflict if code == 409 else APIError):
                await set_binding_synced(stored_binding(), user(), client(http), synced=True, now=NOW)

    asyncio.run(run())
    assert len(requests) == 1


@pytest.mark.parametrize("namespace", ["", "Other", "other/namespace", "a" * 64])
def test_refuses_invalid_namespace_before_any_request(namespace: str) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        pytest.fail(f"Unexpected request {request.method}")

    async def run() -> None:
        async with httpx.AsyncClient(
            base_url="https://kubernetes.test", transport=httpx.MockTransport(respond)
        ) as http:
            with pytest.raises(ValueError, match="namespace"):
                await ensure_binding(user(), client(http, namespace))

    asyncio.run(run())


@pytest.mark.parametrize("extra", ["accountId", "callsign", "observedPolicyRevision", "credentialRefs"])
def test_models_refuse_status_fields_that_the_shared_crd_would_prune(extra: str) -> None:
    with pytest.raises(ValidationError):
        UserBindingStatus.model_validate({extra: "unsupported"})


@pytest.mark.parametrize("invalid", ["duplicate", "naive-time"])
def test_refuses_invalid_conditions_before_writing(invalid: str) -> None:
    binding = stored_binding()
    condition = PlatformCondition(
        type="Synced",
        status="False",
        reason="Pending",
        message="Provisioning is incomplete.",
        last_transition_time=NOW if invalid == "duplicate" else NOW.replace(tzinfo=None),
    )
    binding.status = UserBindingStatus(conditions=[condition, condition] if invalid == "duplicate" else [condition])

    def respond(request: httpx.Request) -> httpx.Response:
        pytest.fail(f"Unexpected request {request.method}")

    async def run() -> None:
        async with httpx.AsyncClient(
            base_url="https://kubernetes.test", transport=httpx.MockTransport(respond)
        ) as http:
            with pytest.raises(ValueError, match="conditions"):
                await set_binding_synced(binding, user(), client(http), synced=True, now=NOW)

    asyncio.run(run())


@pytest.mark.parametrize("invalid", ["deleted", "missing-uid", "namespaced"])
def test_refuses_incomplete_or_deleted_users_before_creating(invalid: str) -> None:
    subject = user()
    assert subject.metadata
    if invalid == "deleted":
        subject.metadata.deletion_timestamp = Time(root=NOW)
    elif invalid == "missing-uid":
        subject.metadata.uid = None
    else:
        subject.metadata.namespace = NAMESPACE

    def respond(request: httpx.Request) -> httpx.Response:
        pytest.fail(f"Unexpected request {request.method}")

    async def run() -> None:
        async with httpx.AsyncClient(
            base_url="https://kubernetes.test", transport=httpx.MockTransport(respond)
        ) as http:
            with pytest.raises(ValueError):
                await ensure_binding(subject, client(http))

    asyncio.run(run())
