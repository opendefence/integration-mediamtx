"""Exercise callback admission through current policy and exact grant scope."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import pytest

from odintegration_mediamtx.auth import AuthRequest
from odintegration_mediamtx.paths import StreamPath
from odintegration_mediamtx.policy import EffectivePolicy, MediaGrant, authorize_media

NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)
OWNER = UUID(int=1)
BINDING = UUID(int=10)
OTHER_OWNER = UUID(int=2)
STREAM = StreamPath(tool="ipcam", owner_id=OWNER)
OTHER_STREAM = StreamPath(tool="ipcam", owner_id=OTHER_OWNER)
PASSWORD = "fixture_password_not_for_release_1234"
GRANT = MediaGrant(
    id="g_" + "A" * 22,
    subject_id=OWNER,
    binding_uid=BINDING,
    stream=STREAM,
    action="read",
    protocols=frozenset({"hls"}),
    password=PASSWORD,
    created_at=NOW,
    expires_at=NOW + timedelta(hours=1),
)
POLICY = EffectivePolicy(
    subject_id=OWNER,
    binding_uid=BINDING,
    approved=True,
    assigned=True,
    revision="policy-1",
    evaluated_at=NOW,
    valid_until=NOW + timedelta(seconds=15),
    approval_deadline=NOW + timedelta(hours=2),
    read_all=True,
    publish_own=True,
)
PAYLOAD = {
    "user": GRANT.id,
    "password": PASSWORD,
    "token": PASSWORD,
    "action": "read",
    "path": str(STREAM),
    "protocol": "hls",
    "id": None,
}
ENABLED = frozenset({"rtsps", "rtmps", "hls", "srt", "webrtc"})


def allowed(  # noqa: PLR0913 - Tests vary request, grant, policy, time and deployment independently.
    payload: object = PAYLOAD,
    grant: MediaGrant | None = GRANT,
    policy: EffectivePolicy | None = POLICY,
    *,
    now: datetime = NOW,
    protocols: frozenset[str] = ENABLED,
) -> bool:
    return authorize_media(payload, grant, policy, now=now, enabled_protocols=protocols)


def test_scoped_read_admission() -> None:
    assert allowed()
    assert allowed(PAYLOAD | {"token": "", "futureField": {"ignored": True}})
    assert allowed(PAYLOAD | {"id": str(UUID(int=3)), "query": "password=do-not-retain"})
    assert allowed(policy=replace(POLICY, read_all=False, read_paths=frozenset({STREAM})))
    assert allowed(policy=replace(POLICY, approval_deadline=None))


@pytest.mark.parametrize("action", ["publish", "api", "metrics", "pprof", "playback", "unknown"])
def test_read_credential_never_inherits_broader_owner_permissions(action: str) -> None:
    # Even an approved principal with all supported permissions cannot widen this grant.
    assert not allowed(PAYLOAD | {"action": action})


@pytest.mark.parametrize("path", [str(OTHER_STREAM), str(STREAM) + "2", str(STREAM) + "/channel"])
def test_read_scope_does_not_use_owner_prefixes(path: str) -> None:
    assert not allowed(PAYLOAD | {"path": path})


def test_publish_requires_both_grant_scope_and_own_stream_permission() -> None:
    grant = replace(GRANT, action="publish", protocols=frozenset({"rtsps"}))
    request = PAYLOAD | {"action": "publish", "protocol": "rtsp"}
    assert allowed(request, grant)
    assert not allowed(request, grant, replace(POLICY, publish_own=False))
    assert not allowed(request | {"path": str(OTHER_STREAM)}, grant)
    assert not allowed(request | {"path": str(OTHER_STREAM)}, replace(grant, stream=OTHER_STREAM))


@pytest.mark.parametrize(
    "upstream,public", [("rtsp", "rtsps"), ("rtmp", "rtmps"), ("srt", "srt"), ("webrtc", "webrtc")]
)
def test_protocol_mapping_requires_explicit_deployment_enablement(upstream: str, public: str) -> None:
    grant = replace(GRANT, protocols=frozenset({public}))
    assert allowed(PAYLOAD | {"protocol": upstream}, grant, protocols=frozenset({public}))
    assert not allowed(PAYLOAD | {"protocol": upstream}, grant, protocols=frozenset())
    assert not allowed(PAYLOAD | {"protocol": upstream})


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        "{}",
        {},
        PAYLOAD | {"user": ""},
        PAYLOAD | {"user": "g_" + "B" * 22},
        PAYLOAD | {"password": "", "token": ""},
        PAYLOAD | {"password": "", "token": PASSWORD},
        PAYLOAD | {"password": "wrong", "token": "wrong"},
        PAYLOAD | {"token": "conflicting-token"},
        PAYLOAD | {"password": "\ud800", "token": ""},
        PAYLOAD | {"password": "é", "token": "é"},
        PAYLOAD | {"password": None},
        PAYLOAD | {"token": None},
        PAYLOAD | {"action": None},
        PAYLOAD | {"path": []},
        PAYLOAD | {"protocol": "rtsps"},
        PAYLOAD | {"protocol": "moq"},
        PAYLOAD | {"protocol": "unknown"},
        PAYLOAD | {"id": "not-a-session-id"},
        PAYLOAD | {"id": 1},
        PAYLOAD | {"query": "A" * 16385},
        PAYLOAD | {"userAgent": {}},
    ],
)
def test_unknown_or_malformed_credentials_and_requests_fail_closed(payload: object) -> None:
    assert not allowed(payload)


@pytest.mark.parametrize(
    "policy",
    [
        None,
        replace(POLICY, approved=False),
        replace(POLICY, assigned=False),
        replace(POLICY, subject_id=OTHER_OWNER),
        replace(POLICY, binding_uid=UUID(int=11)),
        replace(POLICY, evaluated_at=NOW + timedelta(seconds=1)),
        replace(POLICY, evaluated_at=NOW - timedelta(seconds=1), valid_until=NOW),
        replace(POLICY, approval_deadline=NOW),
        replace(POLICY, read_all=False),
    ],
)
def test_missing_stale_unapproved_or_unassigned_policy_denies(policy: EffectivePolicy | None) -> None:
    assert not allowed(policy=policy)


def test_group_policy_change_does_not_need_a_user_identity_change() -> None:
    assert allowed()
    changed = replace(POLICY, revision="policy-2", read_all=False)
    assert changed.subject_id == POLICY.subject_id
    assert not allowed(policy=changed)


def test_each_time_boundary_is_exclusive() -> None:
    assert allowed(now=POLICY.valid_until - timedelta(microseconds=1))
    assert not allowed(now=POLICY.valid_until)
    fresh = replace(POLICY, valid_until=NOW + timedelta(hours=2))
    assert allowed(now=GRANT.expires_at - timedelta(microseconds=1), policy=fresh)
    assert not allowed(now=GRANT.expires_at, policy=fresh)
    earlier_deadline = replace(POLICY, approval_deadline=NOW + timedelta(seconds=5))
    assert allowed(now=NOW + timedelta(seconds=4), policy=earlier_deadline)
    assert not allowed(now=earlier_deadline.approval_deadline or NOW, policy=earlier_deadline)
    assert not allowed(grant=replace(GRANT, created_at=NOW + timedelta(seconds=1)))
    assert not allowed(now=NOW.replace(tzinfo=None))
    assert allowed(now=NOW.astimezone(timezone(timedelta(hours=3))))


def test_missing_or_revoked_grant_always_denies() -> None:
    assert not allowed(grant=None)
    assert not allowed(grant=replace(GRANT, revoked_at=NOW))
    assert not allowed(grant=replace(GRANT, revoked_at=NOW + timedelta(days=1)))


def test_credentials_and_unused_callback_fields_are_not_in_model_reprs() -> None:
    request = AuthRequest.from_payload(PAYLOAD | {"query": "sensitive-query", "userAgent": "untrusted-agent"})
    assert PASSWORD not in repr(request)
    assert PASSWORD not in repr(GRANT)
    assert "sensitive-query" not in repr(request)
    assert "untrusted-agent" not in repr(request)
    assert PASSWORD not in repr(AuthRequest.from_payload(PAYLOAD | {"user": PASSWORD, "path": PASSWORD}))


@pytest.mark.parametrize(
    "change",
    [
        {"revision": ""},
        {"valid_until": NOW},
        {"approval_deadline": NOW.replace(tzinfo=None)},
        {"evaluated_at": NOW.replace(tzinfo=None)},
        {"approved": "false"},
        {"read_paths": frozenset({"live/ipcam/ALPHA"})},
    ],
)
def test_invalid_core_projection_cannot_be_constructed(change: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        replace(POLICY, **change)


@pytest.mark.parametrize(
    "change",
    [
        {"action": "api"},
        {"action": "playback"},
        {"action": "publish"},
        {"protocols": frozenset()},
        {"protocols": frozenset({"moq"})},
        {"password": "short"},
        {"password": "é" * 32},
        {"expires_at": NOW},
        {"expires_at": NOW + timedelta(hours=24, microseconds=1)},
        {"created_at": NOW.replace(tzinfo=None)},
        {"revoked_at": NOW.replace(tzinfo=None)},
    ],
)
def test_invalid_grant_record_cannot_be_constructed(change: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        replace(GRANT, **change)
