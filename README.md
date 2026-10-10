# OpenDefence MediaMTX integration

This repository starts the replacement for the legacy MediaMTX integration.
It is not a running API or operator yet. The
[original implementation plan](docs/integration-mediamtx-plan.md) and
[original API draft](docs/openapi.json) are design references. See the
[implementation status](docs/implementation-status.md) for current work and evidence.

Use Python 3.14, uv and Task 3.51.1. Install Task with `mise install`, or use
the same version from the official Task distribution. Run `task sync`, then
`task check` and `task build`. Run `task --list` to see the entry points.
If mise is not active in your shell, prefix commands with `mise exec --`.
The Python package is `opendefence_integration_mediamtx`.
Run `uv run --locked prek install` to install the local checks.
Run `uv run --locked prek run --all-files` to check the whole repository.
Bandit exceptions identify test fixtures and fixed developer-tool invocations.
The audited `.secrets.baseline` contains only public source hashes in recorded
probe results. Review each new finding before adding a baseline entry; do not
regenerate it to silence unknown credentials. Known test values use inline
allowlist comments. New credentials remain blocked.

For the shared development cluster, keep a current checkout of
[opendefence/base](https://github.com/opendefence/base) at `../base` and follow
its prerequisites and kube-context instructions. This repository delegates to
the [base taskfiles](https://github.com/opendefence/base/tree/main/taskfiles):

```sh
task base:up
task base:status
```

The base `up` task starts registries, creates Kind and deploys the base operators.
Use `BASE_DIR=/path/to/base` for another checkout location. Pass base variables
after `--`, for example `task base:up -- CONTAINER_RUNTIME=podman`.
`task base:down` deletes that development cluster and keeps its registry data.
These tasks use the base checkout's workflow; update an older checkout to obtain
the current operator deployment steps. Run cluster lifecycle commands serially.

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
and operator remain pending their shared contracts.
Core owns user mTLS authentication. The integration's header parser consumes
`X-OpenDefence-User-UUID` by default, with a configurable name. See
[Core boundary](docs/m1-contracts.md#identity-and-policy-boundary) for duplicate
header handling and the supplied UserBinding schema.
The [M2 binding adapter](docs/m2-bindings.md) implements atomic binding creation
and guarded status writes, with an explicit live CRD probe. Core effective media
policy and the production API/operator processes remain separate work.
