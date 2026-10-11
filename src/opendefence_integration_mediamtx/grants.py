"""Store one media grant in a namespace-scoped Kubernetes Secret."""

import base64
import binascii
import hashlib
import re
from collections.abc import Iterable
from datetime import datetime
from uuid import UUID

import httpx
from cloudcoil.apimachinery import ObjectMeta
from cloudcoil.client import AsyncAPIClient
from cloudcoil.errors import ResourceConflict, ResourceNotFound
from cloudcoil.models.kubernetes.core.v1 import Secret
from cloudcoil.patches import diff
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, model_validator

from opendefence_integration_mediamtx.bindings import MANAGED_BY
from opendefence_integration_mediamtx.paths import parse_path
from opendefence_integration_mediamtx.policy import MediaGrant
from opendefence_integration_mediamtx.reservations import (
    RETRY_WINDOW,
    Reservation,
    _namespace,
    _remove_retained_reservation,
    list_reservations_for_subject,
    mark_cleanup_complete,
)
from opendefence_integration_mediamtx.sessions import drain_grant_sessions

_DATA_KEY = "grant.json"
_SUBJECT_LABEL = "mediamtx.opendefence.fi/subject-uid"
_RETRIES = 16


class GrantRecord(BaseModel):
    """Validated Secret payload; its password is intentionally absent from repr."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: int = 1
    id: str
    subject_id: UUID
    binding_uid: UUID
    stream: str
    action: str
    protocols: frozenset[str]
    password: str = Field(repr=False)
    created_at: AwareDatetime
    expires_at: AwareDatetime
    revoked_at: AwareDatetime | None = None
    key_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def valid_grant(self) -> GrantRecord:
        if self.schema_version != 1:
            raise ValueError("Unsupported grant schema")
        self.media_grant()
        return self

    def media_grant(self) -> MediaGrant:
        return MediaGrant(
            id=self.id,
            subject_id=self.subject_id,
            binding_uid=self.binding_uid,
            stream=parse_path(self.stream),
            action=self.action,
            protocols=self.protocols,
            password=self.password,
            created_at=self.created_at,
            expires_at=self.expires_at,
            revoked_at=self.revoked_at,
        )


def _name(grant_id: str) -> str:
    if not isinstance(grant_id, str) or not re.fullmatch(r"g_[A-Za-z0-9_-]{22}", grant_id):
        raise ValueError("Invalid grant ID")
    return "mediamtx-grant-" + hashlib.sha256(grant_id.encode("ascii")).hexdigest()


def _read(secret: Secret, namespace: str, grant_id: str | None = None) -> GrantRecord:
    metadata = secret.metadata
    if (
        not metadata
        or (grant_id is not None and metadata.name != _name(grant_id))
        or metadata.namespace != namespace
        or not metadata.uid
        or not metadata.resource_version
        or metadata.deletion_timestamp
        or (metadata.labels or {}).get("app.kubernetes.io/managed-by") != MANAGED_BY
        or secret.type != "Opaque"
        or not secret.data
        or set(secret.data) != {_DATA_KEY}
    ):
        raise ValueError("Grant Secret ownership mismatch")
    try:
        encoded = secret.data[_DATA_KEY]
        if len(encoded) > 8192:
            raise ValueError
        record = GrantRecord.model_validate_json(base64.b64decode(encoded, validate=True))
    except ValueError, ValidationError, binascii.Error:
        raise ValueError("Invalid grant Secret") from None
    if (
        metadata.name != _name(record.id)
        or (grant_id is not None and record.id != grant_id)
        or (metadata.labels or {}).get(_SUBJECT_LABEL) != str(record.subject_id)
    ):
        raise ValueError("Grant Secret identity mismatch")
    return record


async def load_grant(client: AsyncAPIClient[Secret], grant_id: str) -> GrantRecord:
    """Read a stored grant after checking Secret ownership and its full payload."""
    namespace = _namespace(client)
    secret = await client.get(_name(grant_id), namespace=namespace)
    return _read(secret, namespace, grant_id)


async def list_grants_for_subject(client: AsyncAPIClient[Secret], subject_id: UUID) -> list[GrantRecord]:
    """List every stored grant for one User, including revoked grants."""
    namespace = _namespace(client, subject_id)
    selector = f"app.kubernetes.io/managed-by={MANAGED_BY},{_SUBJECT_LABEL}={subject_id}"
    records: list[GrantRecord] = []
    async for secret in await client.list(namespace=namespace, label_selector=selector):
        record = _read(secret, namespace)
        if record.subject_id != subject_id:
            raise ValueError("Grant subject mismatch")
        records.append(record)
    return records


async def create_grant_record(
    client: AsyncAPIClient[Secret], reservation: Reservation, grant: MediaGrant, *, now: datetime
) -> GrantRecord:
    """Create once; a retry returns only the stored winning credential."""
    if (
        not isinstance(reservation, Reservation)
        or not isinstance(grant, MediaGrant)
        or not isinstance(now, datetime)
        or now.utcoffset() is None
        or reservation.grant_id != grant.id
        or reservation.created_at != grant.created_at
        or reservation.expires_at != grant.expires_at
        or reservation.cleanup_complete
        or grant.revoked_at is not None
        or not grant.created_at <= now < grant.expires_at
    ):
        raise ValueError("Grant does not match an active reservation")
    namespace = _namespace(client, grant.subject_id)
    record = GrantRecord(
        id=grant.id,
        subject_id=grant.subject_id,
        binding_uid=grant.binding_uid,
        stream=str(grant.stream),
        action=grant.action,
        protocols=grant.protocols,
        password=grant.password,
        created_at=grant.created_at,
        expires_at=grant.expires_at,
        key_digest=reservation.key_digest,
        request_digest=reservation.request_digest,
    )
    desired = Secret(
        metadata=ObjectMeta(
            name=_name(grant.id),
            namespace=namespace,
            labels={"app.kubernetes.io/managed-by": MANAGED_BY, _SUBJECT_LABEL: str(grant.subject_id)},
        ),
        type="Opaque",
        data={_DATA_KEY: base64.b64encode(record.model_dump_json().encode()).decode("ascii")},
    )
    try:
        stored = _read(await client.create(desired), namespace, grant.id)
    except ResourceConflict:
        stored = await load_grant(client, grant.id)
    if (
        stored.subject_id != grant.subject_id
        or stored.binding_uid != grant.binding_uid
        or stored.stream != str(grant.stream)
        or stored.action != grant.action
        or stored.protocols != grant.protocols
        or stored.created_at != grant.created_at
        or stored.expires_at != grant.expires_at
        or stored.key_digest != reservation.key_digest
        or stored.request_digest != reservation.request_digest
        or stored.revoked_at is not None
        or stored.expires_at <= now
    ):
        raise ValueError("Stored grant does not match the reservation")
    return stored


async def revoke_grant(
    client: AsyncAPIClient[Secret], subject_id: UUID, grant_id: str, *, now: datetime
) -> GrantRecord:
    """Persist denial before the caller drains sessions."""
    namespace = _namespace(client, subject_id)
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise ValueError("Invalid revocation time")
    for _ in range(_RETRIES):
        secret = await client.get(_name(grant_id), namespace=namespace)
        stored = _read(secret, namespace, grant_id)
        if stored.subject_id != subject_id:
            raise ValueError("Grant subject mismatch")
        if stored.revoked_at is not None:
            return stored
        updated = stored.model_copy(update={"revoked_at": now})
        desired = secret.model_copy(deep=True)
        desired.data = {_DATA_KEY: base64.b64encode(updated.model_dump_json().encode()).decode("ascii")}
        try:
            return _read(await client.patch(secret, diff(secret, desired)), namespace, grant_id)
        except ResourceConflict:
            continue
    raise RuntimeError("Grant revocation did not converge")


async def retire_grant(
    client: AsyncAPIClient[Secret],
    subject_id: UUID,
    grant_id: str,
    media_clients: Iterable[httpx.AsyncClient],
    *,
    now: datetime,
) -> GrantRecord:
    """Persist denial and drain; caller must supply every active MediaMTX instance."""
    instances = tuple(media_clients)
    if not instances:
        raise ValueError("At least one MediaMTX instance is required")
    record = await revoke_grant(client, subject_id, grant_id, now=now)
    for media in instances:
        await drain_grant_sessions(media, record.id, protocols=record.protocols)
    await mark_cleanup_complete(client, subject_id, record.key_digest, record.id)
    return record


async def prune_retired_grants(client: AsyncAPIClient[Secret], subject_id: UUID, *, now: datetime) -> int:
    """Remove retained records after expiry and the retry window, with guarded writes."""
    namespace = _namespace(client, subject_id)
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise ValueError("Invalid cleanup time")
    removed = 0
    for reservation in await list_reservations_for_subject(client, subject_id):
        if (
            not reservation.cleanup_complete
            or now < reservation.expires_at
            or now < reservation.created_at + RETRY_WINDOW
        ):
            continue
        name = _name(reservation.grant_id)
        try:
            secret = await client.get(name, namespace=namespace)
        except ResourceNotFound:
            pass  # A previous attempt may have deleted the grant before it stopped.
        else:
            record = _read(secret, namespace, reservation.grant_id)
            if (
                record.subject_id != subject_id
                or record.key_digest != reservation.key_digest
                or record.request_digest != reservation.request_digest
                or record.created_at != reservation.created_at
                or record.expires_at != reservation.expires_at
                or record.revoked_at is None
            ):
                raise ValueError("Grant does not match the completed reservation")
            assert secret.metadata
            try:
                await client.delete(
                    name,
                    namespace=namespace,
                    uid=secret.metadata.uid,
                    resource_version=secret.metadata.resource_version,
                )
            except ResourceNotFound:
                pass
            try:
                await client.get(name, namespace=namespace)
            except ResourceNotFound:
                pass
            else:
                raise RuntimeError("Grant Secret deletion did not complete")
        removed += await _remove_retained_reservation(
            client, subject_id, reservation.key_digest, reservation.grant_id, now=now
        )
    return removed
