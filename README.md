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
Core owns user mTLS authentication. The integration's header parser consumes
`X-OpenDefence-User-UUID` by default, with a configurable name. See
[Core boundary](docs/m1-contracts.md#identity-and-policy-boundary) for duplicate
header handling and the supplied UserBinding schema.
The [M2 binding adapter](docs/m2-bindings.md) implements atomic binding creation
and guarded status writes, with an explicit live CRD probe. Core effective media
policy and the public API remain separate work. The [M2 binding operator](docs/m2-operator.md)
runs these observations with `task operator:run`. Provisioning stays incomplete
until its Core policy and MediaMTX configuration contracts are implemented.
