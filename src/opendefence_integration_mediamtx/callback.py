"""Private HTTPS endpoint for MediaMTX's password authorization callback."""

import argparse
import asyncio
import json
import os
from contextlib import AsyncExitStack

import httpx
import uvicorn
from cloudcoil.client import AsyncAPIClient, Config
from cloudcoil.errors import APIError
from cloudcoil.models.kubernetes.core.v1 import Secret
from lib_opendefence_core.models.v1alpha1 import User
from uvicorn._types import ASGIReceiveCallable, ASGISendCallable, Scope

from opendefence_integration_mediamtx.authorization import authorize_user


class AuthCallback:
    """One private route, bounded requests, and no credential-bearing response or log."""

    def __init__(self, users: AsyncAPIClient[User], passwords: AsyncAPIClient[Secret]) -> None:
        self.users = users
        self.passwords = passwords

    async def __call__(self, scope: Scope, receive: ASGIReceiveCallable, send: ASGISendCallable) -> None:
        if scope["type"] != "http":
            return
        status = 404
        if scope["path"] == "/internal/mediamtx/auth":
            status = 405
            if scope["method"] == "POST":
                try:
                    async with asyncio.timeout(5):
                        body = bytearray()
                        while True:
                            message = await receive()
                            if message["type"] == "http.disconnect":
                                return
                            if message["type"] != "http.request":
                                raise ValueError("Invalid callback body")
                            body.extend(message.get("body", b""))
                            if len(body) > 32768:
                                raise ValueError("Callback body too large")
                            if not message.get("more_body", False):
                                break
                        allowed = await authorize_user(json.loads(body), self.users, self.passwords)
                        status = 204 if allowed else 403
                except ValueError, RecursionError:
                    status = 400
                except APIError, httpx.HTTPError, TimeoutError:
                    status = 503
        await send({"type": "http.response.start", "status": status, "headers": [(b"cache-control", b"no-store")]})
        await send({"type": "http.response.body", "body": b""})


async def _serve(options: argparse.Namespace) -> None:
    async with Config(namespace=options.namespace) as config, AsyncExitStack() as transports:
        transports.callback(config.client.close)
        transports.push_async_callback(config.async_client.aclose)
        users = await User.async_client(config, cached=False)
        passwords = await Secret.async_client(config, namespace=options.namespace, cached=False)
        # shortcut: certificates load at startup; add reload before unattended production use.
        server = uvicorn.Server(
            uvicorn.Config(
                AuthCallback(users, passwords),
                host=options.host,
                port=options.port,
                ssl_certfile=options.tls_cert,
                ssl_keyfile=options.tls_key,
                lifespan="off",
                access_log=False,
                limit_concurrency=128,
                timeout_keep_alive=5,
                timeout_graceful_shutdown=10,
            )
        )
        await server.serve()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", default=os.environ.get("CLOUDCOIL_NAMESPACE", "integration-mediamtx"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9443)
    parser.add_argument("--tls-cert", required=True)
    parser.add_argument("--tls-key", required=True)
    asyncio.run(_serve(parser.parse_args()))


if __name__ == "__main__":
    main()
