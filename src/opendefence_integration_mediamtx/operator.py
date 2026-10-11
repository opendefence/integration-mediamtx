"""Observe bindings and issue passwords; readiness waits for the remaining lifecycle work."""

import logging
import os
from datetime import UTC, datetime
from functools import partial
from typing import Any, override
from uuid import UUID

from cloudcoil.application import Application, RBACRule
from cloudcoil.client import Config
from cloudcoil.controller import Controller, HealthServer, Request, ResourceKey, Result
from cloudcoil.errors import ResourceNotFound
from cloudcoil.models.kubernetes.core.v1 import Secret
from lib_opendefence_core.models.v1alpha1 import User, UserBinding

from opendefence_integration_mediamtx.bindings import (
    MANAGED_BY,
    ensure_binding,
    set_binding_pending,
)
from opendefence_integration_mediamtx.credentials import active_user, ensure_user_password


class BindingApplication(Application):
    @override
    def manifests(self, **options: Any) -> list[dict[str, Any]]:
        # Core owns the shared CRDs that Cloudcoil discovers on its models.
        return [
            document
            for document in super().manifests(**options)
            if not (
                document["kind"] == "CustomResourceDefinition"
                and document["spec"]["group"] == "platform.opendefence.fi"
            )
        ]


def binding_keys(user: User, *, namespace: str) -> list[ResourceKey]:
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
        raise ValueError("UserBinding is outside the mediamtx-operator namespace")
    user: User | None = None
    bindings = await request.client(UserBinding)
    try:
        binding = await bindings.get(request.name)
    except ResourceNotFound:
        # shortcut: scan a few hundred cached Users; add an index if that bound grows.
        candidate = next(
            (user for user in request.cached(User).list() if request.key in binding_keys(user, namespace=namespace)),
            None,
        )
        if candidate is None:
            return None
        users = await request.client(User)
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
    if user is None:
        users = await request.client(User)
        try:
            user = await users.get(binding.spec.user_ref.name)
        except ResourceNotFound:
            return Result(requeue_after=60)
    if request.key in binding_keys(user, namespace=namespace) and active_user(user):
        passwords = await request.client(Secret)
        await ensure_user_password(user, passwords)
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
    controller.watch(User, mapper=partial(binding_keys, namespace=namespace))
    return BindingApplication(
        "mediamtx-operator",
        controller,
        namespace=namespace,
        config=config,
        rules=(
            RBACRule(User, ("get", "list", "watch"), plural="users", scope="Cluster"),
            RBACRule(UserBinding, ("create",), plural="userbindings", scope="Namespaced"),
            RBACRule(UserBinding, ("patch",), subresources=("status",)),
            RBACRule(Secret, ("get", "create"), plural="secrets", scope="Namespaced"),
        ),
        health=HealthServer(host="0.0.0.0", port=8080),  # nosec B104 # Pod diagnostics, protected by deployment networking.
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    create_operator(namespace=os.environ.get("CLOUDCOIL_NAMESPACE", "integration-mediamtx")).main()


if __name__ == "__main__":
    main()
