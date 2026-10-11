"""Exercise reconciliation through the actual Kubernetes resource clients."""

import json
from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import httpx
import pytest
from cloudcoil.apimachinery import ObjectMeta, Time
from cloudcoil.client import AsyncAPIClient
from cloudcoil.controller import Request, ResourceKey
from cloudcoil.errors import APIError, ResourceConflict
from cloudcoil.models.kubernetes.core.v1 import Secret

from lib_opendefence_core.models.v1alpha1 import ResolvedRef, User, UserBinding, UserSpec, UserStatus

from opendefence_integration_mediamtx.bindings import USER_UUID_ANNOTATION
from opendefence_integration_mediamtx.operator import binding_keys, create_operator, reconcile_binding

NAMESPACE = "integration-mediamtx"
SUBJECT = UUID("01234567-89ab-cdef-0123-456789abcdef")
NAME = f"mediamtx-{SUBJECT.hex}"
BINDING_UID = "01234567-89ab-cdef-0123-456789abcdea"
NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)


def core_user() -> User:
    return User(
        kind="User",
        metadata=ObjectMeta(name="alpha", uid=str(SUBJECT), resource_version="5"),
        spec=UserSpec(callsign="alpha"),
    )


def stored_binding() -> dict[str, Any]:
    return {
        "apiVersion": "platform.opendefence.fi/v1alpha1",
        "kind": "UserBinding",
        "metadata": {
            "name": NAME,
            "namespace": NAMESPACE,
            "uid": BINDING_UID,
            "resourceVersion": "8",
            "generation": 2,
            "annotations": {USER_UUID_ANNOTATION: str(SUBJECT)},
            "labels": {"app.kubernetes.io/managed-by": "odintegration-mediamtx"},
        },
        "spec": {"userRef": {"name": "alpha"}},
    }


class Kubernetes:
    """Small HTTP fixture for identity reads and guarded status writes."""

    def __init__(self, binding: dict[str, Any] | None = None) -> None:
        self.binding = binding
        self.user = core_user().model_dump(mode="json", by_alias=True, exclude_none=True)
        self.user_code = 200
        self.patch_code = 200
        self.secret: dict[str, Any] | None = None
        self.requests: list[httpx.Request] = []

    def respond(self, request: httpx.Request) -> httpx.Response:  # noqa: PLR0911 - Explicit Kubernetes response cases.
        self.requests.append(request)
        assert request.method in {"GET", "POST", "PATCH"}
        if "/secrets" in request.url.path:
            assert f"/namespaces/{NAMESPACE}/secrets" in request.url.path
            if request.method == "POST":
                assert self.secret is None
                self.secret = json.loads(request.content)
                assert self.secret is not None
                self.secret["metadata"].update(uid=str(UUID(int=9)), resourceVersion="1")
                return httpx.Response(201, json=self.secret)
            return httpx.Response(200, json=self.secret) if self.secret else httpx.Response(404, json={})
        if request.url.path.endswith("/users/alpha"):
            assert request.method == "GET"
            return httpx.Response(self.user_code, json=self.user)
        assert f"/namespaces/{NAMESPACE}/userbindings" in request.url.path
        if request.method == "POST":
            if self.binding is not None:
                return httpx.Response(409, json={"reason": "AlreadyExists"})
            self.binding = json.loads(request.content)
            assert self.binding is not None
            self.binding["metadata"].update(uid=BINDING_UID, resourceVersion="8", generation=2)
            return httpx.Response(201, json=self.binding)
        if self.binding is None:
            return httpx.Response(404, json={"reason": "NotFound"})
        if request.method == "PATCH":
            assert request.url.path.endswith(f"/{NAME}/status")
            if self.patch_code != 200:
                return httpx.Response(self.patch_code, json={"reason": "Conflict"})
            operations = json.loads(request.content)
            assert operations[:2] == [
                {"op": "test", "path": "/metadata/uid", "value": BINDING_UID},
                {
                    "op": "test",
                    "path": "/metadata/resourceVersion",
                    "value": self.binding["metadata"]["resourceVersion"],
                },
            ]
            for operation in operations[2:]:
                path = operation["path"]
                assert operation["op"] in {"add", "replace"}
                if path == "/status":
                    self.binding["status"] = operation["value"]
                else:
                    assert path in {"/status/conditions", "/status/observedGeneration"}
                    self.binding["status"][path.rsplit("/", 1)[-1]] = operation["value"]
            self.binding["metadata"]["resourceVersion"] = str(int(self.binding["metadata"]["resourceVersion"]) + 1)
        return httpx.Response(200, json=self.binding)


def request_for(http: httpx.AsyncClient, users: list[User] | None = None) -> Request[UserBinding]:
    bindings = AsyncAPIClient(
        api_version="platform.opendefence.fi/v1alpha1",
        kind=UserBinding,
        resource="userbindings",
        subresources=["status"],
        default_namespace=NAMESPACE,
        namespaced=True,
        client=http,
    )
    core = AsyncAPIClient(
        api_version="platform.opendefence.fi/v1alpha1",
        kind=User,
        resource="users",
        subresources=[],
        default_namespace=NAMESPACE,
        namespaced=False,
        client=http,
    )
    request = Mock(spec=Request)
    request.key = ResourceKey(NAME, NAMESPACE)
    request.name = NAME
    request.namespace = NAMESPACE
    request.resource = None
    passwords = AsyncAPIClient(
        api_version="v1",
        kind=Secret,
        resource="secrets",
        subresources=[],
        default_namespace=NAMESPACE,
        namespaced=True,
        client=http,
    )
    request.client = AsyncMock(side_effect={UserBinding: bindings, User: core, Secret: passwords}.get)
    request.cached.return_value.list.return_value = [core_user()] if users is None else users
    return cast(Request[UserBinding], request)


@pytest.mark.asyncio
async def test_creates_pending_binding_and_restarts_without_duplicate_or_status_churn() -> None:
    kube = Kubernetes()
    async with httpx.AsyncClient(
        base_url="https://kubernetes.test", transport=httpx.MockTransport(kube.respond)
    ) as http:
        first = await reconcile_binding(request_for(http), namespace=NAMESPACE)
        # A restarted process has no saved reconciliation state.
        second = await reconcile_binding(request_for(http), namespace=NAMESPACE)
    assert first and second and first.requeue_after == second.requeue_after == 60
    assert kube.binding and kube.binding["spec"] == {"userRef": {"name": "alpha"}}
    status = kube.binding["status"]
    assert status["observedGeneration"] == 2
    assert status["conditions"][0]["status"] == "False"
    assert status["conditions"][0]["reason"] == "ProvisioningPending"
    assert [request.method for request in kube.requests] == ["GET", "GET", "POST", "PATCH", "GET", "GET"]


@pytest.mark.parametrize("state", ["active", "revoked", "unapproved", "replaced"])
@pytest.mark.asyncio
async def test_only_current_active_user_gets_a_stable_password(state: str) -> None:
    kube = Kubernetes(stored_binding())
    if state != "unapproved":
        kube.user["spec"]["approvedAt"] = NOW.isoformat()
    if state == "revoked":
        kube.user["spec"]["revokedAt"] = NOW.isoformat()
    if state == "replaced":
        kube.user["metadata"]["uid"] = str(UUID(int=7))
    async with httpx.AsyncClient(
        base_url="https://kubernetes.test", transport=httpx.MockTransport(kube.respond)
    ) as http:
        await reconcile_binding(request_for(http), namespace=NAMESPACE)
        await reconcile_binding(request_for(http), namespace=NAMESPACE)
    assert (kube.secret is not None) == (state == "active")
    writes = [request for request in kube.requests if "/secrets" in request.url.path and request.method == "POST"]
    assert len(writes) == (1 if state == "active" else 0)


@pytest.mark.parametrize("change", ["replaced", "deleting", "missing", "no-cached-user"])
@pytest.mark.asyncio
async def test_cached_user_cannot_create_binding_after_live_identity_changes(change: str) -> None:
    kube = Kubernetes()
    if change == "replaced":
        kube.user["metadata"]["uid"] = str(UUID(int=3))
    elif change == "deleting":
        kube.user["metadata"]["deletionTimestamp"] = NOW.isoformat()
    elif change == "missing":
        kube.user_code = 404
    async with httpx.AsyncClient(
        base_url="https://kubernetes.test", transport=httpx.MockTransport(kube.respond)
    ) as http:
        result = await reconcile_binding(
            request_for(http, [] if change == "no-cached-user" else None), namespace=NAMESPACE
        )
    assert result is None and kube.binding is None
    assert all(request.method == "GET" for request in kube.requests)


@pytest.mark.asyncio
async def test_clears_former_readiness_for_orphan_without_deleting_or_retargeting_binding() -> None:
    record = stored_binding()
    condition = {
        "type": "Synced",
        "status": "True",
        "reason": "Reconciled",
        "message": "Provisioning is complete.",
        "lastTransitionTime": NOW.isoformat(),
        "observedGeneration": 1,
    }
    other = {**condition, "type": "SessionsDrained", "status": "False"}
    record["status"] = {"observedGeneration": 1, "conditions": [condition, other]}
    kube = Kubernetes(record)
    kube.user_code = 404
    async with httpx.AsyncClient(
        base_url="https://kubernetes.test", transport=httpx.MockTransport(kube.respond)
    ) as http:
        await reconcile_binding(request_for(http, []), namespace=NAMESPACE)
    assert kube.binding and kube.binding["metadata"]["uid"] == BINDING_UID
    assert kube.binding["spec"] == {"userRef": {"name": "alpha"}}
    conditions = kube.binding["status"]["conditions"]
    assert conditions[0]["status"] == "False" and conditions[0]["observedGeneration"] == 2
    assert conditions[1]["type"] == "SessionsDrained" and conditions[1]["status"] == "False"
    assert [request.method for request in kube.requests] == ["GET", "PATCH", "GET"]


@pytest.mark.parametrize("change", ["owner", "namespace", "annotation", "name"])
@pytest.mark.asyncio
async def test_never_adopts_unrelated_bindings(change: str) -> None:
    record = stored_binding()
    if change == "owner":
        record["metadata"]["labels"] = {"app.kubernetes.io/managed-by": "another-integration"}
    elif change == "annotation":
        record["metadata"]["annotations"] = {USER_UUID_ANNOTATION: str(UUID(int=3))}
    else:
        record["metadata"][change] = "another-integration"
    kube = Kubernetes(record)
    async with httpx.AsyncClient(
        base_url="https://kubernetes.test", transport=httpx.MockTransport(kube.respond)
    ) as http:
        with pytest.raises(ValueError):
            await reconcile_binding(request_for(http), namespace=NAMESPACE)
    assert [request.method for request in kube.requests] == ["GET"]


@pytest.mark.asyncio
async def test_namespace_mismatch_rejected_before_any_request() -> None:
    kube = Kubernetes()
    async with httpx.AsyncClient(
        base_url="https://kubernetes.test", transport=httpx.MockTransport(kube.respond)
    ) as http:
        with pytest.raises(ValueError, match="namespace"):
            await reconcile_binding(request_for(http), namespace="another-integration")
    assert not kube.requests


@pytest.mark.asyncio
async def test_leaves_deleting_bindings_to_explicit_future_cleanup() -> None:
    record = stored_binding()
    record["metadata"]["deletionTimestamp"] = NOW.isoformat()
    kube = Kubernetes(record)
    async with httpx.AsyncClient(
        base_url="https://kubernetes.test", transport=httpx.MockTransport(kube.respond)
    ) as http:
        assert await reconcile_binding(request_for(http), namespace=NAMESPACE) is None
    assert [request.method for request in kube.requests] == ["GET"]


@pytest.mark.parametrize("code", [409, 422, 503])
@pytest.mark.asyncio
async def test_failures_propagate_and_next_pass_reads_a_new_status_baseline(code: int) -> None:
    kube = Kubernetes(stored_binding())
    kube.patch_code = code
    async with httpx.AsyncClient(
        base_url="https://kubernetes.test", transport=httpx.MockTransport(kube.respond)
    ) as http:
        with pytest.raises(ResourceConflict if code == 409 else APIError):
            await reconcile_binding(request_for(http), namespace=NAMESPACE)
        assert kube.binding
        kube.binding["metadata"]["resourceVersion"] = "20"
        kube.patch_code = 200
        await reconcile_binding(request_for(http), namespace=NAMESPACE)
    assert [request.method for request in kube.requests] == ["GET", "PATCH", "GET", "PATCH", "GET"]


@pytest.mark.asyncio
async def test_core_outage_is_not_treated_as_a_missing_user() -> None:
    kube = Kubernetes()
    kube.user_code = 503
    async with httpx.AsyncClient(
        base_url="https://kubernetes.test", transport=httpx.MockTransport(kube.respond)
    ) as http:
        with pytest.raises(APIError):
            await reconcile_binding(request_for(http), namespace=NAMESPACE)
    assert kube.binding is None


@pytest.mark.parametrize("change", ["valid", "deleting", "noncanonical", "namespaced", "missing"])
def test_user_events_map_only_canonical_cluster_identities(change: str) -> None:
    user = core_user()
    assert user.metadata
    if change == "deleting":
        user.metadata.deletion_timestamp = Time(NOW)
    elif change == "noncanonical":
        user.metadata.uid = str(SUBJECT).upper()
    elif change == "namespaced":
        user.metadata.namespace = "another-integration"
    elif change == "missing":
        user.metadata.uid = None
    expected: list[ResourceKey] = [ResourceKey(NAME, NAMESPACE)] if change in {"valid", "deleting"} else []
    assert binding_keys(user, namespace=NAMESPACE) == expected


def test_status_only_role_and_group_projection_update_requeues_the_same_binding() -> None:
    user = core_user()
    updated = user.model_copy(deep=True)
    assert updated.metadata
    updated.metadata.resource_version = "6"
    updated.status = UserStatus(
        roles=[ResolvedRef(name="superadmin", uid=str(UUID(int=4)))],
        groups=[ResolvedRef(name="medics", uid=str(UUID(int=5)))],
    )
    assert (
        binding_keys(user, namespace=NAMESPACE)
        == binding_keys(updated, namespace=NAMESPACE)
        == [ResourceKey(NAME, NAMESPACE)]
    )


def test_offline_manifests_preserve_core_ownership_and_namespace_scoping() -> None:
    app = create_operator(namespace=NAMESPACE)
    documents = app.manifests(image="example.test/mediamtx:test", command=["mediamtx-operator"])
    cluster_rules = next(document["rules"] for document in documents if document["kind"] == "ClusterRole")
    assert cluster_rules == [
        {"apiGroups": ["platform.opendefence.fi"], "resources": ["users"], "verbs": ["get", "list", "watch"]}
    ]
    role = next(document for document in documents if document["kind"] == "Role")
    assert role["metadata"]["namespace"] == NAMESPACE
    assert {rule["resources"][0] for rule in role["rules"]} == {"userbindings", "userbindings/status", "secrets"}
    assert next(rule["verbs"] for rule in role["rules"] if rule["resources"] == ["secrets"]) == ["create", "get"]
    assert all("delete" not in rule["verbs"] for rule in role["rules"])
    assert not any(document["kind"] in {"CustomResourceDefinition", "Service", "Secret"} for document in documents)
    deployment = next(document for document in documents if document["kind"] == "Deployment")
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    assert container["command"] == ["mediamtx-operator"] and container["args"] == ["run"]
    assert deployment["spec"]["replicas"] == 1
