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
            "PACKAGE_TAGS": "0.1.0-pr42-20261011T1600\n0.1.0-pr42",
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
