"""Exercise TAK publication, verified writes, retries, and feed ownership."""

import copy
import json
from typing import Any

import httpx
import pytest

from opendefence_integration_mediamtx.paths import parse_path
from opendefence_integration_mediamtx.tak import sync_feeds, video_collection

NAMESPACE = "integration-mediamtx"
ORIGIN = "rtsps://media.test:8322"
ALPHA = parse_path("live/ipcam/alpha")
BRAVO = parse_path("live/uas/bravo")


class TakServer:
    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}
        self.requests: list[httpx.Request] = []
        self.ignore_writes = False
        self.lose_reply = False

    def respond(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.url.path.startswith("/Marti/api/video")
        uid = request.url.path.rsplit("/", 1)[-1]
        if request.method == "POST":
            item = json.loads(request.content)["videoConnections"][0]
            if not self.ignore_writes:
                self.records[item["uuid"]] = item
            if self.lose_reply:
                raise httpx.ReadTimeout("Lost response", request=request)
            return httpx.Response(200)
        if request.method == "DELETE":
            if not self.ignore_writes:
                self.records.pop(uid, None)
            return httpx.Response(200)
        if uid == "video":
            return httpx.Response(200, json={"videoConnections": list(self.records.values())})
        return httpx.Response(200, json=self.records[uid]) if uid in self.records else httpx.Response(404)


@pytest.mark.asyncio
async def test_creates_updates_and_removes_only_owned_feeds_after_restart() -> None:
    server = TakServer()
    foreign = video_collection(ALPHA, namespace="other-installation", media_url=ORIGIN)
    server.records[foreign["uuid"]] = copy.deepcopy(foreign)
    async with httpx.AsyncClient(base_url="https://tak.test", transport=httpx.MockTransport(server.respond)) as client:
        await sync_feeds(client, {ALPHA, BRAVO}, namespace=NAMESPACE, media_url=ORIGIN)
        assert len(server.records) == 3
        before = len(server.requests)
        await sync_feeds(client, {ALPHA, BRAVO}, namespace=NAMESPACE, media_url=ORIGIN)
        assert [item.method for item in server.requests[before:]] == ["GET"]
        await sync_feeds(client, {BRAVO}, namespace=NAMESPACE, media_url="rtsps://new-media.test:8322")
        assert len(server.records) == 2
        assert server.records[foreign["uuid"]] == foreign
        updated = video_collection(BRAVO, namespace=NAMESPACE, media_url="rtsps://new-media.test:8322")
        assert server.records[updated["uuid"]] == updated
    # No in-memory ownership ledger is needed after a process restart.
    async with httpx.AsyncClient(base_url="https://tak.test", transport=httpx.MockTransport(server.respond)) as client:
        await sync_feeds(client, set(), namespace=NAMESPACE, media_url=ORIGIN)
    assert server.records == {foreign["uuid"]: foreign}


@pytest.mark.asyncio
async def test_http_success_is_not_enough_for_publication_or_deletion() -> None:
    server = TakServer()
    server.ignore_writes = True
    async with httpx.AsyncClient(base_url="https://tak.test", transport=httpx.MockTransport(server.respond)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await sync_feeds(client, {ALPHA}, namespace=NAMESPACE, media_url=ORIGIN)
        existing = video_collection(ALPHA, namespace=NAMESPACE, media_url=ORIGIN)
        server.records[existing["uuid"]] = existing
        with pytest.raises(RuntimeError, match="publication is unverified"):
            await sync_feeds(client, {ALPHA}, namespace=NAMESPACE, media_url="rtsps://changed.test:8322")
        with pytest.raises(RuntimeError, match="deletion is unverified"):
            await sync_feeds(client, set(), namespace=NAMESPACE, media_url=ORIGIN)


@pytest.mark.asyncio
async def test_retry_after_lost_write_reply_does_not_duplicate_the_feed() -> None:
    server = TakServer()
    server.lose_reply = True
    async with httpx.AsyncClient(base_url="https://tak.test", transport=httpx.MockTransport(server.respond)) as client:
        with pytest.raises(httpx.ReadTimeout):
            await sync_feeds(client, {ALPHA}, namespace=NAMESPACE, media_url=ORIGIN)
        server.lose_reply = False
        await sync_feeds(client, {ALPHA}, namespace=NAMESPACE, media_url=ORIGIN)
    assert len(server.records) == 1
    assert len([request for request in server.requests if request.method == "POST"]) == 1


@pytest.mark.parametrize(
    "origin",
    [
        "http://media.test",
        "rtsp://media.test",
        "rtsps://a:b@media.test",
        "rtsps://media.test/?token=x",
        "rtsps://media.test/base",
        "rtsps://media.test/#key",
    ],
)
def test_feed_urls_cannot_distribute_credentials_or_insecure_endpoints(origin: str) -> None:
    with pytest.raises(ValueError):
        video_collection(ALPHA, namespace=NAMESPACE, media_url=origin)


def test_identifiers_are_stable_and_scoped_to_the_installation() -> None:
    record = video_collection(ALPHA, namespace=NAMESPACE, media_url=ORIGIN)
    assert record["uuid"] == video_collection(ALPHA, namespace=NAMESPACE, media_url="rtsps://new.test")["uuid"]
    assert record["uuid"] != video_collection(ALPHA, namespace="other", media_url=ORIGIN)["uuid"]
    assert record["feeds"][0]["url"] == "rtsps://media.test:8322/live/ipcam/alpha"


@pytest.mark.parametrize(
    "listing",
    [{}, {"videoConnections": [None]}, {"videoConnections": [{"uuid": "mediamtx:integration-mediamtx:../other"}]}],
)
@pytest.mark.asyncio
async def test_invalid_remote_inventory_never_causes_writes(listing: dict[str, object]) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return httpx.Response(200, json=listing)

    async with httpx.AsyncClient(base_url="https://tak.test", transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(ValueError):
            await sync_feeds(client, {ALPHA}, namespace=NAMESPACE, media_url=ORIGIN)
