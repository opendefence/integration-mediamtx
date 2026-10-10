# OpenDefence MediaMTX integration

This repository starts the replacement for the legacy MediaMTX integration.
It is not a running API or operator yet. Read the
[implementation plan](integration-mediamtx-plan.md) and the
[draft API contract](openapi.json).

Use Python 3.14 and uv. Run `make sync`, then `make check` and `make build`.
Run `uv run --locked prek install` to install the local checks.

For protocol tests, install Kind v0.33.0 and start Podman. Run `make kind-up`.
The script creates a separate cluster for this checkout. It stores the kubeconfig
under `.local/kind/` and prints the explicit context. It does not change your
default kubeconfig. Run `make kind-load ARCHIVE=/path/to/image.tar` to load a
Podman image archive. Use `imagePullPolicy: Never` in offline test workloads.
Run `make kind-down` to delete only the cluster owned by this checkout.
After failed creation, use the same cleanup command before retrying.
Run cluster commands one at a time.
See the [Kind rootless requirements](https://kind.sigs.k8s.io/docs/user/rootless/)
before testing UDP traffic. No application workload is installed by these tasks.

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
