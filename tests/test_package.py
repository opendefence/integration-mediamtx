"""Keep packaged workloads, image references, and namespaces aligned."""

import tomllib
from pathlib import Path

import pytest
import yaml
from lib_opendefence_core.models.v1alpha1 import Integration

ROOT = Path(__file__).resolve().parents[1]
NAMESPACE_TEMPLATE = "{{ .Values.namespace }}"


def test_integration_registration_uses_the_shared_model_without_extra_roles() -> None:
    package = yaml.safe_load((ROOT / "zarf.yaml").read_text())
    component = next(item for item in package["components"] if item["name"] == "integration")
    assert component["required"] is True
    template = (ROOT / component["manifests"][0]["files"][0]).read_text()
    for values_file in ("values/values.yaml", "values/local-dev.yaml"):
        namespace = yaml.safe_load((ROOT / values_file).read_text())["namespace"]
        rendered = template.replace(NAMESPACE_TEMPLATE, namespace)
        rendered = rendered.replace("{{ .Pkg.Metadata.Version | quote }}", f'"{package["metadata"]["version"]}"')
        document = yaml.safe_load(rendered)
        registration = Integration.model_validate(document)
        assert registration.kind == "Integration" and registration.name == namespace
        assert registration.metadata and registration.metadata.namespace is None
        assert registration.status is None
        assert registration.spec.version == package["metadata"]["version"]
        assert registration.spec.extra_roles == []
        assert registration.spec.network_policy.ingress == "Public"
        assert registration.spec.network_policy.egress == "Internet"
        assert registration.spec.product_info and registration.spec.product_info.component is None


def test_zarf_package_matches_the_operator_overlay() -> None:
    package = yaml.safe_load((ROOT / "zarf.yaml").read_text())
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    bump = tomllib.loads((ROOT / ".bumpversion.toml").read_text())
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    locked = next(item for item in lock["package"] if item["name"] == "opendefence-integration-mediamtx")
    assert project["project"]["version"] == bump["tool"]["bumpversion"]["current_version"] == locked["version"]
    version = project["project"]["version"].replace("+", "-")
    image = f"zarf.internal/opendefence/integration-mediamtx:{version}"
    assert package["metadata"]["version"] == version
    assert package["constants"] == [{"name": "OPERATOR_IMAGE", "value": image}]
    component = next(item for item in package["components"] if item["name"] == "operator")
    assert component["imageArchives"][0]["images"] == [image]
    template = (ROOT / component["manifests"][0]["files"][0]).read_text()
    for values_file in ("values/values.yaml", "values/local-dev.yaml"):
        values = yaml.safe_load((ROOT / values_file).read_text())
        namespace = values["namespace"]
        rendered = template.replace(NAMESPACE_TEMPLATE, namespace)
        rendered = rendered.replace("{{ .Constants.OPERATOR_IMAGE }}", image)
        for key, value in values.items():
            rendered = rendered.replace("{{ .Values." + key + " }}", value)
        documents = list(yaml.safe_load_all(rendered))
        assert all(document["kind"] != "CustomResourceDefinition" for document in documents)
        assert all(
            document["metadata"]["namespace"] == namespace
            for document in documents
            if document["kind"] not in {"ClusterRole", "ClusterRoleBinding"}
        )
        binding = next(document for document in documents if document["kind"] == "ClusterRoleBinding")
        assert binding["subjects"][0]["namespace"] == namespace
        deployment = next(document for document in documents if document["kind"] == "Deployment")
        assert deployment["spec"]["replicas"] == 1
        assert deployment["spec"]["strategy"] == {
            "type": "RollingUpdate",
            "rollingUpdate": {"maxSurge": 0, "maxUnavailable": 1},
        }
        pod = deployment["spec"]["template"]["spec"]
        container = pod["containers"][0]
        assert container["image"] == image
        assert pod["volumes"] == [
            {"name": "runtime-tmp", "emptyDir": {"medium": "Memory", "sizeLimit": "16Mi"}},
            {"name": "auth-tls", "secret": {"secretName": "mediamtx-auth-tls"}},  # pragma: allowlist secret
            {
                "name": "control-ca",
                "secret": {
                    "secretName": "mediamtx-control-tls",  # pragma: allowlist secret
                    "items": [{"key": "ca.crt", "path": "ca.crt"}],
                },
            },
            {
                "name": "tak-admin",
                "secret": {
                    "secretName": "mediamtx-tak-admin",  # pragma: allowlist secret
                    "optional": True,
                    "defaultMode": 288,
                    "items": [{"key": key, "path": key} for key in ("ca.crt", "tls.crt", "tls.key")],
                },
            },
        ]
        assert container["volumeMounts"] == [
            {"name": "runtime-tmp", "mountPath": "/tmp"},  # nosec B108 # Pod mount, not a host path.
            {"name": "control-ca", "mountPath": "/var/run/mediamtx-control", "readOnly": True},
            {"name": "tak-admin", "mountPath": "/var/run/tak", "readOnly": True},
        ]
        assert container["env"] == [
            {"name": "CLOUDCOIL_NAMESPACE", "valueFrom": {"fieldRef": {"fieldPath": "metadata.namespace"}}},
            {"name": "TAK_URL", "value": values["takUrl"]},
            {"name": "TAK_SERVER_NAME", "value": values["takServerName"]},
            {"name": "MEDIA_RTSPS_URL", "value": f"rtsps://{values['domain']}:8322"},
        ]
        auth = pod["containers"][1]
        assert auth["command"] == ["mediamtx-auth"] and auth["image"] == image
        assert auth["env"] == container["env"][:1]
        assert "tak-admin" not in {mount["name"] for mount in auth["volumeMounts"]}
        assert pod["securityContext"]["fsGroup"] == 65532
        assert {"name": "runtime-tmp", "mountPath": "/tmp"} in auth["volumeMounts"]  # nosec B108
        assert auth["args"] == [  # nosec B104 # Pod listener fixture.
            "--host",
            "0.0.0.0",
            "--tls-cert",
            "/tls/tls.crt",
            "--tls-key",
            "/tls/tls.key",
        ]


@pytest.mark.parametrize("published", [False, True])
def test_build_image_and_version_reach_both_containers_and_registration(published: bool) -> None:
    version = "0.1.0-261011-123.1"
    image = (
        "ghcr.io/opendefence/integration-mediamtx-operator@sha256:" + "a" * 64
        if published
        else f"zarf.internal/opendefence/integration-mediamtx:{version}"
    )
    operator = (ROOT / "manifests/operator/operator.yaml.tmpl").read_text()
    rendered = operator.replace(NAMESPACE_TEMPLATE, "integration-mediamtx-dev")
    rendered = rendered.replace("{{ .Constants.OPERATOR_IMAGE }}", image)
    deployment = next(document for document in yaml.safe_load_all(rendered) if document["kind"] == "Deployment")
    images = {container["image"] for container in deployment["spec"]["template"]["spec"]["containers"]}
    assert images == {image}
    integration = (ROOT / "manifests/integration/integration.yaml.tmpl").read_text()
    rendered = integration.replace(NAMESPACE_TEMPLATE, "integration-mediamtx-dev")
    rendered = rendered.replace("{{ .Pkg.Metadata.Version | quote }}", f'"{version}"')
    assert Integration.model_validate(yaml.safe_load(rendered)).spec.version == version


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
        assert operator["spec"]["ingress"] == [
            {
                "from": [{"podSelector": {"matchLabels": {"app.kubernetes.io/name": "mediamtx"}}}],
                "ports": [{"protocol": "TCP", "port": 9443}],
            }
        ]
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
            ("TCP", 8892),
            ("UDP", 8892),
            ("UDP", 8893),
        }
        assert control["from"] == [{"podSelector": {"matchLabels": {"app.kubernetes.io/name": "mediamtx-operator"}}}]
        assert control["ports"] == [{"protocol": "TCP", "port": 9997}]


def test_media_component_bundles_a_fail_closed_server_in_the_selected_namespace() -> None:
    package = yaml.safe_load((ROOT / "zarf.yaml").read_text())
    component = next(item for item in package["components"] if item["name"] == "media")
    image = (
        "docker.io/bluenviron/mediamtx:1.21.2@sha256:c7540465f868a02652118bea5a0daab12a29ac0f6cb8485abd535939ecddf886"
    )
    assert component["required"] is True
    assert component["images"] == [image]
    template = (ROOT / component["manifests"][0]["files"][0]).read_text()
    for values_file in ("values/values.yaml", "values/local-dev.yaml"):
        values = yaml.safe_load((ROOT / values_file).read_text())
        rendered = template.replace(NAMESPACE_TEMPLATE, values["namespace"])
        rendered = rendered.replace("{{ .Values.domain | quote }}", f'"{values["domain"]}"')
        documents = {item["kind"]: item for item in yaml.safe_load_all(rendered)}
        assert set(documents) == {"Certificate", "ConfigMap", "Deployment", "Service"}
        assert {item["metadata"]["namespace"] for item in documents.values()} == {values["namespace"]}
        assert documents["Certificate"]["spec"]["dnsNames"] == [values["domain"]]
        config = yaml.safe_load(documents["ConfigMap"]["data"]["mediamtx.yml"])
        assert config["authInternalUsers"] == []
        assert config["authMethod"] == "http" and config["authHTTPExclude"] == []
        assert (
            config["authHTTPAddress"] == f"https://mediamtx-auth.{values['namespace']}.svc:9443/internal/mediamtx/auth"
        )
        assert config["api"] is True and config["apiEncryption"] is True
        assert config["apiServerKey"] == "/control-tls/tls.key"
        assert config["apiServerCert"] == "/control-tls/tls.crt"
        assert config["metrics"] is False and config["pprof"] is False
        assert config["moq"] is True
        assert config["moqServerKey"] == "/tls/tls.key"
        assert config["moqServerCert"] == "/tls/tls.crt"
        assert config["rtspEncryption"] == config["rtmpEncryption"] == "strict"
        deployment = documents["Deployment"]["spec"]["template"]
        assert deployment["metadata"]["labels"] == {"app.kubernetes.io/name": "mediamtx"}
        assert deployment["spec"]["containers"][0]["image"] == image
        assert deployment["spec"]["containers"][0]["command"] == ["/mediamtx", "/config/mediamtx.yml"]
        assert deployment["spec"]["containers"][0]["env"] == [{"name": "SSL_CERT_FILE", "value": "/auth-ca/ca.crt"}]
        ca = next(volume for volume in deployment["spec"]["volumes"] if volume["name"] == "auth-ca")
        assert ca["secret"]["items"] == [{"key": "tls.crt", "path": "ca.crt"}]
        assert documents["Service"]["spec"]["selector"] == deployment["metadata"]["labels"]
        service_ports = documents["Service"]["spec"]["ports"]
        assert {(port["protocol"], port["port"]) for port in service_ports} == {
            ("TCP", 9997),
            ("TCP", 8888),
            ("TCP", 8889),
            ("TCP", 8322),
            ("TCP", 1936),
            ("UDP", 8189),
            ("UDP", 8890),
            ("TCP", 8892),
            ("UDP", 8892),
            ("UDP", 8893),
        }


def test_callback_certificate_covers_the_private_service_in_each_overlay() -> None:
    template = (ROOT / "manifests/auth/auth.yaml.tmpl").read_text()
    for values_file in ("values/values.yaml", "values/local-dev.yaml"):
        namespace = yaml.safe_load((ROOT / values_file).read_text())["namespace"]
        documents = list(yaml.safe_load_all(template.replace(NAMESPACE_TEMPLATE, namespace)))
        assert {item["metadata"]["namespace"] for item in documents} == {namespace}
        certificates = {item["metadata"]["name"]: item for item in documents if item["kind"] == "Certificate"}
        assert certificates["mediamtx-auth-ca"]["spec"]["isCA"] is True
        tls = certificates["mediamtx-auth-tls"]["spec"]
        assert tls["dnsNames"] == [f"mediamtx-auth.{namespace}.svc"]
        assert tls["issuerRef"]["name"] == "mediamtx-auth-ca"
        control = certificates["mediamtx-control-tls"]["spec"]
        assert control["dnsNames"] == [f"mediamtx.{namespace}.svc"]
        assert control["issuerRef"]["name"] == "mediamtx-auth-ca"
        service = next(item for item in documents if item["kind"] == "Service")
        assert service["spec"]["selector"] == {"app.kubernetes.io/name": "mediamtx-operator"}
        assert service["spec"]["ports"] == [{"name": "https", "port": 9443, "targetPort": "auth"}]
