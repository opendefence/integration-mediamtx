# M2 `mediamtx-operator`

`mediamtx-operator` watches cluster-scoped Core Users and integration-owned
UserBindings in one namespace. It creates missing observations with the existing atomic
binding adapter. It reads the current User from Kubernetes before creation;
cached identity only selects work. Recreated Users get separate UID-pinned
bindings. It does not change Core Users, resolve roles or issue credentials.

Provisioning remains incomplete while Core's effective Role projection and
MediaMTX configuration reconciliation are pending. `mediamtx-operator` sets only
`Synced=False` and the observed generation. It clears former readiness on owned
bindings, including orphaned bindings, without retargeting or deleting them.
Unrelated and mismatched bindings are not adopted. Deleting bindings are left
for explicit lifecycle work. There is no finalizer or credential cleanup yet.

User changes and binding changes enqueue reconciliation. Startup replays both
resource lists; successful passes schedule another observation after 60 seconds.
Core plans to write effective Role and Group changes into the User object. A
status-only User update maps to the same binding key. The current shared User
model has only direct Roles, so `mediamtx-operator` still reports provisioning as
pending after that event.
Conflicts and dependency failures propagate to Cloudcoil's retry queue. Each
attempt reads a new binding before its UID/resource-version guarded status
write. An unchanged observation preserves transition times and makes no write.
This repairs observation status; it does not prove fresh authorization or end
existing media sessions.

## Run and generate manifests

Install the locked environment with `task sync`. The namespace and Core's shared
User/UserBinding CRDs must already exist. `mediamtx-operator` uses the current context
in a single `KUBECONFIG` file, or the Pod's ServiceAccount in a cluster:

```sh
export CLOUDCOIL_NAMESPACE=integration-mediamtx
export KUBECONFIG=/absolute/path/to/kubeconfig
task operator:run
```

The equivalent command is `uv run --locked mediamtx-operator run`. SIGINT and
SIGTERM stop the application. Cloudcoil owns process signals, watches, retries
and application-created transports. A caller-supplied Config stays caller-owned.
The namespace defaults to `integration-mediamtx`.

Generate RBAC without contacting Kubernetes:

```sh
uv run --locked mediamtx-operator manifests > operator.yaml
```

To include a Deployment, supply an image that installs this package:

```sh
uv run --locked mediamtx-operator manifests \
  --image your-registry/mediamtx-integration:your-version \
  --command mediamtx-operator > operator.yaml
```

The generated ClusterRole only reads Core Users. Binding permissions remain in
the selected namespace. `mediamtx-operator` receives no Secret, Core status, deletion,
CRD installation or RBAC administration permissions. Shared CRDs are not
generated or installed by this application, including when the shared Core
models carry Cloudcoil CRD metadata. Use one replica for this slice.
The [Zarf package workflow](../README.md#zarf-package) builds a local
`mediamtx-operator` image and archive. A release image has not been published.

An internal HTTP diagnostics listener exposes `/healthz`, `/readyz` and
`/metrics` on port 8080. Readiness means that the controller's watches have
started and synced. It is not media readiness or fresh-policy evidence. Keep
the diagnostics listener internal when deploying `mediamtx-operator`.

## Verification

The unit suite uses real Cloudcoil resource clients with mocked Kubernetes HTTP
responses. It covers restart idempotency, stale cached Users, missing and
replaced Users, orphan readiness, namespace and ownership checks, conflict
recovery, dependency outages and generated RBAC. Default pytest needs no cluster.

The existing owned-cluster binding probe also exercises the running
`mediamtx-operator`:

```sh
PATH="$PWD/.local/bin:$PATH" task kind:up
uv run --locked spikes/m2/run_bindings.py --crds ../core/manifests/crds/crds.yaml --operator
PATH="$PWD/.local/bin:$PATH" task kind:down
```

The probe refuses existing Core CRDs. It creates only fixture Users and bindings,
runs `mediamtx-operator` with explicit fixture credentials, and removes its fixtures
and installed CRDs. It checks startup replay, binding recreation, User
recreation, incomplete status, orphan readiness invalidation, preservation of
an unrelated binding and shutdown. The live run passed all assertions and
fixture/cluster cleanup. The [result record](m2-operator-results.json) includes
the tested source hashes; the runner writes `.local/m2/operator-results.json`.
Both sibling clusters remained present. The original binding result record is preserved.
The `mediamtx-operator` probe passed again with `lib-opendefence-core` 0.2.1+261010 and
Core's current CRDs; fixture and owned-cluster cleanup passed. The original
`mediamtx-operator` result record remains a Cloudcoil-only checkpoint.
The live role checks and packaged `mediamtx-operator` deployment passed in an
isolated Kind cluster. The first Deployment crashed because Cloudcoil could
not create a temporary directory on the read-only root filesystem. The overlay now mounts a 16 MiB memory-backed
volume at `/tmp`. One replica became available after this change.

The deployed ServiceAccount could read Users, create UserBindings and patch
binding status. Kubernetes denied Secret reads, binding deletion and binding
creation in another namespace. A fixture User received a UID-pinned binding
with `Synced=False`. The owned cluster and kubeconfig were removed. The sibling
clusters remained present. This check does not prove MediaMTX provisioning or
network policy enforcement. TAK remains deferred.
