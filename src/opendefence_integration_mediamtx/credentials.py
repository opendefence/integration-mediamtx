"""Keep one integration-issued media password for each immutable User UID."""

import base64
import re
import secrets

from cloudcoil.apimachinery import ObjectMeta
from cloudcoil.client import AsyncAPIClient
from cloudcoil.errors import ResourceConflict, ResourceNotFound
from cloudcoil.models.kubernetes.core.v1 import Secret
from lib_opendefence_core.models.v1alpha1 import User

from opendefence_integration_mediamtx.bindings import MANAGED_BY, USER_UUID_ANNOTATION, _user_identity
from opendefence_integration_mediamtx.reservations import _namespace

CONTROL_USER = "mediamtx-control"


def active_user(user: User) -> bool:
    """Approval permits a credential; any revocation marker denies it."""
    return bool(
        user.metadata
        and not user.metadata.deletion_timestamp
        and user.spec.approved_at is not None
        and user.spec.revoked_at is None
    )


def _read_password(secret: Secret, user: User, namespace: str) -> str:
    _, subject = _user_identity(user)
    meta = secret.metadata
    if (
        not meta
        or meta.name != f"mediamtx-user-{subject.hex}"
        or meta.namespace != namespace
        or not meta.uid
        or not meta.resource_version
        or meta.deletion_timestamp
        or (meta.labels or {}).get("app.kubernetes.io/managed-by") != MANAGED_BY
        or (meta.annotations or {}).get(USER_UUID_ANNOTATION) != str(subject)
    ):
        raise ValueError("Media credential identity or ownership mismatch")
    return _password(secret)


def _password(secret: Secret) -> str:
    if secret.type != "Opaque" or not secret.data or set(secret.data) != {"password"}:
        raise ValueError("Invalid media credential")
    try:
        encoded = secret.data["password"]
        if len(encoded) > 256:
            raise ValueError
        password = base64.b64decode(encoded, validate=True).decode("ascii")
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", password):
            raise ValueError
    except ValueError:
        raise ValueError("Invalid media credential") from None
    return password


async def control_password(client: AsyncAPIClient[Secret], *, create: bool = False) -> str:
    """Keep the integration's control credential separate from User credentials."""
    namespace = _namespace(client)
    try:
        stored = await client.get(CONTROL_USER, namespace=namespace)
    except ResourceNotFound:
        if not create:
            raise
        desired = Secret(
            metadata=ObjectMeta(
                name=CONTROL_USER,
                namespace=namespace,
                labels={"app.kubernetes.io/managed-by": MANAGED_BY},
            ),
            type="Opaque",
            data={"password": base64.b64encode(secrets.token_urlsafe(32).encode("ascii")).decode("ascii")},
        )
        try:
            stored = await client.create(desired)
        except ResourceConflict:
            stored = await client.get(CONTROL_USER, namespace=namespace)
    meta = stored.metadata
    if (
        not meta
        or meta.name != CONTROL_USER
        or meta.namespace != namespace
        or not meta.uid
        or not meta.resource_version
        or meta.deletion_timestamp
        or (meta.labels or {}).get("app.kubernetes.io/managed-by") != MANAGED_BY
    ):
        raise ValueError("Control credential ownership mismatch")
    return _password(stored)


async def user_password(user: User, client: AsyncAPIClient[Secret]) -> str:
    """Read a UID-pinned credential; this never issues one on an auth request."""
    _, subject = _user_identity(user)
    namespace = _namespace(client)
    stored = await client.get(f"mediamtx-user-{subject.hex}", namespace=namespace)
    return _read_password(stored, user, namespace)


async def ensure_user_password(user: User, client: AsyncAPIClient[Secret]) -> str:
    """Create once for an approved User; concurrent creators use the stored winner."""
    if not active_user(user):
        raise ValueError("An approved, unrevoked User is required")
    _, subject = _user_identity(user)
    namespace = _namespace(client)
    try:
        return await user_password(user, client)
    except ResourceNotFound:
        pass
    desired = Secret(
        metadata=ObjectMeta(
            name=f"mediamtx-user-{subject.hex}",
            namespace=namespace,
            labels={"app.kubernetes.io/managed-by": MANAGED_BY},
            annotations={USER_UUID_ANNOTATION: str(subject)},
        ),
        type="Opaque",
        data={"password": base64.b64encode(secrets.token_urlsafe(32).encode("ascii")).decode("ascii")},
    )
    try:
        stored = await client.create(desired)
    except ResourceConflict:
        return await user_password(user, client)
    return _read_password(stored, user, namespace)
