"""Use live User projections to filter TAK metadata without core-operator."""

import json
import asyncio
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from cloudcoil.client import AsyncAPIClient
from cloudcoil.errors import APIError
from lib_opendefence_core.models.v1alpha1 import User
from cloudcoil.models.kubernetes.core.v1 import Secret

from opendefence_integration_mediamtx.catalogue import reconcile_catalogue
from opendefence_integration_mediamtx import catalogue


@pytest.mark.asyncio
async def test_poll_retries_without_logging_payloads_and_reloads_certificates(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(User, "async_client", AsyncMock())
    monkeypatch.setattr(Secret, "async_client", AsyncMock())
    monkeypatch.setattr(catalogue, "control_password", AsyncMock(return_value="test"))
    tls = Mock()
    monkeypatch.setattr(catalogue.ssl, "create_default_context", tls)
    client = AsyncMock()
    clients = Mock(return_value=client)
    monkeypatch.setattr(catalogue.httpx, "AsyncClient", clients)
    reconcile = AsyncMock(side_effect=[RuntimeError("sensitive remote response"), 1])
    monkeypatch.setattr(catalogue, "reconcile_catalogue", reconcile)
    monkeypatch.setattr(catalogue.asyncio, "sleep", AsyncMock(side_effect=[None, asyncio.CancelledError]))
    with pytest.raises(asyncio.CancelledError):
        await catalogue.run_catalogue(
            namespace="media",
            tak_url="https://tak.test",
            media_url="rtsps://media.test",
            server_name="certificate.test",
        )
    assert reconcile.await_count == 2 and tls.call_count == 4
    assert tls.return_value.load_cert_chain.call_count == 2
    assert "RuntimeError" in caplog.text and "sensitive remote response" not in caplog.text
    tak_options = clients.call_args_list[-1].kwargs
    assert tak_options["trust_env"] is False and tak_options["verify"] is tls.return_value
    request = httpx.Request("GET", "https://tak.test/Marti/api/video")
    await tak_options["event_hooks"]["request"][0](request)
    assert request.extensions["sni_hostname"] == "certificate.test"


@pytest.mark.parametrize("state", ["active", "revoked", "unapproved", "missing", "outage"])
@pytest.mark.asyncio
async def test_only_current_approved_stream_owners_are_published(state: str) -> None:
    writes: list[str] = []
    record: dict[str, Any] | None = None

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal record
        if request.url.host == "media.test":
            return httpx.Response(
                200, json={"pageCount": 1, "itemCount": 1, "items": [{"name": "live/ipcam/alpha", "ready": True}]}
            )
        if request.url.host == "kubernetes.test":
            if state in {"missing", "outage"}:
                return httpx.Response(
                    404 if state == "missing" else 503,
                    json={"reason": "NotFound" if state == "missing" else "Unavailable"},
                )
            spec: dict[str, object] = {"callsign": "alpha"}
            if state != "unapproved":
                spec["approvedAt"] = datetime.now(UTC).isoformat()
            if state == "revoked":
                spec["revokedAt"] = datetime.now(UTC).isoformat()
            return httpx.Response(
                200,
                json={
                    "apiVersion": "platform.opendefence.fi/v1alpha1",
                    "kind": "User",
                    "metadata": {"name": "alpha"},
                    "spec": spec,
                },
            )
        if state == "outage":
            pytest.fail("TAK must not receive a request after a source outage")
        if request.method == "POST":
            writes.append(request.method)
            record = json.loads(request.content)["videoConnections"][0]
            return httpx.Response(200)
        if request.url.path == "/Marti/api/video":
            return httpx.Response(200, json={"videoConnections": []})
        return httpx.Response(200, json=record)

    transport = httpx.MockTransport(respond)
    async with (
        httpx.AsyncClient(base_url="https://media.test", transport=transport) as media,
        httpx.AsyncClient(base_url="https://tak.test", transport=transport) as tak,
        httpx.AsyncClient(base_url="https://kubernetes.test", transport=transport) as kube,
    ):
        users = AsyncAPIClient(
            api_version="platform.opendefence.fi/v1alpha1",
            kind=User,
            resource="users",
            subresources=[],
            default_namespace="integration-mediamtx",
            namespaced=False,
            client=kube,
        )
        if state == "outage":
            with pytest.raises(APIError):
                await reconcile_catalogue(
                    media, tak, users, namespace="integration-mediamtx", media_url="rtsps://media.test"
                )
        else:
            assert await reconcile_catalogue(
                media, tak, users, namespace="integration-mediamtx", media_url="rtsps://media.test"
            ) == int(state == "active")
    assert writes == (["POST"] if state == "active" else [])
