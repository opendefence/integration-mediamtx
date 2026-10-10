# M2 Core identity and bindings

Date: 2026-10-10. This slice consumes the user's supplied CRD and authentication
boundary. It implements adapters, not a running public API or operator process.

Core owns user mTLS authentication and any ForwardAuth configuration. The
integration consumes one injected header through `user_id_from_headers` in
`identity.py`. Its configurable default is `X-OpenDefence-User-UUID`. Preserve
HTTP header pairs; do not convert them to a dictionary before checking for
duplicates. The parser normalizes canonical UUID text and compact Base64URL
into a UUID. It rejects missing, duplicate, joined and noncanonical values.
Errors do not echo supplied values. Identity parsing does not authorize access.
The edge must strip client identity headers and restrict ingress to its trusted
route. No certificate parser or ForwardAuth service was added here.

The shared CRD is `platform.opendefence.fi/v1alpha1`. Integrations create one
namespaced UserBinding per User and write its `Synced` condition. Core watches
these observations. The spec only contains `userRef.name`; status only contains
conditions and observed generation. Binding existence and `Synced=True` do not
prove assignment, policy freshness or media permission.
The persisted `app.kubernetes.io/managed-by` value remains
`odintegration-mediamtx` across the Python package rename, so existing bindings
retain their ownership identity.

`bindings.py` provides typed models and two resource operations:

- `ensure_binding` takes a fetched Core User and a namespace-scoped Cloudcoil
  client. It atomically creates `mediamtx-<User UUID hex>`. Concurrent losers
  fetch the stored binding and validate its identity and ownership. The
  annotation `mediamtx.opendefence.fi/user-uuid` pins the reference to the
  immutable User UID. A recreated User gets a different binding even if its
  name is reused. Mismatched or deleting bindings are not adopted or retargeted.
- `set_binding_synced` takes the provisioning result from its caller. It writes
  only the status subresource with UID and resource-version tests. It preserves
  other conditions and changes the transition timestamp only when the condition
  status changes. An unchanged observation makes no request. Conflicts propagate
  so the caller must read and reconcile again.

The User view keeps spec and status opaque. It reads identity from metadata and
does not resolve roles or groups. Callers must fetch the current User; a stored
snapshot is not policy freshness evidence. No grants or credentials are created
by these binding operations. They do not set owner references: cleanup must deny
grants and drain sessions before deletion, rather than relying on automatic
garbage collection. That lifecycle remains operator work.
The caller owns the resource client's transport lifetime. Cloudcoil's Config
context does not close HTTP transports; the probe explicitly closes both clients.

The original live probe used Cloudcoil at
[`e8ec4ef00c03b2c8974ed7ed0c99a7280ee802c8`](https://github.com/cloudcoil/cloudcoil/tree/e8ec4ef00c03b2c8974ed7ed0c99a7280ee802c8).
Reviewed the resource models, async create/get/patch clients, JSON Patch guards,
HTTP errors, kubeconfig TLS setup and transport lifecycle used by this slice.
The upstream tag is `0.8.0`, but that Git package reports `0.5.0.dev0`.
The dependency now uses the registry package with Kubernetes and operator
extras; `uv.lock` resolves version `0.8.0`. The unit suite passes against that
release. The recorded live result retains its original dependency identity;
the live probe has not been repeated with the registry package. Future probe
results record the installed version without claiming a Git revision.
The optional upstream pytest cluster plugin is disabled because this repository
uses its own owned Kind workflow. Four narrow Pyrefly suppressions cover
Cloudcoil's documented concrete wire literals over mutable base fields; runtime
Pydantic validation still enforces those literals.

## Verification

The unit suite covers header ambiguity, namespace ownership, atomic-create
responses, User recreation, guarded status writes, no-op observations,
transition times, condition preservation, invalid records and failed writes.
The default test suite uses mocked HTTP responses through the actual Cloudcoil
resource client. It does not create a cluster.

The explicit live probe installs only the User and UserBinding CRDs from the
supplied file in this checkout's owned cluster. It refuses existing Core CRDs
and removes its namespace, User and installed CRDs after the run. It does not
install the source file's RBAC or service accounts. Run lifecycle commands
serially:

```sh
PATH="$PWD/.local/bin:$PATH" make kind-up
uv run --locked spikes/m2/run_bindings.py --crds ../opendefence_core_crds.yaml
PATH="$PWD/.local/bin:$PATH" make kind-down
```

The [live result](m2-bindings-results.json) records eight concurrent creators
returning one persisted binding, current-generation status, a no-op repeat,
stale-write rejection, actual pruning of unsupported status fields, separate
bindings after User recreation and rejection after binding replacement.
Fixture cleanup and owned cluster removal passed; sibling clusters remained.
The CRD input hash is
`105bede6c1dd9f77c9effb6d8525d5882822a6ca67c75f14f2f59f64f106a747`.

No effective-policy endpoint or revision/expiry projection is defined in these
CRDs or the inspected Core scaffold. Production media authorization still needs
that contract. The existing pure policy function remains fail-closed on absent
or stale policy. Ingress, production RBAC, grant persistence, the operator
process and public API are not validated by this probe. TAK remains deferred.
