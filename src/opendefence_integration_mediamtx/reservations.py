"""Persist bounded grant reservations without issuing media credentials."""

import base64
import binascii
import hashlib
import re
import secrets
from datetime import datetime, timedelta
from uuid import UUID

from cloudcoil.apimachinery import ObjectMeta
from cloudcoil.client import AsyncAPIClient
from cloudcoil.errors import ResourceConflict, ResourceNotFound
from cloudcoil.models.kubernetes.core.v1 import Secret
from cloudcoil.patches import diff
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, model_validator

from opendefence_integration_mediamtx.bindings import MANAGED_BY

MAX_ACTIVE = 8
MAX_RETAINED = 64
MAX_LIFETIME = timedelta(hours=24)
_RETRIES = 16
_DATA_KEY = "reservations.json"


class Reservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    grant_id: str = Field(pattern=r"^g_[A-Za-z0-9_-]{22}$")
    key_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: AwareDatetime
    expires_at: AwareDatetime
    cleanup_complete: bool = False

    @model_validator(mode="after")
    def valid_lifetime(self) -> Reservation:
        if not timedelta() < self.expires_at - self.created_at <= MAX_LIFETIME:
            raise ValueError("Invalid reservation lifetime")
        return self


class _Ledger(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: int = 1
    subject_id: str
    entries: dict[str, Reservation]

    @model_validator(mode="after")
    def valid_entries(self) -> _Ledger:
        if (
            self.schema_version != 1
            or len(self.entries) > MAX_RETAINED
            or any(key != item.key_digest for key, item in self.entries.items())
        ):
            raise ValueError("Invalid reservation ledger")
        return self


def _namespace(client: AsyncAPIClient[Secret], subject_id: UUID | None = None) -> str:
    if (
        client.kind is not Secret
        or not client.namespaced
        or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", client.default_namespace)
        or (subject_id is not None and not isinstance(subject_id, UUID))
    ):
        raise ValueError("Invalid reservation scope")
    return client.default_namespace


def _key_digest(subject_id: UUID, key: str, request_digest: str, now: datetime) -> str:
    if (
        not isinstance(key, str)
        or not re.fullmatch(r"[!-~]{1,256}", key)
        or not isinstance(request_digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", request_digest)
        or not isinstance(now, datetime)
        or now.utcoffset() is None
    ):
        raise ValueError("Invalid reservation scope")
    key_bytes = key.encode("ascii")
    return hashlib.sha256(subject_id.bytes + len(key_bytes).to_bytes(2, "big") + key_bytes).hexdigest()


def _encode(ledger: _Ledger) -> str:
    return base64.b64encode(ledger.model_dump_json().encode()).decode("ascii")


def _read(secret: Secret, subject_id: UUID, namespace: str) -> _Ledger:
    meta = secret.metadata
    if (
        not meta
        or meta.name != f"mediamtx-reservations-{subject_id.hex}"
        or meta.namespace != namespace
        or not meta.uid
        or not meta.resource_version
        or meta.deletion_timestamp
        or (meta.labels or {}).get("app.kubernetes.io/managed-by") != MANAGED_BY
        or secret.type != "Opaque"
        or not secret.data
        or set(secret.data) != {_DATA_KEY}
    ):
        raise ValueError("Reservation Secret ownership mismatch")
    try:
        encoded = secret.data[_DATA_KEY]
        if len(encoded) > 65536:
            raise ValueError
        ledger = _Ledger.model_validate_json(base64.b64decode(encoded, validate=True))
    except ValueError, ValidationError, binascii.Error:
        raise ValueError("Invalid reservation ledger") from None
    if ledger.subject_id != str(subject_id):
        raise ValueError("Reservation Secret subject mismatch")
    return ledger


async def reserve_grant(  # noqa: PLR0913 - Each value is part of the reservation identity or lifetime.
    client: AsyncAPIClient[Secret],
    subject_id: UUID,
    idempotency_key: str,
    request_digest: str,
    *,
    now: datetime,
    expires_at: datetime,
) -> Reservation:
    """Reserve one grant ID with atomic create and version-guarded updates."""
    namespace = _namespace(client, subject_id)
    key_digest = _key_digest(subject_id, idempotency_key, request_digest, now)
    if (
        not isinstance(expires_at, datetime)
        or expires_at.utcoffset() is None
        or not now < expires_at <= now + MAX_LIFETIME
    ):
        raise ValueError("Invalid reservation expiry")
    name = f"mediamtx-reservations-{subject_id.hex}"
    for _ in range(_RETRIES):
        try:
            secret = await client.get(name, namespace=namespace)
        except ResourceNotFound:
            reservation = Reservation(
                grant_id="g_" + secrets.token_urlsafe(16),
                key_digest=key_digest,
                request_digest=request_digest,
                created_at=now,
                expires_at=expires_at,
            )
            ledger = _Ledger(subject_id=str(subject_id), entries={key_digest: reservation})
            desired = Secret(
                metadata=ObjectMeta(
                    name=name,
                    namespace=namespace,
                    labels={"app.kubernetes.io/managed-by": MANAGED_BY},
                ),
                type="Opaque",
                data={_DATA_KEY: _encode(ledger)},
            )
            try:
                await client.create(desired)
                return reservation
            except ResourceConflict:
                continue
        ledger = _read(secret, subject_id, namespace)
        existing = ledger.entries.get(key_digest)
        if existing:
            if existing.request_digest != request_digest:
                raise ValueError("Idempotency key has a different request")
            if existing.cleanup_complete or existing.expires_at <= now:
                raise ValueError("Reservation is no longer active")
            return existing
        if (
            len(ledger.entries) >= MAX_RETAINED
            or sum(not item.cleanup_complete for item in ledger.entries.values()) >= MAX_ACTIVE
        ):
            raise ValueError("Grant reservation limit reached")
        reservation = Reservation(
            grant_id="g_" + secrets.token_urlsafe(16),
            key_digest=key_digest,
            request_digest=request_digest,
            created_at=now,
            expires_at=expires_at,
        )
        updated = ledger.model_copy(update={"entries": {**ledger.entries, key_digest: reservation}})
        desired = secret.model_copy(deep=True)
        desired.data = {_DATA_KEY: _encode(updated)}
        try:
            await client.patch(secret, diff(secret, desired))
            return reservation
        except ResourceConflict:
            continue
    raise RuntimeError("Grant reservation update did not converge")


async def mark_cleanup_complete(
    client: AsyncAPIClient[Secret],
    subject_id: UUID,
    key_digest: str,
    grant_id: str,
) -> Reservation:
    """Release active capacity after the caller has persisted denial and drained sessions."""
    namespace = _namespace(client, subject_id)
    if (
        not isinstance(key_digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", key_digest)
        or not isinstance(grant_id, str)
        or not re.fullmatch(r"g_[A-Za-z0-9_-]{22}", grant_id)
    ):
        raise ValueError("Invalid grant reservation identity")
    name = f"mediamtx-reservations-{subject_id.hex}"
    for _ in range(_RETRIES):
        secret = await client.get(name, namespace=namespace)
        ledger = _read(secret, subject_id, namespace)
        existing = ledger.entries.get(key_digest)
        if not existing or existing.grant_id != grant_id:
            raise ValueError("Grant reservation mismatch")
        if existing.cleanup_complete:
            return existing
        complete = existing.model_copy(update={"cleanup_complete": True})
        updated = ledger.model_copy(update={"entries": {**ledger.entries, key_digest: complete}})
        desired = secret.model_copy(deep=True)
        desired.data = {_DATA_KEY: _encode(updated)}
        try:
            await client.patch(secret, diff(secret, desired))
            return complete
        except ResourceConflict:
            continue
    raise RuntimeError("Grant reservation cleanup did not converge")
