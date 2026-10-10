"""Binding observations; provisioning stays pending until the Core policy contract exists."""

import logging
import os
from datetime import UTC, datetime
from functools import partial
from uuid import UUID

from cloudcoil.application import Application, RBACRule
from cloudcoil.client import Config
from cloudcoil.controller import Controller, HealthServer, Request, ResourceKey, Result
from cloudcoil.errors import ResourceNotFound

from opendefence_integration_mediamtx.bindings import (
    MANAGED_BY,
    CoreUser,
    UserBinding,
    ensure_binding,
    set_binding_pending,
)


def binding_keys(user: CoreUser, *, namespace: str) -> list[ResourceKey]:
    """Map User changes and deletions without treating cached identity as authority."""
    meta = user.metadata
    if not meta or not meta.name or not meta.uid or meta.namespace is not None:
        return []
    try:
        subject = UUID(meta.uid)
    except ValueError:
        return []
    if str(subject) != meta.uid:
        return []
    return [ResourceKey(f"mediamtx-{subject.hex}", namespace)]


async def reconcile_binding(request: Request[UserBinding], *, namespace: str) -> Result | None:
    if request.namespace != namespace:
        raise ValueError("UserBinding is outside the operator namespace")
    bindings = await request.client(UserBinding)
    try:
        binding = await bindings.get(request.name)
    except ResourceNotFound:
        # shortcut: scan a few hundred cached Users; add an index if that bound grows.
        candidate = next(
            (
                user
                for user in request.cached(CoreUser).list()
                if request.key in binding_keys(user, namespace=namespace)
            ),
            None,
        )
        if candidate is None:
            return None
        users = await request.client(CoreUser)
        try:
            user = await users.get(candidate.name or "")
        except ResourceNotFound:
            return None
        if request.key not in binding_keys(user, namespace=namespace) or (
            user.metadata and user.metadata.deletion_timestamp
        ):
            return None
        binding = await ensure_binding(user, bindings)
    if binding.metadata and binding.metadata.deletion_timestamp:
        return None
    await set_binding_pending(binding, bindings, now=datetime.now(UTC))
    return Result(requeue_after=60)


def create_operator(*, namespace: str, config: Config | None = None) -> Application:
    """Use Cloudcoil's scoped watches, retry queue, CLI and transport lifecycle."""
    controller = Controller(
        UserBinding,
        partial(reconcile_binding, namespace=namespace),
        namespace=namespace,
        label_selector=f"app.kubernetes.io/managed-by={MANAGED_BY}",
        events=False,
        status_updates=False,
        reconcile_timeout=30,
    )
    controller.watch(CoreUser, mapper=partial(binding_keys, namespace=namespace))
    return Application(
        "mediamtx-operator",
        controller,
        namespace=namespace,
        config=config,
        rules=(
            RBACRule(CoreUser, ("get", "list", "watch"), plural="users", scope="Cluster"),
            RBACRule(UserBinding, ("create",), plural="userbindings", scope="Namespaced"),
            RBACRule(UserBinding, ("patch",), subresources=("status",)),
        ),
        health=HealthServer(host="0.0.0.0", port=8080),  # nosec B104 # Pod diagnostics, protected by deployment networking.
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    create_operator(namespace=os.environ.get("CLOUDCOIL_NAMESPACE", "integration-mediamtx")).main()


if __name__ == "__main__":
    main()
