"""Read complete MediaMTX path snapshots before changing the stream catalogue."""

import httpx

from opendefence_integration_mediamtx.paths import StreamPath, parse_path


async def active_paths(client: httpx.AsyncClient) -> set[StreamPath]:
    """Reject partial or changing pagination; advertise only canonical ready paths."""
    if client.base_url.scheme != "https":
        raise ValueError("MediaMTX control API requires HTTPS")
    paths: set[StreamPath] = set()
    seen: set[str] = set()
    expected: tuple[int, int] | None = None
    for page in range(1000):
        response = await client.get("/v3/paths/list", params={"itemsPerPage": 100, "page": page})
        response.raise_for_status()
        listing = response.json()
        if not isinstance(listing, dict):
            raise ValueError("Invalid MediaMTX path list")
        items, pages, count = listing.get("items"), listing.get("pageCount"), listing.get("itemCount")
        if (
            not isinstance(items, list)
            or type(pages) is not int
            or not 0 <= pages <= 1000
            or type(count) is not int
            or count < 0
            or (pages == 0 and count != 0)
            or (expected is not None and expected != (pages, count))
        ):
            raise ValueError("Invalid or changing MediaMTX path list")
        expected = pages, count
        for item in items:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("name"), str)
                or type(item.get("ready")) is not bool
                or item["name"] in seen
            ):
                raise ValueError("Invalid or duplicate MediaMTX path")
            seen.add(item["name"])
            if item["ready"]:
                try:
                    paths.add(parse_path(item["name"]))
                except ValueError:
                    continue  # Superadmins can publish outside the canonical catalogue.
        if page + 1 >= pages:
            if len(seen) != count:
                raise ValueError("Incomplete MediaMTX path list")
            return paths
    raise ValueError("MediaMTX path pagination exceeded its limit")
