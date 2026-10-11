"""Keep TAK feed metadata aligned with active streams and current User approval."""

import asyncio
import logging
import ssl

import httpx
from cloudcoil.client import AsyncAPIClient
from cloudcoil.errors import APIError, ResourceNotFound
from cloudcoil.models.kubernetes.core.v1 import Secret
from lib_opendefence_core.models.v1alpha1 import User

from opendefence_integration_mediamtx.credentials import CONTROL_USER, active_user, control_password
from opendefence_integration_mediamtx.streams import active_paths
from opendefence_integration_mediamtx.tak import sync_feeds

_LOGGER = logging.getLogger(__name__)


async def reconcile_catalogue(
    media: httpx.AsyncClient,
    tak: httpx.AsyncClient,
    users: AsyncAPIClient[User],
    *,
    namespace: str,
    media_url: str,
) -> int:
    """An unavailable source is an error, never an empty desired catalogue."""
    paths = await active_paths(media)
    approved: set[str] = set()
    for callsign in sorted({path.owner_callsign for path in paths}):
        try:
            user = await users.get(callsign)
        except ResourceNotFound:
            continue
        if user.name == callsign and user.spec.callsign == callsign and active_user(user):
            approved.add(callsign)
    desired = {path for path in paths if path.owner_callsign in approved}
    await sync_feeds(tak, desired, namespace=namespace, media_url=media_url)
    return len(desired)


async def run_catalogue(*, namespace: str, tak_url: str, media_url: str, server_name: str = "") -> None:
    """Retry transient failures and reload mounted client certificates on each scan."""
    users = await User.async_client(cached=False)
    passwords = await Secret.async_client(namespace=namespace, cached=False)

    async def server_identity(request: httpx.Request) -> None:
        if server_name:
            request.extensions["sni_hostname"] = server_name

    while True:
        try:
            async with asyncio.timeout(60):
                media_tls = ssl.create_default_context(cafile="/var/run/mediamtx-control/ca.crt")
                tak_tls = ssl.create_default_context(cafile="/var/run/tak/ca.crt")
                tak_tls.load_cert_chain("/var/run/tak/tls.crt", "/var/run/tak/tls.key")
                async with (
                    httpx.AsyncClient(
                        base_url=f"https://mediamtx.{namespace}.svc:9997",
                        verify=media_tls,
                        auth=(CONTROL_USER, await control_password(passwords)),
                        trust_env=False,
                        timeout=10,
                    ) as media,
                    httpx.AsyncClient(
                        base_url=tak_url,
                        verify=tak_tls,
                        event_hooks={"request": [server_identity]},
                        trust_env=False,
                        timeout=10,
                    ) as tak,
                ):
                    count = await reconcile_catalogue(media, tak, users, namespace=namespace, media_url=media_url)
                    _LOGGER.debug("TAK catalogue verified: %d active streams", count)
        except (APIError, httpx.HTTPError, OSError, TimeoutError, ValueError, RuntimeError) as error:
            # Exception messages can contain remote payloads; log only the error type.
            _LOGGER.warning("TAK catalogue reconciliation failed (%s); retrying", type(error).__name__)
        await asyncio.sleep(10)
