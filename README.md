# OpenDefence MediaMTX integration

This repository starts the replacement for the legacy MediaMTX integration.
It includes policy adapters and a binding observation operator. The public API
and MediaMTX provisioning remain pending. The
[original implementation plan](docs/integration-mediamtx-plan.md) and
[original API draft](docs/openapi.json) are design references. See the
[implementation status](docs/implementation-status.md) for current work and evidence.

Use Python 3.14, uv and Task 3.54.0. Install Task with `mise install`, or use
the same version from the official Task distribution. Run `task sync`, then
`task check` and `task build`. Run `task --list` to see the entry points.
If mise is not active in your shell, prefix commands with `mise exec --`.
The Python package is `opendefence_integration_mediamtx`.
Its Core resource models come from `lib-opendefence-core` on the configured
[pypilocal index](https://nexus.dev.pvarki.fi/repository/pypilocal/).
Use that index when installing a built wheel outside this uv project.
Run `uv run --locked prek install` to install the local checks.
Run `uv run --locked prek run --all-files` to check the whole repository.
Bandit exceptions identify test fixtures and fixed developer-tool invocations.
The audited `.secrets.baseline` contains only public source hashes in recorded
probe results. Review each new finding before adding a baseline entry; do not
regenerate it to silence unknown credentials. Known test values and public
Taskfile checksums use inline allowlist comments. New credentials remain blocked.

For the shared development cluster, this repository imports the registry,
cluster and package [base taskfiles](https://github.com/opendefence/base/tree/b04ff076bc4d3ec6a2ce01074a66f10d0f09b7a6/taskfiles)
from GitHub at a pinned revision, with checked SHA-256 contents. A sibling
checkout is not required. Install Docker or Podman, Kind, kubectl, Zarf 0.87.0
and jq as described in the [base prerequisites](https://github.com/opendefence/base/blob/b04ff076bc4d3ec6a2ce01074a66f10d0f09b7a6/README.md).
Choose a published base version or an absolute path to a built package archive:

```sh
task base:up BASE_PACKAGE=/absolute/path/to/zarf-package-base-arm64.tar.zst BASE_ISSUER=ca
task base:status
```

`base:up` starts registries, creates Kind and deploys the base operators from
the selected package. Alternatively, set `BASE_VERSION=<published-version>`;
the package reference defaults to `oci://ghcr.io/opendefence/base:<version>`.
Use `BASE_ISSUER=ca` for local CA mode; the package default is ACME.
Pass overrides directly, for example `CONTAINER_RUNTIME=podman` or
`CLUSTER_NAME=my-dev`. Package commands require the current kubectl context to
match `KUBE_CONTEXT` (default `kind-<CLUSTER_NAME>`); switch it explicitly when
reusing an existing cluster. `base-package:install`, `base-package:remove` and
`base-package:export-ca` are available separately.
`task base:down` deletes that development cluster and keeps its registry data.
Run cluster lifecycle commands serially. To build or deploy unpublished base
source, run the checkout-only `build:*` tasks in `../base`.

Task downloads the pinned includes on first use, including for Python checks.
After downloading, `task --offline check` uses the local cache in `.task/`.
Pinned checksums avoid trust prompts and reject changed contents. See
[Task remote includes](https://taskfile.dev/docs/remote-taskfiles#pin-reviewed-contents).

For the isolated protocol probes, install Kind v0.33.0 and start Podman.
Run `task kind:up`.
The script creates a separate cluster for this checkout. It stores the kubeconfig
under `.local/kind/` and prints the explicit context. It does not change your
default kubeconfig. Run `task kind:load ARCHIVE=/path/to/image.tar` to load a
Podman image archive. Use `imagePullPolicy: Never` in offline test workloads.
Run `task kind:down` to delete only the cluster owned by this checkout.
After failed creation, use the same cleanup command before retrying.
Run cluster commands one at a time.
See the [Kind rootless requirements](https://kind.sigs.k8s.io/docs/user/rootless/)
before testing UDP traffic. The isolated Kind lifecycle tasks install no application workload.

TAK profiles and integration with the sibling TAK repositories are deferred until
their current work is complete. Do not advertise TAK support yet.

See the [decision record](docs/decisions/0001-foundation.md) and the
[implementation status](docs/implementation-status.md) for scope and test evidence.
The [M1 contracts](docs/m1-contracts.md), [protocol findings](docs/m1-findings.md)
and [reproducible spike](spikes/m1/README.md) record the first integration checks
and the remaining Core and routing gates.
The [M2 policy implementation](docs/m2-policy.md) adds canonical stream paths and
scoped admission checks with explicit fresh Core policy inputs. The public API
and MediaMTX provisioning remain pending their shared contracts.
The [Core media-policy handoff](docs/core-media-policy-handoff.md) lists the
Core decisions and acceptance cases that this integration needs.
Core owns user mTLS authentication. The integration's header parser consumes
`X-OpenDefence-User-UUID` by default, with a configurable name. See
[Core boundary](docs/m1-contracts.md#identity-and-policy-boundary) for duplicate
header handling and the supplied UserBinding schema.
The [M2 binding adapter](docs/m2-bindings.md) implements atomic binding creation
and guarded status writes, with an explicit live CRD probe. Core effective media
policy and the public API remain separate work. The [M2 binding operator](docs/m2-operator.md)
runs these observations with `task operator:run`. Provisioning stays incomplete
until its Core policy and MediaMTX configuration contracts are implemented.
The [M2 session adapter](docs/m2-sessions.md) can remove connections by grant
username after denial is persisted; it is not connected to a public API yet.
The [M2 reservation adapter](docs/m2-reservations.md) stores bounded grant
reservations in Kubernetes Secrets. It is not connected to issuance yet.

## Zarf package

`zarf.yaml` packages the current binding observation operator and its local OCI
image archive. Base, Core and Core's shared CRDs must be installed first. Create
a dedicated namespace before deploying; this package leaves namespace lifecycle
with the cluster owner so removing it cannot delete unrelated objects.
The package also installs ingress `NetworkPolicy` rules. They select the operator
with no allowed Pod ingress and allow Traefik Pods in `traefik-system` to reach
MediaMTX's HLS, WebRTC signaling, RTSPS, RTMPS, SRT and WebRTC ICE ports. The
operator Pod is allowed to reach MediaMTX's private control API on port 9997.
Other NetworkPolicies can add permissions. Future MediaMTX Pods must use
the `app.kubernetes.io/name: mediamtx` label and the pinned
[MediaMTX 1.21.2 ports](https://github.com/bluenviron/mediamtx/blob/v1.21.2/mediamtx.yml)
for these rules to apply. RTSPS and RTMPS need strict encryption, and RTSPS
uses TCP transport in this policy. These
policies create no public listeners. The current base Traefik chart exposes only
HTTP/HTTPS, so native TCP/UDP entrypoints, media Services and the authenticated
MediaMTX workload remain deployment work. NetworkPolicy enforcement must be
verified with the cluster's network plugin before relying on the rules.
Plain RTSP/RTMP and MoQ remain outside the approved integration protocol set.

Deployment settings use Zarf package values, following Core's overlay names:
`values/values.yaml` is the production default (`integration-mediamtx`) and
`values/local-dev.yaml` selects `integration-mediamtx-dev` for local development.
The `namespace` value changes the generated RBAC and Deployment namespace.
The Pod reads `CLOUDCOIL_NAMESPACE` from its own namespace through Kubernetes;
no separate Pod environment setting is needed. For a standalone install, pass a
values file or `--set-values namespace=<your-dedicated-namespace>` to Zarf.
`KUBECONFIG` selects the administrator's deployment context, not Pod configuration.
There are no other operator application environment settings yet; add future
settings to the Zarf values, schema and manifest template when they appear.

Install Zarf 0.87.0 and run `task package:check` to lint and render both
overlays. `task package:render` regenerates the operator manifest after its
controller, RBAC or Deployment overlay changes; `task check` rejects a stale
generated file. `task package:inspect` renders the local-dev overlay by default;
set `VALUES_FILE=values/values.yaml` for the production default. To build a
self-contained ARM64 package with Podman:

```sh
task package:build ARCH=arm64 CONTAINER_RUNTIME=podman
```

The archive is `dist/zarf-package-integration-mediamtx-arm64-0.1.0.tar.zst`.
For an AMD64 Docker host, omit those overrides (Docker 25 or newer is needed
for a compatible [Zarf image archive](https://docs.zarf.dev/ref/components/)).
The build creates an ignored OCI image
archive in `.local/` and packages the image without a published registry tag.
After selecting the intended Kubernetes context and creating the namespace,
deploy with:

```sh
zarf package deploy dist/zarf-package-integration-mediamtx-arm64-0.1.0.tar.zst \
  --connected --confirm --values values/local-dev.yaml
```

For production or standalone deployments, supply the appropriate values file
or set `namespace` directly. The package
has not been deployed to a production cluster. It contains the operator only;
the MediaMTX workload and public API follow when their contracts are ready.
