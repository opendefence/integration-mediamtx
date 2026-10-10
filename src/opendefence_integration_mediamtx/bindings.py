"""Integration-owned provisioning observations, matching Core's shared CRD."""

import re
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from cloudcoil.apimachinery import ObjectMeta
from cloudcoil.client import AsyncAPIClient
from cloudcoil.errors import ResourceConflict
from cloudcoil.patches import diff
from cloudcoil.pydantic import BaseModel
from cloudcoil.resources import Resource
from pydantic import ConfigDict, Field

from opendefence_integration_mediamtx.paths import parse_user_id

USER_UUID_ANNOTATION = "mediamtx.opendefence.fi/user-uuid"
# Keep the persisted ownership label stable across Python package renames.
MANAGED_BY = "odintegration-mediamtx"


class CoreUser(Resource):
    """Read-only User view; permission references remain opaque to this adapter."""

    # Cloudcoil requires concrete wire literals over its mutable Any | None base fields.
    api_version: Literal["platform.opendefence.fi/v1alpha1"] = Field(  # pyrefly: ignore[bad-override-mutable-attribute]
        default="platform.opendefence.fi/v1alpha1", alias="apiVersion"
    )
    kind: Literal["User"] = "User"  # pyrefly: ignore[bad-override-mutable-attribute]
    spec: dict[str, object]
    status: dict[str, object] | None = None


class ObjectRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)


class UserBindingSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_ref: ObjectRef = Field(alias="userRef")


class PlatformCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str
    status: Literal["True", "False", "Unknown"]
    reason: str
    message: str
    last_transition_time: datetime = Field(alias="lastTransitionTime")
    observed_generation: Annotated[int | None, Field(strict=True, alias="observedGeneration")] = None


class UserBindingStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conditions: list[PlatformCondition] = Field(default_factory=list)
    observed_generation: Annotated[int | None, Field(strict=True, alias="observedGeneration")] = None


class UserBinding(Resource):
    api_version: Literal["platform.opendefence.fi/v1alpha1"] = Field(  # pyrefly: ignore[bad-override-mutable-attribute]
        default="platform.opendefence.fi/v1alpha1", alias="apiVersion"
    )
    kind: Literal["UserBinding"] = "UserBinding"  # pyrefly: ignore[bad-override-mutable-attribute]
    spec: UserBindingSpec
    status: UserBindingStatus | None = None


def _user_identity(user: CoreUser) -> tuple[str, UUID]:
    meta = user.metadata
    if not meta or not meta.name or not meta.uid or not meta.resource_version or meta.deletion_timestamp:
        raise ValueError("A current Core User is required")
    subject_id = parse_user_id(meta.uid)
    if str(subject_id) != meta.uid or meta.namespace is not None:
        raise ValueError("Invalid Core User metadata")
    return meta.name, subject_id


def _namespace(client: AsyncAPIClient[UserBinding]) -> str:
    namespace = client.default_namespace
    if (
        client.kind is not UserBinding
        or not client.namespaced
        or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", namespace)
    ):
        raise ValueError("A namespace-scoped UserBinding client is required")
    return namespace


def _binding_identity(binding: UserBinding, namespace: str) -> UUID:
    meta = binding.metadata
    subject = (meta.annotations or {}).get(USER_UUID_ANNOTATION, "") if meta else ""
    subject_id = parse_user_id(subject)
    if (
        not meta
        or meta.name != f"mediamtx-{subject_id.hex}"
        or meta.namespace != namespace
        or not meta.uid
        or not meta.resource_version
        or meta.generation is None
        or meta.generation < 1
        or meta.deletion_timestamp
        or subject != str(subject_id)
        or (meta.labels or {}).get("app.kubernetes.io/managed-by") != MANAGED_BY
    ):
        raise ValueError("UserBinding identity or ownership mismatch")
    if str(parse_user_id(meta.uid)) != meta.uid:
        raise ValueError("Invalid UserBinding UID")
    conditions: list[PlatformCondition] = binding.status.conditions if binding.status else []
    if len({condition.type for condition in conditions}) != len(conditions) or any(
        condition.last_transition_time.utcoffset() is None for condition in conditions
    ):
        raise ValueError("Invalid UserBinding conditions")
    return subject_id


def _check_binding(binding: UserBinding, user: CoreUser, namespace: str) -> None:
    name, subject_id = _user_identity(user)
    if _binding_identity(binding, namespace) != subject_id or binding.spec.user_ref.name != name:
        raise ValueError("UserBinding identity or ownership mismatch")


async def ensure_binding(user: CoreUser, client: AsyncAPIClient[UserBinding]) -> UserBinding:
    """Atomically create one observation; never retarget an existing binding."""
    name, subject_id = _user_identity(user)
    namespace = _namespace(client)
    desired = UserBinding(
        metadata=ObjectMeta(
            name=f"mediamtx-{subject_id.hex}",
            namespace=namespace,
            annotations={USER_UUID_ANNOTATION: str(subject_id)},
            labels={"app.kubernetes.io/managed-by": MANAGED_BY},
        ),
        spec=UserBindingSpec(user_ref=ObjectRef(name=name)),
    )
    try:
        binding = await client.create(desired)
    except ResourceConflict:
        binding = await client.get(desired.name or "", namespace=namespace)
    _check_binding(binding, user, namespace)
    return binding


async def set_binding_synced(
    binding: UserBinding,
    user: CoreUser,
    client: AsyncAPIClient[UserBinding],
    *,
    synced: bool,
    now: datetime,
) -> UserBinding:
    """Report completed provisioning, with UID/version guards; conflicts propagate."""
    _check_binding(binding, user, _namespace(client))
    return await _set_synced(binding, client, synced=synced, now=now)


async def set_binding_pending(
    binding: UserBinding, client: AsyncAPIClient[UserBinding], *, now: datetime
) -> UserBinding:
    """Clear readiness for owned bindings, including missing or replaced Users."""
    _binding_identity(binding, _namespace(client))
    return await _set_synced(binding, client, synced=False, now=now)


async def _set_synced(
    binding: UserBinding, client: AsyncAPIClient[UserBinding], *, synced: bool, now: datetime
) -> UserBinding:
    if type(synced) is not bool or now.utcoffset() is None:
        raise ValueError("Invalid provisioning observation")
    conditions: list[PlatformCondition] = binding.status.conditions if binding.status else []
    previous = next((condition for condition in conditions if condition.type == "Synced"), None)
    state = "True" if synced else "False"
    transition = previous.last_transition_time if previous and previous.status == state else now
    condition = PlatformCondition(
        type="Synced",
        status=state,
        reason="Reconciled" if synced else "ProvisioningPending",
        message="Provisioning is complete." if synced else "Provisioning is incomplete.",
        last_transition_time=transition,
        observed_generation=binding.metadata.generation if binding.metadata else None,
    )
    desired = binding.model_copy(deep=True)
    updated_conditions = [condition if item.type == "Synced" else item for item in conditions]
    if previous is None:
        updated_conditions.append(condition)
    desired.status = UserBindingStatus(
        observed_generation=condition.observed_generation,
        conditions=updated_conditions,
    )
    operations = diff(binding, desired)
    if not operations:
        return binding
    return await client.patch(binding, operations, subresource="status")
