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
        pod = deployment["spec"]["template"]["spec"]
        container = pod["containers"][0]
        assert container["image"] == image
        assert pod["volumes"] == [{"name": "runtime-tmp", "emptyDir": {"medium": "Memory", "sizeLimit": "16Mi"}}]
        assert container["volumeMounts"] == [
            {"name": "runtime-tmp", "mountPath": "/tmp"}  # nosec B108 # Pod mount, not a host path.
        ]
        assert container["env"] == [
            {"name": "CLOUDCOIL_NAMESPACE", "valueFrom": {"fieldRef": {"fieldPath": "metadata.namespace"}}}
        ]


def test_media_network_policy_keeps_control_private_and_matches_protocol_ports() -> None:
    package = yaml.safe_load((ROOT / "zarf.yaml").read_text())
    component = next(item for item in package["components"] if item["name"] == "media-networking")
    assert component["required"] is True
    template = (ROOT / component["manifests"][0]["files"][0]).read_text()
    for values_file in ("values/values.yaml", "values/local-dev.yaml"):
        namespace = yaml.safe_load((ROOT / values_file).read_text())["namespace"]
        policies = list(yaml.safe_load_all(template.replace(NAMESPACE_TEMPLATE, namespace)))
        assert {policy["metadata"]["namespace"] for policy in policies} == {namespace}
        operator, media = policies
        assert operator["spec"]["podSelector"]["matchLabels"] == {"app.kubernetes.io/name": "mediamtx-operator"}
        assert operator["spec"]["ingress"] == []
        assert media["spec"]["podSelector"]["matchLabels"] == {"app.kubernetes.io/name": "mediamtx"}
        public, control = media["spec"]["ingress"]
        assert public["from"] == [
            {
                "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "traefik-system"}},
                "podSelector": {"matchLabels": {"app.kubernetes.io/name": "traefik"}},
            }
        ]
        assert {(port["protocol"], port["port"]) for port in public["ports"]} == {
            ("TCP", 8888),
            ("TCP", 8889),
            ("TCP", 8322),
            ("TCP", 1936),
            ("UDP", 8189),
            ("UDP", 8890),
        }
        assert control["from"] == [{"podSelector": {"matchLabels": {"app.kubernetes.io/name": "mediamtx-operator"}}}]
        assert control["ports"] == [{"protocol": "TCP", "port": 9997}]
