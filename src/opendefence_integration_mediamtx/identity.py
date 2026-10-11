"""Read Core-injected identity at the integration's private HTTP boundary."""

import re
from collections.abc import Iterable
from uuid import UUID

from opendefence_integration_mediamtx.paths import parse_user_id

DEFAULT_USER_UUID_HEADER = "X-OpenDefence-User-UUID"


def user_id_from_headers(headers: Iterable[tuple[str, str]], *, header_name: str = DEFAULT_USER_UUID_HEADER) -> UUID:
    """Require one injected UUID; callers must preserve duplicate HTTP headers."""
    if not isinstance(header_name, str) or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", header_name):
        raise ValueError("Invalid identity header configuration")
    values = [value for name, value in headers if name.lower() == header_name.lower()]
    if len(values) != 1:
        raise ValueError("Missing or ambiguous Core identity")
    try:
        return parse_user_id(values[0])
    except ValueError:
        raise ValueError("Invalid Core identity") from None
