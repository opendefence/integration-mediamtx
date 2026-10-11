"""Exercise MediaMTX revocation scans against its v3 list and kick contract."""

import asyncio
from uuid import UUID

import httpx
import pytest

from opendefence_integration_mediamtx.sessions import drain_grant_sessions

GRANT = "g_" + "a" * 22
OTHER = "g_" + "b" * 22
SESSION = str(UUID(int=1))
ROUTES = {
    "hls": "hls/sessions",
    "rtsps": "rtsps/sessions",
    "rtmps": "rtmps/conns",
    "srt": "srt/conns",
    "webrtc": "webrtc/sessions",
}


@pytest.mark.parametrize(("protocol", "route"), ROUTES.items())
def test_kicks_only_matching_grant_across_each_protocol(protocol: str, route: str) -> None:
    requests: list[httpx.Request] = []
    kicked = False

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal kicked
        requests.append(request)
        assert request.url.path.startswith(f"/v3/{route}/")
        if request.method == "POST":
            kicked = True
            assert request.url.path == f"/v3/{route}/kick/{SESSION}"
            return httpx.Response(404)  # Already absent is a successful drain.
        assert request.url.params["page"] == "0"
        return httpx.Response(
            200,
            json={
                "pageCount": 1,
                "items": [] if kicked else [{"id": SESSION, "user": GRANT}, {"id": str(UUID(int=2)), "user": OTHER}],
            },
        )

    async def run() -> int:
        async with httpx.AsyncClient(
            base_url="https://mediamtx.test", transport=httpx.MockTransport(respond)
        ) as client:
            return await drain_grant_sessions(client, GRANT, protocols=frozenset({protocol}))

    assert asyncio.run(run()) == 1
    assert [request.method for request in requests] == ["GET", "POST", "GET", "GET"]


def test_reads_every_page_then_rescans_after_kicking() -> None:
    requested_pages: list[str] = []
    kicked = False

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal kicked
        if request.method == "POST":
            kicked = True
            return httpx.Response(200, json={"status": "ok"})
        page = request.url.params["page"]
        requested_pages.append(page)
        return httpx.Response(
            200,
            json={
                "pageCount": 2 if not kicked else 0,
                "items": []
                if kicked
                else [{"id": str(UUID(int=2)) if page == "0" else SESSION, "user": OTHER if page == "0" else GRANT}],
            },
        )

    async def run() -> int:
        async with httpx.AsyncClient(
            base_url="https://mediamtx.test", transport=httpx.MockTransport(respond)
        ) as client:
            return await drain_grant_sessions(client, GRANT, protocols=frozenset({"hls"}))

    assert asyncio.run(run()) == 1
    assert requested_pages == ["0", "1", "0", "0"]


def test_session_appearing_during_empty_scan_is_removed() -> None:
    scans = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal scans
        if request.method == "POST":
            return httpx.Response(200)
        scans += 1
        return httpx.Response(
            200,
            json={"pageCount": 1, "items": [{"id": SESSION, "user": GRANT}] if scans == 2 else []},
        )

    async def run() -> int:
        async with httpx.AsyncClient(
            base_url="https://mediamtx.test", transport=httpx.MockTransport(respond)
        ) as client:
            return await drain_grant_sessions(client, GRANT, protocols=frozenset({"hls"}))

    assert asyncio.run(run()) == 1
    assert scans == 4


def test_unfinished_cleanup_stays_an_error() -> None:
    kicks = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal kicks
        if request.method == "POST":
            kicks += 1
            return httpx.Response(200)
        return httpx.Response(200, json={"pageCount": 1, "items": [{"id": SESSION, "user": GRANT}]})

    async def run() -> None:
        async with httpx.AsyncClient(
            base_url="https://mediamtx.test", transport=httpx.MockTransport(respond)
        ) as client:
            with pytest.raises(RuntimeError, match="did not converge"):
                await drain_grant_sessions(client, GRANT, protocols=frozenset({"hls"}))

    asyncio.run(run())
    assert kicks == 6


@pytest.mark.parametrize(
    "listing",
    [
        {"pageCount": "1", "items": []},
        {"pageCount": 1, "items": [{"id": SESSION}]},
        {"pageCount": 1, "items": [{"id": "../another", "user": GRANT}]},
        {"pageCount": 1001, "items": []},
    ],
)
def test_invalid_listing_never_kicks(listing: dict[str, object]) -> None:
    methods: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        return httpx.Response(200, json=listing)

    async def run() -> None:
        async with httpx.AsyncClient(
            base_url="https://mediamtx.test", transport=httpx.MockTransport(respond)
        ) as client:
            with pytest.raises(ValueError, match="Invalid MediaMTX"):
                await drain_grant_sessions(client, GRANT, protocols=frozenset({"hls"}))

    asyncio.run(run())
    assert methods == ["GET"]


def test_api_failure_cannot_be_reported_as_clean() -> None:
    def respond(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    async def run() -> None:
        async with httpx.AsyncClient(
            base_url="https://mediamtx.test", transport=httpx.MockTransport(respond)
        ) as client:
            with pytest.raises(httpx.HTTPStatusError):
                await drain_grant_sessions(client, GRANT, protocols=frozenset({"hls"}))

    asyncio.run(run())


def test_rejects_unscoped_or_plain_http_client() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        pytest.fail(f"Unexpected {request.method}")

    async def run() -> None:
        async with httpx.AsyncClient(base_url="http://mediamtx.test", transport=httpx.MockTransport(respond)) as client:
            with pytest.raises(ValueError, match="HTTPS"):
                await drain_grant_sessions(client, GRANT, protocols=frozenset({"hls"}))
        async with httpx.AsyncClient(
            base_url="https://mediamtx.test", transport=httpx.MockTransport(respond)
        ) as client:
            with pytest.raises(ValueError, match="Invalid grant"):
                await drain_grant_sessions(client, "not-a-grant", protocols=frozenset({"hls"}))

    asyncio.run(run())
