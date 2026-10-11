# OpenDefence MediaMTX integration

This repository starts the replacement for the legacy MediaMTX integration.
It includes policy adapters, the `mediamtx-operator` binding observer, and a
packaged MediaMTX server. User authorization and stream provisioning remain pending. The
[original implementation plan](docs/integration-mediamtx-plan.md) and
[original API draft](docs/openapi.json) are design references. See the
[implementation status](docs/implementation-status.md) for current work and evidence.

`mediamtx-operator` reads Kubernetes User CRD state. It does not call or require
`core-operator` at runtime. Tests can supply projected User roles and group
memberships directly in CRD status. Media authorization still needs an agreed
effective-role projection schema and the public API implementation.

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
task base:up BASE_PACKAGE=/absolute/path/to/zarf-package-base-arm64.tar.zst
task base:status
```

`base:up` starts registries, creates Kind and deploys the base components from
the selected package. Alternatively, set `BASE_VERSION=<published-version>`;
the package reference defaults to `oci://ghcr.io/opendefence/base:<version>`.
`base:up` selects base's local certificate authority (CA) mode by default.
Base then creates `public-issuer` without an external ACME challenge. Set
`BASE_ISSUER=acme` only when the cluster can pass that challenge. Direct
`base-package:install` calls use the base package default unless you set
`BASE_ISSUER=ca`.
The local development overlay uses `local-dev.opendefence.fi` as its certificate
name. That name resolves to `127.0.0.1` for local testing.
To trust local media certificates in a client, export the base root certificate:

```sh
mkdir -p .local
task base-package:export-ca > .local/public-root-ca.pem
```

Pass overrides directly, for example `CONTAINER_RUNTIME=podman` or
`CLUSTER_NAME=my-dev`. Base package commands and `package:deploy:local` require
the current kubectl context to match `KUBE_CONTEXT` (default
`kind-<CLUSTER_NAME>`). Switch it explicitly when reusing an existing cluster.
`base-package:install`, `base-package:remove` and
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
scoped admission checks with fresh Core identity and Role inputs. The public API
and stream provisioning remain pending their shared contracts.
The [Core User projection handoff](docs/core-media-policy-handoff.md) lists the
Core identity and effective Role data that this integration needs. This
integration defines MediaMTX Role meanings and access rules.
Current media paths use `live/{tool}/{callsign}`. The original plan and API draft
retain the earlier UUID-path proposal as historical design text.
MediaMTX `api`, `metrics`, and `pprof` actions are reserved for current Core
`superadmin` Users and this integration's own service identity. See the
[control-action boundary](docs/core-media-policy-handoff.md#mediamtx-role-meanings-owned-by-this-integration).
Core owns User mutual Transport Layer Security (mTLS) authentication. Traefik
ends mTLS and sends a verified User UUID to the REST API. The integration's
header parser consumes `X-OpenDefence-User-UUID` by default, with a configurable
name. See the [Core boundary](docs/m1-contracts.md#identity-and-policy-boundary) for duplicate
header handling and the supplied UserBinding schema.
The integration does not read User certificate data. MediaMTX will check
integration-issued passwords for media streams when grant issuance is connected.
Integration workloads do not use service Users or UserBindings.
The [M2 binding adapter](docs/m2-bindings.md) implements atomic binding creation
and guarded status writes, with an explicit live CRD probe. Core's effective
Role projection and the public API remain separate work. The
[`mediamtx-operator`](docs/m2-operator.md) runs these observations with
`task operator:run`. Provisioning stays incomplete until Core's Role
projection and MediaMTX configuration are implemented.
The [kubectl test](docs/m2-operator.md#test-with-kubectl-without-core-operator)
creates a disposable, unapproved User and changes its projected roles and groups
without running `core-operator`. An approved User stays as a permanent record
after revocation; do not delete it.
The [M2 session adapter](docs/m2-sessions.md) can remove connections by grant
username after denial is persisted; it is not connected to a public API yet.
The [M2 reservation adapter](docs/m2-reservations.md) stores bounded grant
reservations in Kubernetes Secrets. It is not connected to issuance yet.
The [M2 grant record adapter](docs/m2-grants.md) stores a reserved media grant,
persists revocation, drains supplied MediaMTX instances before releasing active
quota, and removes retained records after their retry window. It is not
connected to issuance or `mediamtx-operator` yet.

## Zarf package

`zarf.yaml` packages `mediamtx-operator` and MediaMTX 1.21.2. It builds the
`mediamtx-operator` image locally. It includes the MediaMTX image in the offline package.
Base, Core and Core's shared CRDs must be installed first. Create
a dedicated namespace before deploying; this package leaves namespace lifecycle
with the cluster owner so removing it cannot delete unrelated objects.
The package installs a MediaMTX Deployment, ClusterIP Service, configuration,
and a certificate from base's `public-issuer`. The media configuration has no
users. It denies all stream and control requests until an authorization service
is ready. The control API, metrics, and profiling listeners are disabled.
The local development overlay uses the CA-backed `public-issuer` from base.
This package does not configure the issuer.

The package also installs ingress `NetworkPolicy` rules. They select `mediamtx-operator`
with no allowed Pod ingress and allow Traefik Pods in `traefik-system` to reach
MediaMTX's HLS, WebRTC signaling, RTSPS, RTMPS, SRT, WebRTC ICE, and MoQ ports. The
`mediamtx-operator` Pod may reach MediaMTX's private control API on port 9997
when that API is enabled. Other NetworkPolicies can add permissions. The MediaMTX Pod uses
the `app.kubernetes.io/name: mediamtx` label and the pinned
[MediaMTX 1.21.2 ports](https://github.com/bluenviron/mediamtx/blob/v1.21.2/mediamtx.yml)
for these rules to apply. RTSPS, RTMPS, and MoQ use the issued certificate.
RTSPS and RTMPS use strict encryption. RTSPS uses TCP transport.
The current base Traefik chart exposes only
HTTP/HTTPS. Public routes and native TCP/UDP entrypoints remain deployment work.
NetworkPolicy enforcement must be
verified with the cluster's network plugin before relying on the rules.
Plain RTSP and RTMP remain disabled. MoQ uses Basic username and password
credentials in its [authorization token](https://github.com/bluenviron/mediamtx/blob/v1.21.2/internal/servers/moq/session.go).
MoQ grant issuance is pending because MediaMTX 1.21.2 does not include
usernames in its [MoQ session list](https://github.com/bluenviron/mediamtx/blob/v1.21.2/internal/defs/api_moq.go).
The current grant cleanup needs usernames to close sessions after revocation.

Deployment settings use Zarf package values, following Core's overlay names:
`values/values.yaml` is the production default (`integration-mediamtx`) and
`values/local-dev.yaml` selects `integration-mediamtx-dev` for local development.
The `namespace` value selects the dedicated namespace for both workloads.
The `domain` value sets the media certificate name and WebRTC host. Set it to a
real host before production deployment. The production default
`opendefence.invalid` cannot receive a certificate.
For local testing, keep `domain: local-dev.opendefence.fi` from
`values/local-dev.yaml`.
The Pod reads `CLOUDCOIL_NAMESPACE` from its own namespace through Kubernetes;
no separate Pod environment setting is needed. For a standalone install, give
Zarf a values file with both `namespace` and `domain`.
`KUBECONFIG` selects the administrator's deployment context, not Pod configuration.
There are no other `mediamtx-operator` application environment settings yet.
Add future settings to the Zarf values, schema and manifest template when they appear.

Install Zarf 0.87.0 and run `task package:check` to lint and render both
overlays. `task package:render` regenerates the `mediamtx-operator` manifest after its
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
The build creates an ignored `mediamtx-operator` OCI image archive in `.local/`. Zarf pulls
the pinned MediaMTX image while it creates the package.
For the local Kind cluster, select its Kubernetes context. Create the namespace
specified in `values/local-dev.yaml`. Then deploy with:

```sh
kubectl create namespace integration-mediamtx-dev
task package:deploy:local PACKAGE_FILE=dist/zarf-package-integration-mediamtx-arm64-0.1.0.tar.zst
```

This task loads the built `mediamtx-operator` image into Kind before it deploys
the package in Zarf connected mode. For a Zarf-initialized cluster, use `task package:deploy`
instead. That task uses `values/values.yaml` by default. Supply a deployment
values file with `VALUES_FILE`, and set both `namespace` and `domain` in that
file. Create that namespace before deployment.
The package has not been deployed to a production cluster. Its media server
rejects access until the public API and authorization service are connected.
