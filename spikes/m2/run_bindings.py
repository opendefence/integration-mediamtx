"""Prove binding writes against the supplied CRDs in this checkout's owned Kind cluster."""

import argparse
import asyncio
import hashlib
import json
import subprocess  # nosec B404 # Harness invokes local kubectl with an argument vector.
import sys
from contextlib import AsyncExitStack
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

import yaml
from cloudcoil.client import Config
from cloudcoil.errors import APIError

from opendefence_integration_mediamtx.bindings import CoreUser, UserBinding, ensure_binding, set_binding_synced
from opendefence_integration_mediamtx.operator import binding_keys, create_operator

ROOT = Path(__file__).resolve().parents[2]
NAMESPACE = "mediamtx-m2-bindings"
USER_NAME = "mediamtx-m2-binding-probe"
CRD_NAMES = {"users.platform.opendefence.fi", "userbindings.platform.opendefence.fi"}


def kubectl(*args: str, data: object = None) -> str:
    cluster = (ROOT / ".local/kind/owner").read_text().strip()
    expected = "mediamtx-" + hashlib.sha256(str(ROOT).encode()).hexdigest()[:12]
    if cluster != expected:
        raise ValueError("Refusing a cluster not owned by this checkout")
    return subprocess.run(  # nosec B603 B607 # Developer kubectl from PATH, shell-free arguments.
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


async def exercise(*, run_operator: bool = False) -> dict[str, Any]:  # noqa: PLR0915 - Explicit live acceptance sequence.
    cluster = (ROOT / ".local/kind/owner").read_text().strip()
    async with (
        Config(kubeconfig=ROOT / ".local/kind/kubeconfig", context="kind-" + cluster, namespace=NAMESPACE) as config,
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
        report = {
            "concurrentCreators": len(created),
            "atomicCreate": True,
            "statusGeneration": synced.status.observed_generation,
            "statusNoOp": True,
            "staleWriteDenied": True,
            "unknownStatusFieldsPruned": True,
            "recreatedUserSeparated": True,
            "replacedBindingDenied": True,
        }
        if run_operator:
            report.update(await exercise_operator(config))
        return report


async def exercise_operator(config: Config) -> dict[str, Any]:  # noqa: PLR0915 - Explicit live reconciliation assertions.
    users = await CoreUser.async_client(config, cached=False)
    bindings = await UserBinding.async_client(config, namespace=NAMESPACE, cached=False)
    current_user = await users.get(USER_NAME)
    current_key = binding_keys(current_user, namespace=NAMESPACE)[0]
    orphan = next(binding for binding in await bindings.list() if binding.name != current_key.name)
    assert orphan.name
    fixture_condition = {
        "type": "Synced",
        "status": "True",
        "reason": "Fixture",
        "message": "Former readiness fixture.",
        "lastTransitionTime": datetime.now(UTC).isoformat(),
        "observedGeneration": 1,
    }
    kubectl(
        "patch",
        "userbinding",
        orphan.name,
        "--subresource=status",
        "--type=merge",
        "-p",
        json.dumps({"status": {"observedGeneration": 1, "conditions": [fixture_condition]}}),
    )
    kubectl("delete", "userbinding", current_key.name, "--wait=true")
    unrelated = await bindings.create(
        UserBinding.model_validate(
            {
                "metadata": {
                    "name": "unrelated-observation",
                    "namespace": NAMESPACE,
                    "labels": {"app.kubernetes.io/managed-by": "another-integration"},
                },
                "spec": {"userRef": {"name": USER_NAME}},
            }
        )
    )
    app = create_operator(namespace=NAMESPACE, config=config)
    # The probe tests reconciliation against Kubernetes, without opening a diagnostics port.
    app.health = None
    stop = asyncio.Event()
    running = asyncio.create_task(app.run(stop=stop))

    async def pending(name: str) -> UserBinding:
        async with asyncio.timeout(20):
            while True:
                if running.done():
                    await running
                    raise AssertionError("Operator stopped before reconciliation")
                try:
                    binding = await bindings.get(name)
                except APIError as error:
                    if error.status_code != 404:
                        raise
                else:
                    assert binding.metadata
                    status = binding.status
                    if (
                        status
                        and status.observed_generation == binding.metadata.generation
                        and any(
                            condition.type == "Synced" and condition.status == "False"
                            for condition in status.conditions
                        )
                    ):
                        return binding
                await asyncio.sleep(0.05)

    try:
        await app.wait_ready()
        first = await pending(current_key.name)
        await pending(orphan.name)
        assert first.metadata
        await asyncio.to_thread(kubectl, "delete", "userbinding", current_key.name, "--wait=true")
        repaired = await pending(current_key.name)
        assert repaired.metadata and repaired.metadata.uid != first.metadata.uid
        await asyncio.to_thread(kubectl, "delete", "user", USER_NAME, "--wait=true")
        await asyncio.to_thread(create_user)
        recreated = await users.get(USER_NAME)
        new_key = binding_keys(recreated, namespace=NAMESPACE)[0]
        assert new_key != current_key
        await pending(new_key.name)
        retained = await bindings.get(current_key.name)
        assert retained.metadata and retained.metadata.uid == repaired.metadata.uid
        unchanged = await bindings.get(unrelated.name or "")
        assert unchanged.metadata and unrelated.metadata
        assert unchanged.metadata.resource_version == unrelated.metadata.resource_version
        assert unchanged.status is None
    finally:
        stop.set()
        await asyncio.wait_for(running, timeout=15)
    assert not app.healthy
    return {
        "operatorStartupReplay": True,
        "operatorBindingRepair": True,
        "operatorUserRecreation": True,
        "operatorPendingStatus": True,
        "operatorOrphanReadinessCleared": True,
        "operatorUnrelatedBindingPreserved": True,
        "operatorCleanShutdown": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--crds", type=Path, required=True, help="The supplied opendefence_core_crds.yaml")
    parser.add_argument("--operator", action="store_true", help="Also exercise the running binding operator")
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
        report = asyncio.run(exercise(run_operator=args.operator))
    finally:
        if user_created:
            kubectl("delete", "user", USER_NAME, "--ignore-not-found", "--wait=true")
        if namespace_created:
            kubectl("delete", "namespace", NAMESPACE, "--wait=true", "--timeout=60s")
        if installed:
            kubectl("delete", "crd", *installed, "--wait=true", "--timeout=60s")
    report.update(
        coreCrdSourceSha256=hashlib.sha256(source).hexdigest(),
        cloudcoilVersion=version("cloudcoil"),
        pythonVersion=sys.version.split()[0],
        packageSourceSha256={
            module: hashlib.sha256((ROOT / "src/opendefence_integration_mediamtx" / module).read_bytes()).hexdigest()
            for module in (
                ("bindings.py", "identity.py", "operator.py") if args.operator else ("bindings.py", "identity.py")
            )
        },
        namespaceCleanup=True,
        crdCleanup=True,
        userCleanup=True,
    )
    state = ROOT / ".local/m2"
    state.mkdir(parents=True, exist_ok=True)
    result_name = "operator-results.json" if args.operator else "bindings-results.json"
    (state / result_name).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    if not __debug__:
        raise SystemExit("Assertions are required; do not use Python -O")
    main()
