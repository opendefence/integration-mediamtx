"""Pure media admission policy; inputs are semantic projections, not Core CRDs."""

import hmac
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID

from opendefence_integration_mediamtx.auth import AuthRequest
from opendefence_integration_mediamtx.paths import CALLSIGN_PATTERN, StreamPath, parse_path

_PUBLIC_PROTOCOL = {"rtsp": "rtsps", "rtmp": "rtmps", "hls": "hls", "srt": "srt", "webrtc": "webrtc"}
MEDIA_PROTOCOLS = frozenset(_PUBLIC_PROTOCOL.values())
MAX_GRANT_LIFETIME = timedelta(hours=24)


def _aware(value: datetime) -> bool:
    return isinstance(value, datetime) and value.utcoffset() is not None


@dataclass(frozen=True, slots=True, kw_only=True)
class EffectivePolicy:
    subject_id: UUID
    binding_uid: UUID
    callsign: str
    approved: bool
    assigned: bool
    revision: str
    evaluated_at: datetime
    valid_until: datetime
    approval_deadline: datetime | None
    superadmin: bool = False
    read_all: bool = False
    read_paths: frozenset[StreamPath] = frozenset()
    publish_own: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.subject_id, UUID) or not isinstance(self.binding_uid, UUID):
            raise ValueError("Invalid policy identity")
        if not isinstance(self.revision, str) or not self.revision.strip():
            raise ValueError("Missing policy revision")
        if not isinstance(self.callsign, str) or not re.fullmatch(CALLSIGN_PATTERN, self.callsign):
            raise ValueError("Invalid policy callsign")
        if any(
            type(value) is not bool
            for value in (self.approved, self.assigned, self.superadmin, self.read_all, self.publish_own)
        ):
            raise ValueError("Invalid policy permission")
        if not _aware(self.evaluated_at) or not _aware(self.valid_until) or self.valid_until <= self.evaluated_at:
            raise ValueError("Invalid policy freshness")
        if self.approval_deadline is not None and not _aware(self.approval_deadline):
            raise ValueError("Invalid approval deadline")
        if not isinstance(self.read_paths, frozenset) or any(
            not isinstance(path, StreamPath) for path in self.read_paths
        ):
            raise ValueError("Invalid policy read scope")


@dataclass(frozen=True, slots=True, kw_only=True)
class MediaGrant:
    id: str
    subject_id: UUID
    binding_uid: UUID
    stream: StreamPath
    action: str
    protocols: frozenset[str]
    password: str = field(repr=False)
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not re.fullmatch(r"g_[A-Za-z0-9_-]{22}", self.id):
            raise ValueError("Invalid grant ID")
        if not isinstance(self.subject_id, UUID) or not isinstance(self.binding_uid, UUID):
            raise ValueError("Invalid grant identity")
        if not isinstance(self.stream, StreamPath) or self.action not in ("read", "publish"):
            raise ValueError("Invalid grant scope")
        if not isinstance(self.protocols, frozenset) or not self.protocols or not self.protocols <= MEDIA_PROTOCOLS:
            raise ValueError("Invalid grant protocols")
        if self.action == "publish" and "hls" in self.protocols:
            raise ValueError("HLS publishing is unsupported")
        if not isinstance(self.password, str) or not re.fullmatch(r"[A-Za-z0-9_-]{22,128}", self.password):
            raise ValueError("Invalid grant credential")
        if not _aware(self.created_at) or not _aware(self.expires_at):
            raise ValueError("Invalid grant lifetime")
        if not timedelta() < self.expires_at - self.created_at <= MAX_GRANT_LIFETIME:
            raise ValueError("Invalid grant lifetime")
        if self.revoked_at is not None and not _aware(self.revoked_at):
            raise ValueError("Invalid grant revocation")


def grant_remains_authorized(  # noqa: PLR0911 - Keep each grant requirement explicit for reconciliation.
    grant: MediaGrant | None, policy: EffectivePolicy | None, *, now: datetime
) -> bool:
    """Check a stored grant against current policy before retaining its sessions."""
    if not isinstance(grant, MediaGrant) or not isinstance(policy, EffectivePolicy) or not _aware(now):
        return False
    if grant.revoked_at is not None or not grant.created_at <= now < grant.expires_at:
        return False
    if grant.subject_id != policy.subject_id or grant.binding_uid != policy.binding_uid:
        return False
    if (
        not policy.approved
        or not (policy.assigned or policy.superadmin)
        or not policy.evaluated_at <= now < policy.valid_until
    ):
        return False
    if policy.approval_deadline is not None and now >= policy.approval_deadline:
        return False
    if grant.action == "read":
        return policy.superadmin or policy.read_all or grant.stream in policy.read_paths
    return policy.superadmin or (policy.publish_own and grant.stream.owner_callsign == policy.callsign)


def authorize_media(
    payload: object,
    grant: MediaGrant | None,
    policy: EffectivePolicy | None,
    *,
    now: datetime,
    enabled_protocols: frozenset[str],
) -> bool:
    """Decide new admission; the caller must attest strict TLS for enabled RTSPS/RTMPS."""
    if not isinstance(grant, MediaGrant) or not isinstance(policy, EffectivePolicy) or not _aware(now):
        return False
    if not isinstance(enabled_protocols, frozenset) or not enabled_protocols <= MEDIA_PROTOCOLS:
        return False
    try:
        request = AuthRequest.from_payload(payload)
        stream = parse_path(request.path)
        password_matches = hmac.compare_digest(request.password.encode(), grant.password.encode())
    except ValueError:
        return False
    if request.user != grant.id or not password_matches or request.action != grant.action or stream != grant.stream:
        return False
    protocol = _PUBLIC_PROTOCOL.get(request.protocol)
    if protocol not in grant.protocols or protocol not in enabled_protocols:
        return False
    return grant_remains_authorized(grant, policy, now=now)
