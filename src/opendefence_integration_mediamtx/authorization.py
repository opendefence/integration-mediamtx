"""Authorize MediaMTX usernames against current User state and stored passwords."""

import hmac
import re

from cloudcoil.client import AsyncAPIClient
from cloudcoil.errors import ResourceNotFound
from cloudcoil.models.kubernetes.core.v1 import Secret
from lib_opendefence_core.models.v1alpha1 import User

from opendefence_integration_mediamtx.auth import AuthRequest
from opendefence_integration_mediamtx.credentials import active_user, user_password
from opendefence_integration_mediamtx.paths import CALLSIGN_PATTERN, parse_path

_PROTOCOLS = frozenset({"rtsp", "rtmp", "hls", "webrtc", "srt", "moq"})
_CONTROL_ACTIONS = frozenset({"api", "metrics", "pprof"})


def _valid_scope(request: AuthRequest) -> bool:
    if request.action in _CONTROL_ACTIONS:
        return not request.protocol and not request.path
    if request.action == "playback":
        return not request.protocol and bool(request.path)
    return request.action in {"read", "publish"} and request.protocol in _PROTOCOLS and bool(request.path)


async def authorize_user(payload: object, users: AsyncAPIClient[User], passwords: AsyncAPIClient[Secret]) -> bool:
    """Use an uncached User client; API failures propagate and must deny admission."""
    if users.kind is not User or users.namespaced:
        raise ValueError("A cluster-scoped User client is required")
    try:
        request = AuthRequest.from_payload(payload)
        if not re.fullmatch(CALLSIGN_PATTERN, request.user) or not request.password or not _valid_scope(request):
            return False
        user = await users.get(request.user)
        if user.name != request.user or user.spec.callsign != request.user or not active_user(user):
            return False
        password = await user_password(user, passwords)
        if not hmac.compare_digest(request.password.encode("utf-8"), password.encode("ascii")):
            return False
        return bool(
            (user.status and any(role.name == "superadmin" for role in user.status.roles))
            or request.action in {"read", "playback"}
            or (request.action == "publish" and parse_path(request.path).owner_callsign == user.spec.callsign)
        )
    except ResourceNotFound, ValueError:
        return False
