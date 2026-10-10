"""Remove MediaMTX sessions after their grant has been denied or expired."""

import re
from uuid import UUID

import httpx

from opendefence_integration_mediamtx.policy import MEDIA_PROTOCOLS

_ROUTES = {
    "hls": "hls/sessions",
    "rtsps": "rtsps/sessions",
    "rtmps": "rtmps/conns",
    "srt": "srt/conns",
    "webrtc": "webrtc/sessions",
}
_MAX_PAGES = 1000
_MAX_SCANS = 6


async def _matching_sessions(client: httpx.AsyncClient, route: str, username: str) -> set[str]:
    matches: set[str] = set()
    page = 0
    while True:
        response = await client.get(f"/v3/{route}/list", params={"itemsPerPage": 100, "page": page})
        response.raise_for_status()
        listing = response.json()
        if not isinstance(listing, dict):
            raise ValueError("Invalid MediaMTX session list")
        items, page_count = listing.get("items"), listing.get("pageCount")
        if (
            not isinstance(items, list)
            or type(page_count) is not int
            or not 0 <= page_count <= _MAX_PAGES
            or (page_count == 0 and items)
        ):
            raise ValueError("Invalid MediaMTX session list")
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("user"), str):
                raise ValueError("Invalid MediaMTX session")
            if item["user"] == username:
                session_id = item.get("id")
                if not isinstance(session_id, str):
                    raise ValueError("Invalid MediaMTX session ID")
                try:
                    if str(UUID(session_id)) != session_id:
                        raise ValueError
                except ValueError:
                    raise ValueError("Invalid MediaMTX session ID") from None
                matches.add(session_id)
        page += 1
        if page >= page_count:
            return matches


async def drain_grant_sessions(client: httpx.AsyncClient, username: str, *, protocols: frozenset[str]) -> int:
    """Scan and kick a grant's sessions; raise unless two successive scans are empty.

    The caller must persist admission denial first and retain cleanup state until
    this returns. The client must target one authenticated MediaMTX instance.
    """
    if (
        not isinstance(username, str)
        or not re.fullmatch(r"g_[A-Za-z0-9_-]{22}", username)
        or not isinstance(protocols, frozenset)
        or not protocols
        or not protocols <= MEDIA_PROTOCOLS
    ):
        raise ValueError("Invalid grant session scope")
    if client.base_url.scheme != "https":
        raise ValueError("MediaMTX control API requires HTTPS")
    empty_scans = kicked = 0
    for _ in range(_MAX_SCANS):
        found: list[tuple[str, str]] = []
        for protocol in sorted(protocols):
            route = _ROUTES[protocol]
            found.extend((route, session_id) for session_id in await _matching_sessions(client, route, username))
        if not found:
            empty_scans += 1
            if empty_scans == 2:
                return kicked
            continue
        empty_scans = 0
        for route, session_id in found:
            response = await client.post(f"/v3/{route}/kick/{session_id}")
            if response.status_code != 404:
                response.raise_for_status()
            kicked += 1
    raise RuntimeError("MediaMTX session cleanup did not converge")
