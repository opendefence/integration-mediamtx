"""Exercise the publishing shell without a registry or write credentials."""

import os
import subprocess  # nosec B404 # Executes the reviewed workflow shell with a fake Zarf binary.
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("case", ["complete", "missing-architecture", "sign-failure", "publish-failure"])
def test_publish_requires_both_architectures_and_stops_on_failure(tmp_path: Path, case: str) -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/check.yml").read_text())
    script = workflow["jobs"]["zarf-publish"]["steps"][-1]["run"]
    for arch in ("amd64", "arm64"):
        if arch == "arm64" and case == "missing-architecture":
            continue
        archive = tmp_path / f"packages/zarf-package-{arch}/zarf-package-integration-mediamtx-{arch}-preview.tar.zst"
        archive.parent.mkdir(parents=True)
        archive.touch()
    binary = tmp_path / "zarf"
    binary.write_text(
        '#!/bin/bash\nprintf "%s\\n" "$*" >> "$PUBLISH_LOG"\nif [[ "$2-failure" == "$FAIL_CASE" ]]; then exit 1; fi\n'
    )
    binary.chmod(0o700)
    log, summary = tmp_path / "published", tmp_path / "summary"
    result = subprocess.run(  # nosec B603 B607 # Fixed Bash invocation; no network or registry credentials.
        ["bash", "-euo", "pipefail", "-c", script],
        cwd=tmp_path,
        env=os.environ
        | {
            "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
            "IMAGE_TAGS": (
                "ghcr.io/opendefence/integration-mediamtx-operator:0.1.0-pr42-20261011T1600\n"
                "ghcr.io/opendefence/integration-mediamtx-operator:0.1.0-pr42"
            ),
            "GITHUB_STEP_SUMMARY": str(summary),
            "PUBLISH_LOG": str(log),
            "FAIL_CASE": case,
        },
        capture_output=True,
        check=False,
        timeout=10,
    )
    commands: list[str] = log.read_text().splitlines() if log.exists() else []
    if case != "complete":
        assert result.returncode != 0
        assert len(commands) == {"missing-architecture": 0, "sign-failure": 1, "publish-failure": 3}[case]
        assert not summary.exists()
        return
    assert result.returncode == 0
    assert len(commands) == 6
    assert all(
        command.startswith("package sign ") and command.endswith("--keyless --confirm") for command in commands[:2]
    )
    published = commands[2:]
    for index, tag in enumerate(("0.1.0-pr42-20261011T1600", "0.1.0-pr42")):
        assert f"--tag {tag} --confirm" in published[index * 2]
        assert "-amd64-" in published[index * 2] and "-arm64-" in published[index * 2 + 1]
    assert summary.read_text().count("ghcr.io/opendefence/packages/integration-mediamtx:") == 2


@pytest.mark.parametrize("case", ["valid", "missing", "invalid", "failure"])
def test_resolve_image_requires_a_digest_from_the_run_specific_tag(tmp_path: Path, case: str) -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/check.yml").read_text())
    script = workflow["jobs"]["image"]["steps"][-1]["run"]
    digest = "sha256:" + "a" * 64
    binary = tmp_path / "docker"
    binary.write_text(
        '#!/bin/bash\nprintf "%s\\n" "$*" > "$INSPECT_LOG"\n'
        'if [[ "$CASE" == failure ]]; then exit 1; fi\n'
        'if [[ "$CASE" != missing ]]; then printf "%s\\n" "$DIGEST"; fi\n'
    )
    binary.chmod(0o700)
    output, log = tmp_path / "output", tmp_path / "inspected"
    result = subprocess.run(  # nosec B603 B607 # Fixed shell, fake Docker; no registry request.
        ["bash", "-euo", "pipefail", "-c", script],
        cwd=tmp_path,
        env=os.environ
        | {
            "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
            "IMAGE_NAME": "opendefence/integration-mediamtx-operator",
            "PACKAGE_VERSION": "0.1.0-261011-123.1",
            "GITHUB_OUTPUT": str(output),
            "INSPECT_LOG": str(log),
            "CASE": case,
            "DIGEST": "latest" if case == "invalid" else digest,
        },
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert "inspect ghcr.io/opendefence/integration-mediamtx-operator:0.1.0-261011-123.1 " in log.read_text()
    if case == "valid":
        assert result.returncode == 0
        assert output.read_text() == f"reference=ghcr.io/opendefence/integration-mediamtx-operator@{digest}\n"
    else:
        assert result.returncode != 0
        assert not output.exists()
