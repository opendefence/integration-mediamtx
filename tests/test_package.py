"""Keep the packaged image and namespace settings aligned with the operator overlay."""

import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
NAMESPACE_TEMPLATE = "{{ .Values.namespace }}"


def test_zarf_package_matches_the_operator_overlay() -> None:
    package = yaml.safe_load((ROOT / "zarf.yaml").read_text())
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    image = f"zarf.internal/opendefence/integration-mediamtx:{project['project']['version']}"
    assert package["metadata"]["version"] == project["project"]["version"]
    assert package["components"][0]["imageArchives"][0]["images"] == [image]
    template = (ROOT / package["components"][0]["manifests"][0]["files"][0]).read_text()
    for values_file in ("values/values.yaml", "values/local-dev.yaml"):
        namespace = yaml.safe_load((ROOT / values_file).read_text())["namespace"]
        documents = list(yaml.safe_load_all(template.replace(NAMESPACE_TEMPLATE, namespace)))
        assert all(
            document["metadata"]["namespace"] == namespace
            for document in documents
            if document["kind"] not in {"ClusterRole", "ClusterRoleBinding"}
        )
        binding = next(document for document in documents if document["kind"] == "ClusterRoleBinding")
        assert binding["subjects"][0]["namespace"] == namespace
        deployment = next(document for document in documents if document["kind"] == "Deployment")
        container = deployment["spec"]["template"]["spec"]["containers"][0]
        assert container["image"] == image
        assert container["env"] == [
            {"name": "CLOUDCOIL_NAMESPACE", "valueFrom": {"fieldRef": {"fieldPath": "metadata.namespace"}}}
        ]
