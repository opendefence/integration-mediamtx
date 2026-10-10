"""Prove binding writes against the supplied CRDs in this checkout's owned Kind cluster."""

import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
from contextlib import AsyncExitStack
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

import yaml
from cloudcoil.client import Config
from cloudcoil.errors import APIError

from odintegration_mediamtx.bindings import CoreUser, UserBinding, ensure_binding, set_binding_synced

ROOT = Path(__file__).resolve().parents[2]
NAMESPACE = "mediamtx-m2-bindings"
USER_NAME = "mediamtx-m2-binding-probe"
CRD_NAMES = {"users.platform.opendefence.fi", "userbindings.platform.opendefence.fi"}


def kubectl(*args: str, data: object = None) -> str:
    cluster = (ROOT / ".local/kind/owner").read_text().strip()
    expected = "mediamtx-" + hashlib.sha256(str(ROOT).encode()).hexdigest()[:12]
    if cluster != expected:
        raise ValueError("Refusing a cluster not owned by this checkout")
    return subprocess.run(
        [
            "kubectl",
            "--kubeconfig",
            str(ROOT / ".local/kind/kubeconfig"),
            "--context",
            "kind-" + cluster,
            "-n",
            NAMESPACE,
            *args,
        ],
        input=json.dumps(data) if data is not None else None,
        text=True,
        capture_output=True,
        check=True,
    ).stdout


def create_user() -> None:
    kubectl(
        "create",
        "-f",
        "-",
        data={
            "apiVersion": "platform.opendefence.fi/v1alpha1",
            "kind": "User",
            "metadata": {"name": USER_NAME},
            "spec": {"callsign": "M2-PROBE"},
        },
    )


async def exercise() -> dict[str, Any]:  # noqa: PLR0915 - Keep the live acceptance sequence explicit.
    cluster = (ROOT / ".local/kind/owner").read_text().strip()
    async with (
        Config(kubeconfig=ROOT / ".local/kind/kubeconfig", context="kind-" + cluster) as config,
        AsyncExitStack() as transports,
    ):
        transports.callback(config.client.close)
        transports.push_async_callback(config.async_client.aclose)
        users = await CoreUser.async_client(config, cached=False)
        bindings = await UserBinding.async_client(config, namespace=NAMESPACE, cached=False)
        user = await users.get(USER_NAME)
        created = await asyncio.gather(*(ensure_binding(user, bindings) for _ in range(8)))
        assert len({binding.metadata.uid for binding in created if binding.metadata}) == 1
        assert len(await bindings.list()) == 1
        first = created[0]
        assert first.status is None and first.name
        now = datetime.now(UTC)
        synced = await set_binding_synced(first, user, bindings, synced=True, now=now)
        assert synced.status and synced.status.observed_generation == 1
        assert synced.status.conditions[0].status == "True"
        assert synced.status.conditions[0].observed_generation == 1
        unchanged = await set_binding_synced(synced, user, bindings, synced=True, now=datetime.now(UTC))
        assert unchanged is synced
        try:
            await set_binding_synced(first, user, bindings, synced=False, now=now)
        except APIError as error:
            assert error.status_code in (409, 422)
        else:
            raise AssertionError("A stale status write was accepted")

        kubectl(
            "patch",
            "userbinding",
            first.name,
            "--subresource=status",
            "--type=merge",
            "-p",
            '{"status":{"accountId":"must-be-pruned","credentialRefs":[]}}',
        )
        raw = json.loads(kubectl("get", "userbinding", first.name, "-o", "json"))
        assert set(raw["status"]) == {"conditions", "observedGeneration"}

        kubectl("delete", "user", USER_NAME, "--wait=true")
        create_user()
        replacement_user = await users.get(USER_NAME)
        assert replacement_user.metadata and user.metadata
        assert replacement_user.metadata.uid != user.metadata.uid
        replacement_binding = await ensure_binding(replacement_user, bindings)
        assert replacement_binding.name != first.name
        assert len(await bindings.list()) == 2
        try:
            await set_binding_synced(first, replacement_user, bindings, synced=True, now=now)
        except ValueError:
            pass
        else:
            raise AssertionError("A binding was retargeted to a recreated User")

        # Reusing a binding name must also fail the old snapshot's UID guard.
        snapshot = await bindings.get(first.name)
        kubectl("delete", "userbinding", first.name, "--wait=true")
        body = snapshot.model_dump(mode="json", by_alias=True, exclude_none=True)
        body["metadata"] = {key: body["metadata"][key] for key in ("name", "namespace", "annotations", "labels")}
        body.pop("status", None)
        kubectl("create", "-f", "-", data=body)
        try:
            await set_binding_synced(snapshot, user, bindings, synced=False, now=now)
        except APIError as error:
            assert error.status_code in (409, 422)
        else:
            raise AssertionError("A replaced binding accepted the old UID snapshot")
        return {
            "concurrentCreators": len(created),
            "atomicCreate": True,
            "statusGeneration": synced.status.observed_generation,
            "statusNoOp": True,
            "staleWriteDenied": True,
            "unknownStatusFieldsPruned": True,
            "recreatedUserSeparated": True,
            "replacedBindingDenied": True,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--crds", type=Path, required=True, help="The supplied opendefence_core_crds.yaml")
    args = parser.parse_args()
    source = args.crds.read_bytes()
    documents: list[dict[str, Any]] = [
        document
        for document in yaml.safe_load_all(source)
        if isinstance(document, dict)
        and document.get("kind") == "CustomResourceDefinition"
        and document.get("metadata", {}).get("name") in CRD_NAMES
    ]
    if {document["metadata"]["name"] for document in documents} != CRD_NAMES:
        raise ValueError("The supplied User and UserBinding CRDs are required")
    if kubectl("get", "crd", *sorted(CRD_NAMES), "--ignore-not-found", "-o", "name").strip():
        raise ValueError("Refusing to replace existing Core CRDs")
    installed: list[str] = []
    namespace_created = user_created = False
    try:
        for document in documents:
            kubectl("create", "-f", "-", data=document)
            installed.append(document["metadata"]["name"])
        kubectl("wait", "--for=condition=Established", "--timeout=30s", "crd", *installed)
        kubectl("create", "namespace", NAMESPACE)
        namespace_created = True
        create_user()
        user_created = True
        report = asyncio.run(exercise())
    finally:
        if user_created:
            kubectl("delete", "user", USER_NAME, "--ignore-not-found", "--wait=true")
        if namespace_created:
            kubectl("delete", "namespace", NAMESPACE, "--wait=true", "--timeout=60s")
        if installed:
            kubectl("delete", "crd", *installed, "--wait=true", "--timeout=60s")
    report.update(
        coreCrdSourceSha256=hashlib.sha256(source).hexdigest(),
        cloudcoilRevision="e8ec4ef00c03b2c8974ed7ed0c99a7280ee802c8",
        cloudcoilVersion=version("cloudcoil"),
        pythonVersion=sys.version.split()[0],
        packageSourceSha256={
            module: hashlib.sha256((ROOT / "src/odintegration_mediamtx" / module).read_bytes()).hexdigest()
            for module in ("bindings.py", "identity.py")
        },
        namespaceCleanup=True,
        crdCleanup=True,
        userCleanup=True,
    )
    state = ROOT / ".local/m2"
    state.mkdir(parents=True, exist_ok=True)
    (state / "bindings-results.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    if not __debug__:
        raise SystemExit("Assertions are required; do not use Python -O")
    main()
