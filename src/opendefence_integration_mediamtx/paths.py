"""Canonical Core UUIDs and callsign-based media paths."""

import base64
import binascii
import re
from dataclasses import dataclass
from uuid import UUID

TOOLS = frozenset({"icu", "gopro", "uas", "ipcam"})
CALLSIGN_PATTERN = r"[a-z0-9]{3,30}"
MAX_PATH_LENGTH = 192
MAX_STREAM_ID_LENGTH = 259


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("Invalid Base64URL identifier")
    try:
        decoded = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except binascii.Error:
        raise ValueError("Invalid Base64URL identifier") from None
    if _encode(decoded) != value:
        raise ValueError("Noncanonical Base64URL identifier")
    return decoded


def encode_user_id(user_id: UUID) -> str:
    return _encode(user_id.bytes)


def parse_user_id(value: str) -> UUID:
    if not isinstance(value, str) or len(value) not in (22, 36):
        raise ValueError("Invalid Core User ID")
    if len(value) == 22:
        return UUID(bytes=_decode(value))
    try:
        user_id = UUID(value)
    except ValueError:
        raise ValueError("Invalid Core User ID") from None
    if str(user_id) != value:
        raise ValueError("Noncanonical Core User ID")
    return user_id


@dataclass(frozen=True, slots=True)
class StreamPath:
    tool: str
    owner_callsign: str

    def __post_init__(self) -> None:
        if (
            self.tool not in TOOLS
            or not isinstance(self.owner_callsign, str)
            or not re.fullmatch(CALLSIGN_PATTERN, self.owner_callsign)
        ):
            raise ValueError("Invalid stream owner or tool")

    def __str__(self) -> str:
        return f"live/{self.tool}/{self.owner_callsign}"

    @property
    def stream_id(self) -> str:
        return "s1_" + _encode(str(self).encode("ascii"))


def parse_path(value: str) -> StreamPath:
    if not isinstance(value, str) or len(value) > MAX_PATH_LENGTH:
        raise ValueError("Invalid media path")
    parts = value.split("/")
    if len(parts) != 3 or parts[0] != "live":
        raise ValueError("Invalid media path")
    path = StreamPath(tool=parts[1], owner_callsign=parts[2])
    if str(path) != value:
        raise ValueError("Noncanonical media path")
    return path


def parse_stream_id(value: str) -> StreamPath:
    if not isinstance(value, str) or len(value) > MAX_STREAM_ID_LENGTH or not value.startswith("s1_"):
        raise ValueError("Invalid stream ID")
    try:
        path = _decode(value[3:]).decode("ascii")
    except UnicodeDecodeError:
        raise ValueError("Invalid stream ID") from None
    return parse_path(path)
