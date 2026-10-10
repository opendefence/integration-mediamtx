"""Exercise cluster ownership with a fake Kind binary, without a container runtime."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "checkout with spaces"
    (root / "scripts").mkdir(parents=True)
    (root / "bin").mkdir()
    shutil.copyfile(Path(__file__).parents[1] / "scripts/kind.sh", root / "scripts/kind.sh")
    binary = root / "bin/kind"
    binary.write_text(
        "#!/bin/bash\nset -eu\n"
        'printf "CALL\\n" >> "$KIND_TEST_LOG"\n'
        'printf "%s\\n" "$@" >> "$KIND_TEST_LOG"\n'
        'test "$KIND_EXPERIMENTAL_PROVIDER" = podman\n'
        'if [[ $1 == get ]]; then printf "%s\\n" "${KIND_TEST_CLUSTERS:-}"; fi\n'
        'if [[ $1 == "${KIND_TEST_FAIL:-}" ]]; then exit 1; fi\n'
    )
    binary.chmod(0o700)
    monkeypatch.setenv("PATH", f"{root / 'bin'}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("KIND_TEST_LOG", str(root / "calls"))
    return root


def run_kind(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(root / "scripts/kind.sh"), *args], text=True, capture_output=True, check=False)


def test_owned_cluster_lifecycle(checkout: Path) -> None:
    assert run_kind(checkout, "up").returncode == 0
    state = checkout / ".local/kind"
    name = (state / "owner").read_text().strip()
    calls = (checkout / "calls").read_text().split("CALL\n")[1:]
    assert calls[0].splitlines() == ["get", "clusters"]
    assert calls[1].splitlines() == [
        "create",
        "cluster",
        "--name",
        name,
        "--kubeconfig",
        str(state / "kubeconfig"),
        "--config",
        str(checkout / "deploy/kind.yaml"),
        "--wait",
        "180s",
    ]
    archive = checkout / "image with spaces.tar"
    archive.touch()
    assert run_kind(checkout, "load", str(archive)).returncode == 0
    assert (checkout / "calls").read_text().split("CALL\n")[-1].splitlines() == [
        "load",
        "image-archive",
        str(archive),
        "--name",
        name,
    ]
    assert run_kind(checkout, "down").returncode == 0
    assert (checkout / "calls").read_text().split("CALL\n")[-1].splitlines() == [
        "delete",
        "cluster",
        "--name",
        name,
        "--kubeconfig",
        str(state / "kubeconfig"),
    ]
    assert not state.exists()


@pytest.mark.parametrize("operation", ["down", "load"])
def test_refuses_unowned_cluster(checkout: Path, operation: str) -> None:
    assert run_kind(checkout, operation).returncode == 1
    assert not (checkout / "calls").exists()


def test_refuses_existing_cluster(checkout: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert run_kind(checkout, "up").returncode == 0
    state = checkout / ".local/kind"
    name = (state / "owner").read_text().strip()
    shutil.rmtree(state)
    monkeypatch.setenv("KIND_TEST_CLUSTERS", name)
    (checkout / "calls").unlink()
    assert run_kind(checkout, "up").returncode == 1
    assert (checkout / "calls").read_text().splitlines() == ["CALL", "get", "clusters"]
    assert not state.exists()


def test_failed_create_remains_owned(checkout: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KIND_TEST_FAIL", "create")
    assert run_kind(checkout, "up").returncode == 1
    assert (checkout / ".local/kind/owner").exists()
    assert run_kind(checkout, "down").returncode == 0


def test_failed_delete_preserves_ownership(checkout: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert run_kind(checkout, "up").returncode == 0
    monkeypatch.setenv("KIND_TEST_FAIL", "delete")
    assert run_kind(checkout, "down").returncode == 1
    assert (checkout / ".local/kind/owner").exists()


def test_failed_cluster_list_does_not_claim_ownership(checkout: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KIND_TEST_FAIL", "get")
    assert run_kind(checkout, "up").returncode == 1
    assert not (checkout / ".local/kind").exists()


def test_wrong_ownership_record_blocks_cleanup(checkout: Path) -> None:
    state = checkout / ".local/kind"
    state.mkdir(parents=True)
    (state / "owner").write_text("some-other-cluster\n")
    assert run_kind(checkout, "down").returncode == 1
    assert not (checkout / "calls").exists()
