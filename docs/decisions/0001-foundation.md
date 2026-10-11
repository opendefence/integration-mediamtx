# Repository foundation

Date: 2026-10-10. Gate: M0.

Use one Python 3.14 package, `opendefence_integration_mediamtx`, for the future
API and `mediamtx-operator`. Run those processes and MediaMTX in separate Pods.
Core owns identity and effective permissions. `mediamtx-operator` writes
integration binding status.
Namespace Secrets hold credentials. Do not add a user database or sidecars.

Use the development settings from TAK prototype revision
`b332e527c7dedf5e3f0a972b792c7d697dcace6b`: uv, Ruff, strict Pyrefly,
pytest and prek. Use Task for task entry points, as requested after the original
foundation work. Shared development clusters use the base repository's tasks;
protocol probes keep their isolated owned cluster. Do not copy Java, JNI,
certificate packaging, SQL or legacy private package indexes.

Runtime dependencies are deferred until their code is added. Pin Cloudcoil to
a reviewed commit when the Core adapter needs it. The draft OpenAPI file remains
a design input. It does not describe an implemented service.

Use a dedicated Podman-backed Kind cluster with a digest-pinned node image.
Keep its kubeconfig inside this checkout. Refuse to adopt an existing cluster.
Keep an ownership record before creation so failed creation can be cleaned up.
Only named, owned clusters can be deleted. Load image archives explicitly.

The user deferred TAK support on 2026-10-10. Defer TAK video XML profiles and
all integration with sibling TAK tasks. Those profile names remain in the draft
contract for later review. Keep them out of runtime capabilities until the sibling
work is ready and client tests pass.

Core policy, status ownership, identity encoding, HTTP routing and session expiry
remain M1 decisions. Do not invent Core resource fields or identity headers.
No protocol or strict outage guarantee is established by this foundation.

M2 clarification: the user supplied the actual UserBinding CRD and delegated
user mTLS to Core. The [binding adapter](../m2-bindings.md) records the current
schema, injected UUID header and remaining policy contract.
