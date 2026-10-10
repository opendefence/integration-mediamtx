"""Check the draft's authentication boundary without claiming a running API."""

import json
from importlib import import_module
from pathlib import Path

from odintegration_mediamtx.identity import DEFAULT_USER_UUID_HEADER


def test_package_import() -> None:
    assert import_module("odintegration_mediamtx").__doc__


def test_draft_separates_public_api_and_private_callback() -> None:
    contract = json.loads((Path(__file__).parents[1] / "openapi.json").read_text())
    assert contract["openapi"] == "3.1.0"
    assert contract["security"] == [{"ClientCertificate": []}]
    assert contract["x-core-identity-header"]["default"] == DEFAULT_USER_UUID_HEADER
    assert contract["x-core-identity-header"]["authenticationOwner"] == "opendefence/core"
    callback = contract["paths"]["/internal/mediamtx/auth"]
    assert callback["servers"][0]["url"].startswith("https://")
    assert callback["x-internal"] is True
    assert callback["post"]["security"] == []
    assert callback["post"]["x-caller-boundary"]["publicIngress"] is False
    for path, resource in contract["paths"].items():
        if path.startswith("/internal/"):
            continue
        for method in ("get", "post", "delete"):
            if method in resource:
                assert resource[method].get("security", contract["security"]) == contract["security"]
