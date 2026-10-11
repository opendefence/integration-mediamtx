"""Publish credential-free stream metadata to TAK's video collection API."""

import re
from typing import Any

import httpx

from opendefence_integration_mediamtx.paths import StreamPath, parse_stream_id

_VIDEO = "/Marti/api/video"


def _prefix(namespace: str) -> str:
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", namespace):
        raise ValueError("Invalid TAK catalogue namespace")
    return f"mediamtx:{namespace}:"


def video_collection(path: StreamPath, *, namespace: str, media_url: str) -> dict[str, Any]:
    """Use installation-scoped stable identifiers; never distribute media passwords."""
    uid = _prefix(namespace) + path.stream_id
    base = httpx.URL(media_url)
    if (
        base.scheme != "rtsps"
        or not base.host
        or base.userinfo
        or base.path not in {"", "/"}
        or base.query
        or base.fragment
    ):
        raise ValueError("A credential-free RTSPS origin is required")
    alias = f"{path.owner_callsign} ({path.tool})"
    return {
        "uuid": uid,
        "active": True,
        "alias": alias,
        "feeds": [
            {
                "uuid": uid,
                "active": True,
                "alias": alias,
                "url": str(base.copy_with(path=f"/{path}")),
                "order": 0,
                "rtspReliable": "1",
            }
        ],
    }


def _matches(actual: object, desired: dict[str, Any]) -> bool:
    """TAK readback includes extra null fields; compare all fields that we own."""
    if not isinstance(actual, dict) or any(actual.get(key) != desired[key] for key in ("uuid", "active", "alias")):
        return False
    feeds = actual.get("feeds")
    return bool(
        isinstance(feeds, list)
        and len(feeds) == 1
        and isinstance(feeds[0], dict)
        and all(feeds[0].get(key) == value for key, value in desired["feeds"][0].items())
    )


async def sync_feeds(client: httpx.AsyncClient, paths: set[StreamPath], *, namespace: str, media_url: str) -> None:
    """Reconcile only this installation's feed IDs and verify every remote write.

    shortcut: one writer per namespace; add a cluster identifier before sharing
    one TAK catalogue across clusters with identical integration namespaces.
    """
    if client.base_url.scheme != "https":
        raise ValueError("TAK requires HTTPS")
    prefix = _prefix(namespace)
    desired = {
        item["uuid"]: item
        for path in sorted(paths, key=str)
        for item in [video_collection(path, namespace=namespace, media_url=media_url)]
    }
    response = await client.get(_VIDEO, headers={"Accept": "application/json"})
    response.raise_for_status()
    listing = response.json()
    if not isinstance(listing, dict) or not isinstance(listing.get("videoConnections"), list):
        raise ValueError("Invalid TAK video collection list")
    owned: dict[str, dict[str, Any]] = {}
    for item in listing["videoConnections"]:
        if not isinstance(item, dict) or not isinstance(item.get("uuid"), str):
            raise ValueError("Invalid TAK video collection")
        uid = item["uuid"]
        if not uid.startswith(prefix):
            continue
        parse_stream_id(uid.removeprefix(prefix))
        if uid in owned:
            raise ValueError("Duplicate TAK video collection")
        owned[uid] = item
    # Remove stopped streams first, so failed additions cannot delay stale-feed cleanup.
    for uid in sorted(owned.keys() - desired.keys()):
        response = await client.delete(f"{_VIDEO}/{uid}")
        if response.status_code != 404:
            response.raise_for_status()
        check = await client.get(f"{_VIDEO}/{uid}", headers={"Accept": "application/json"})
        if check.status_code != 404:
            check.raise_for_status()
            raise RuntimeError("TAK video deletion is unverified")
    for uid, item in desired.items():
        if _matches(owned.get(uid), item):
            continue
        response = await client.post(_VIDEO, json={"videoConnections": [item]})
        response.raise_for_status()
        check = await client.get(f"{_VIDEO}/{uid}", headers={"Accept": "application/json"})
        check.raise_for_status()
        if not _matches(check.json(), item):
            raise RuntimeError("TAK video publication is unverified")
