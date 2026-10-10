"""Parse the pinned MediaMTX callback without retaining query or token fields."""

import hmac
from dataclasses import dataclass
from uuid import UUID

_LIMITS = {
    "user": 256,
    "password": 4096,
    "token": 8192,
    "action": 32,
    "path": 512,
    "protocol": 32,
    "ip": 64,
    "query": 16384,
    "userAgent": 1024,
}


@dataclass(frozen=True, slots=True, repr=False)
class AuthRequest:
    user: str
    password: str
    action: str
    path: str
    protocol: str

    @classmethod
    def from_payload(cls, payload: object) -> AuthRequest:
        if not isinstance(payload, dict):
            raise ValueError("Invalid authentication payload")
        values: dict[str, str] = {}
        for name, limit in _LIMITS.items():
            value = payload.get(name, None if name == "action" else "")
            if not isinstance(value, str) or len(value) > limit:
                raise ValueError("Invalid authentication field")
            values[name] = value
        session_id = payload.get("id")
        if session_id is not None:
            if not isinstance(session_id, str) or len(session_id) != 36:
                raise ValueError("Invalid authentication session ID")
            try:
                if str(UUID(session_id)) != session_id:
                    raise ValueError
            except ValueError:
                raise ValueError("Invalid authentication session ID") from None
        if values["token"]:
            try:
                matches = hmac.compare_digest(values["password"].encode(), values["token"].encode())
            except UnicodeError:
                raise ValueError("Invalid authentication credential encoding") from None
            if not values["password"] or not matches:
                raise ValueError("Unsupported authentication credentials")
        return cls(
            user=values["user"],
            password=values["password"],
            action=values["action"],
            path=values["path"],
            protocol=values["protocol"],
        )
