"""Keep incomplete MediaMTX snapshots from removing valid catalogue entries."""

import httpx
import pytest

from opendefence_integration_mediamtx.paths import parse_path
from opendefence_integration_mediamtx.streams import active_paths


@pytest.mark.asyncio
async def test_reads_all_pages_and_only_returns_canonical_ready_paths() -> None:
    pages: list[int] = []

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET" and request.url.path == "/v3/paths/list"
        page = int(request.url.params["page"])
        pages.append(page)
        items = [
            [{"name": "live/ipcam/alpha", "ready": True}, {"name": "live/gopro/alpha", "ready": False}],
            [{"name": "admin/custom", "ready": True}, {"name": "live/uas/bravo", "ready": True}],
        ][page]
        return httpx.Response(200, json={"pageCount": 2, "itemCount": 4, "items": items})

    async with httpx.AsyncClient(base_url="https://media.test", transport=httpx.MockTransport(respond)) as client:
        assert await active_paths(client) == {parse_path("live/ipcam/alpha"), parse_path("live/uas/bravo")}
    assert pages == [0, 1]


@pytest.mark.parametrize(
    "listing",
    [
        {},
        {"pageCount": 1001, "itemCount": 0, "items": []},
        {"pageCount": 1, "itemCount": 1, "items": []},
        {"pageCount": 1, "itemCount": 1, "items": [{"name": "live/ipcam/alpha", "ready": "true"}]},
        {"pageCount": 1, "itemCount": 2, "items": [{"name": "live/ipcam/alpha", "ready": True}] * 2},
    ],
)
@pytest.mark.asyncio
async def test_rejects_invalid_or_incomplete_snapshots(listing: dict[str, object]) -> None:
    async with httpx.AsyncClient(
        base_url="https://media.test", transport=httpx.MockTransport(lambda _: httpx.Response(200, json=listing))
    ) as client:
        with pytest.raises(ValueError):
            await active_paths(client)


@pytest.mark.asyncio
async def test_changed_pagination_and_outages_never_return_an_empty_snapshot() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        return httpx.Response(200, json={"pageCount": 2 - page, "itemCount": 2, "items": []})

    async with httpx.AsyncClient(base_url="https://media.test", transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(ValueError, match="changing"):
            await active_paths(client)
    async with httpx.AsyncClient(
        base_url="https://media.test", transport=httpx.MockTransport(lambda _: httpx.Response(503))
    ) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await active_paths(client)


@pytest.mark.asyncio
async def test_empty_snapshot_and_plaintext_refusal() -> None:
    async with httpx.AsyncClient(
        base_url="https://media.test",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"pageCount": 0, "itemCount": 0, "items": []})
        ),
    ) as client:
        assert await active_paths(client) == set()
        client.base_url = "http://media.test"
        with pytest.raises(ValueError, match="HTTPS"):
            await active_paths(client)
