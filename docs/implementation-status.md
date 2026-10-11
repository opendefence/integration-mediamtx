# Implementation status

Date: 2026-10-11. Gate: M2 policy, identity, bindings and the binding operator tested.
MediaMTX provisioning and public API authorization need Core's effective-policy contract.
M3 has not started.

## Packaged operator deployment checkpoint

Date: 2026-10-11. The local-dev Zarf overlay was deployed to an isolated Kind
cluster with the current Core resource definitions. The first Pod could not start because
Cloudcoil needs a temporary directory and the root filesystem is read-only.
The Deployment now mounts a 16 MiB memory-backed volume at `/tmp`.
The corrected Deployment rolled out with one available replica.

The deployed ServiceAccount could read Core Users, create UserBindings and patch
their status. Kubernetes denied Secret reads, binding deletion and binding
creation in another namespace. A fixture User caused the operator to create one
UserBinding pinned to that User's identifier, with `Synced=False`. The owned cluster and its kubeconfig
were removed. The three sibling Kind clusters remained present.

`task check` passed Ruff, strict Pyrefly and 216 tests. `task package:check`
passed Zarf lint and both overlay renders. The ARM64 Zarf archive was rebuilt
and its definition inspected. This check does not prove network policy
enforcement or MediaMTX provisioning.

## Media ingress policy checkpoint

Date: 2026-10-11. The Zarf package now includes namespaced ingress
`NetworkPolicy` rules in both production and local-dev overlays. They select
future MediaMTX Pods for HLS, WebRTC signaling and ICE, RTSPS, RTMPS and SRT
ports from Traefik, and allow the operator to reach the private control port.
The operator policy has no ingress allow rules. The package still has no
MediaMTX Service or workload; base has no native streaming entrypoints.
Live policy enforcement and external client reachability have not been verified.
Zarf lint and both overlay renders passed. The ARM64 package archive was
rebuilt and inspected. Kubernetes accepted both policies in a server-side dry
run. `task check` passed Ruff, strict Pyrefly and 216 tests; all applicable
pre-commit hooks passed.

## M2 session-removal checkpoint

Date: 2026-10-11. Added a MediaMTX 1.21.2 control adapter that scans all pages
for one grant username and kicks matching HLS, RTSPS, RTMPS, SRT or WebRTC
connections. It repeats scans and reports incomplete cleanup on API errors or
sessions that persist. `task check` passed Ruff, strict Pyrefly and 215 tests.
See [session removal](m2-sessions.md). The adapter is not yet wired to persisted
grant revocation or the operator, so no production cleanup guarantee is claimed.

## Zarf package checkpoint

Date: 2026-10-11. Implementation commit: `34cc9658ece04f768d612700c990fa93d3b95c5a`.
Following sibling Core's overlay names, `values/values.yaml` supplies the
production namespace and `values/local-dev.yaml` selects the development
namespace. `zarf.yaml` packages the current binding observation operator image,
namespace RBAC and Deployment. Its only application setting,
`CLOUDCOIL_NAMESPACE`, comes from the Pod namespace; the package `namespace`
value controls the manifest. The package does not own a Namespace or Core CRDs.

`task package:check` passed Zarf 0.87.0 lint and manifest inspection for both
overlays. Schema validation rejected an invalid namespace. Podman built the
ARM64, non-root operator image; Zarf created and inspected the image-bearing
package archive. The image entry point ran in a read-only container.
`task check` passed Ruff, strict Pyrefly and 201 tests; `task build` produced
both Python distributions. All applicable pre-commit hooks passed. The package
was not deployed to a cluster, and AMD64 and hosted CI builds were not run.
MediaMTX provisioning and public API authorization remain gated on Core's
effective-policy contract. See the [package workflow](../README.md#zarf-package).

Reviewed implementation HEAD: `faf76f5c2bd9c8c0e60bc1df0da17c4f3dcf7000`.
M2 commits: `4dc535f` (paths), `70bb721` (admission policy), `05f1687` (live test).
The subsequent commits are `f69561c` (Core UUID header) and `a39005f` (binding adapter).
The user expanded the checks in `47f892e`; `4a1d8b4` fixes the resulting failures.
The package rename is in `5200799`.
The Task migration and original-document relocation are in `17a8da1`.
Pinned remote base tasks are in `7f2b21a`.
The binding operator and isolated probe network fix are in `a19793c`.
The shared Core model dependency is in `faf76f5`.
The original M1 checkpoint remains in `eff771f`.
This checkpoint is a separate documentation commit after that implementation.
Run `git log -1 --format=%H -- docs/implementation-status.md` to get its commit ID.

## Completed work

- Read the [original implementation plan](integration-mediamtx-plan.md) and all
  of the [original API draft](openapi.json), now retained under `docs/`.
- Read the exact TAK prototype foundation at
  `b332e527c7dedf5e3f0a972b792c7d697dcace6b` from the local Git history.
- Created the Python package, uv lockfile, strict type checks, lint checks,
  pytest checks, local prek hooks and Task entry points, originally provided by Make.
- Added checks in GitHub Actions. Top-level checkout and shared setup actions
  use commit references. The shared setup action was read at its pinned revision.
  Its nested actions use the tags defined by that upstream revision.
- Kept Snyk explicitly disabled. No Snyk scan result is claimed.
- Created and tested an isolated, digest-pinned Kind workflow with Podman.
- Recorded the user's TAK deferral in the plan, draft contract and decision record.
- Located and read the working Core architecture handoff and API draft. Compared
  the actual Core operator prototype with the proposed ownership model. Recorded
  unresolved wire contracts instead of inventing Core fields or headers.
- Defined integration identity and policy semantics, bounded grant storage,
  quota reservations, idempotency and cleanup ordering in
  [M1 contracts](m1-contracts.md). Storage implementation and concurrency proof
  remain M2 work. Sharing purpose needs a contract decision before issuance.
- Added a reproducible, standard-library protocol spike with pinned images.
  It tests RTSPS publication, scoped HLS access, paginated session removal,
  callback outage, certificate pinning and the broken HTTP prefix redirect.
  See [findings](m1-findings.md) and the [result record](m1-results.json).
- Updated OpenAPI design gates and its secure-protocol mapping description.
  No public API or operator was added at that checkpoint.
- Implemented canonical UUID normalization, compact media paths and versioned
  stream IDs. Reject path aliases and complete-segment ownership failures.
- Added immutable grant and effective-policy models, callback normalization and
  constant-time scoped admission. Deny unknown or stale state, pending accounts,
  removed assignments, replaced bindings, revoked grants and expired deadlines.
- Added regression cases for both audited policy failures. A read credential
  cannot gain publish or control permissions from its owner's wider access.
- Reused the live protocol runner with the actual package source and explicit
  policy fixtures. Recorded source hashes and evidence in
  [M2 results](m2-results.json). See [M2 policy](m2-policy.md) for the exact scope.
- Rechecked the Core handoff hash and prototype HEAD. Both remain unchanged
  from the M1 sources, and no agreed production contract was found there.
- Consumed the user's supplied `../opendefence_core_crds.yaml`, SHA-256
  `105bede6c1dd9f77c9effb6d8525d5882822a6ca67c75f14f2f59f64f106a747`.
  Bindings are integration-created observations, not Core assignments. Status
  only permits conditions and observed generation. Updated the plan and draft.
- Implemented the configurable `X-OpenDefence-User-UUID` parser. Core owns mTLS
  and any ForwardAuth implementation. Reject duplicate, joined and noncanonical
  identity values; do not echo them in errors or parse certificates here.
- Added typed Core binding models and atomic creation with immutable User UID
  pins. Guard status writes with binding UID and resource version. Preserve
  condition transition times and skip unchanged observations. No grant is issued
  by these adapters, and no permission inheritance is implemented.
- The original binding probe used reviewed Cloudcoil commit
  `e8ec4ef00c03b2c8974ed7ed0c99a7280ee802c8`. The dependency now uses registry
  release 0.8.0, as selected in the user's checks commit. Read Core's scaffold at
  `af0375a41aad095ce464ba588544930d0a486793`; no media-policy wire contract exists
  at that revision. See [M2 bindings](m2-bindings.md).
- Added the [binding operator](m2-operator.md) with Cloudcoil's Application,
  scoped controller watches, retry queue, CLI and transport lifecycle. It watches
  Core Users read-only and owned bindings in one namespace. Fresh User reads
  precede atomic creation; owned status writes only report incomplete provisioning.
  Missing or replaced Users do not cause retargeting or destructive cleanup.
- Added `mediamtx-operator` and `task operator:run`, offline manifest generation,
  namespace RBAC and internal controller diagnostics. Shared Core CRDs are not
  installed by the application. Media readiness, credentials and finalizers remain
  pending. Rechecked Core HEAD: still `af0375a41aad095ce464ba588544930d0a486793`.
- Replaced local Core CRD classes with `lib-opendefence-core` 0.2.1+261010
  `User`, `UserBinding` and their spec, status and condition models. The uv source
  uses Nexus pypilocal explicitly. Core's typed User model requires lowercase
  callsigns; fixtures now use names that match that contract. Ownership and
  UID/resource-version status guards remain in the integration adapter.
- Cloudcoil recognizes the shared UserBinding class as a CRD source. The operator
  omits that Core-owned CRD from generated manifests and installation while
  keeping its namespace RBAC and runtime watch. The original local schema classes
  and four type-check suppressions were removed.

## Evidence

- `task check`: passed. Ruff lint and format passed. Strict Pyrefly reported
  zero errors with four narrow suppressions for Cloudcoil wire-field overrides.
  No warnings remain. The lock check passed. Pytest reported 199 passed: 29 binding
  cases, 21 identity-header cases, 22 operator cases, 48 path cases, 68 admission
  cases, two foundation cases and nine isolated Kind cases.
- `task build`: passed. Both the source distribution and wheel were built.
- `uv run --locked prek validate-config .pre-commit-config.yaml`: passed.
- `uv run --locked prek run --all-files`: all applicable expanded hooks passed.
- `bash -n scripts/kind.sh`, JSON syntax and staged whitespace checks passed.
- Live Kind creation passed. The node became Ready. Image archive loading
  passed, and the probe image was visible in the node's image store.
- Owned cluster and probe image cleanup passed. The sibling clusters
  `opendefence-dev` and `tak-server-t0` remained present.
- M1 live spike: passed. An HLS session delivered a 26,132-byte MPEG-TS segment
  after future admission was denied. Kicking two paginated sessions denied
  query, cookie and segment requests; repeated kick returned 404. Kicks and
  immediate verification took 0.065 seconds locally, after denial was set.
- Actual callback Pod shutdown denied new HLS and control requests while an
  existing HLS query session remained usable. A wrong callback pin was denied;
  changing the pin through the API also restarted listeners and ended sessions.
- Traefik StripPrefix test reproduced a 302 outside the public prefix followed
  by 404. This is expected negative evidence; production routing remains gated.
- The callback event sample and current fixture Pod logs passed generated-secret
  checks. Historical containers, platform logs and traces were not audited.
- Final `make check`, `make build` and all four prek hooks passed. Strict Pyrefly
  includes spike code. The live spike remains a separate explicit command,
  not part of default pytest.
- M1 namespace cleanup and owned cluster cleanup passed. Sibling clusters
  `opendefence-dev` and `tak-server-t0` remained present.
- Ponytail review: ship this isolated spike and contract checkpoint. Checked
  connected callers, fixture lifecycle, credentials, assertions, documentation
  and dependent tooling. No unresolved code findings at the one-runner scope.
  The M0 foundation audit remains valid; the final runtime audit is reserved
  for M5. The product gates below are not waived by this review.
- M2 live package policy: passed. A stale fixture projection denied new media
  access while the separate fixture control credential remained usable. Scoped
  RTSPS/HLS admission, nullable callback IDs and duplicate password/token fields
  worked with the pinned MediaMTX runtime.
- M2 read-after-denial delivered 26,508 MPEG-TS bytes. Paginated session removal
  then denied query, cookie and segment requests. Two kicks and immediate
  verification took 0.061 seconds locally, after admission denial was set.
- Callback shutdown, wrong-pin denial and broken-prefix negative assertions
  still passed. Current Pod logs and sampled callback events passed secret checks.
- M2 namespace and owned cluster cleanup passed. Both sibling clusters remained.
  A conflicting port forward on 18443 was left running; this fixture moved to
  28443. No unrelated process or resource was stopped.
- Ponytail review before M2 commits: checked module callers, parsers, grant and
  policy validation, time boundaries, secret representations, fixture imports,
  live assertions and cleanup. Ship this independent slice. No unresolved code
  findings at the pure-policy and one-runner scope. This is not the M5 audit.
- Live shared-CRD binding probe: passed. Eight concurrent creators returned one
  persisted binding. Synced status recorded the current generation, and a repeat
  made no write. Stale resource versions and replaced binding UIDs were rejected.
  Recreated Users received separate bindings despite name reuse. Kubernetes
  pruned unsupported status fields. Results and source hashes are in
  [M2 binding results](m2-bindings-results.json).
- The probe initially tried to reopen a client already used by discovery. It
  now registers explicit transport-close callbacks. The corrected live run passed
  and removed its User, namespace and installed CRDs. The owned cluster was also
  removed; both sibling clusters remained. No source-file RBAC was installed.
- Ponytail review before the identity and binding commits: ship these adapters.
  Checked header ambiguity, namespace ownership, atomic creation, UUID replacement,
  status transitions, client lifecycle, dependency metadata and cleanup. This
  does not validate production ingress, RBAC or effective-policy provenance.
- Checks maintenance: Bandit uses Python 3.14 explicitly. Constructing the same
  lone-surrogate fixture avoids its report encoding crash. Narrow rule-specific
  exceptions cover test credentials, field length limits, private fixture flags
  and developer-tool subprocess calls. No Python directory is excluded.
- The audited secret baseline contains eight public source hashes in two
  historical JSON records. Inline exceptions cover known test values and one
  Kubernetes Secret name. Negative probes confirmed that new credentials in
  both new and baselined files still fail, and Bandit still detects a new
  hardcoded password. Conventional subjects pass; invalid subjects fail.
- JSON normalization changed no parsed value in the API or three result records.
  Restored PyYAML stubs; strict Pyrefly reports no warnings. Final `make check`
  passed all 176 cases, and `make build` produced both distributions.
- The branch guard rejects local commits on main. An isolated main-branch probe
  verified that CI can skip only this guard; all content checks stay enabled.
  Hosted CI and live protocol/binding probes were not repeated for this change.
- Ponytail review before the checks fix: ship. Checked fixture callers, argument
  vectors, admission behavior, exact baseline entries, lock changes, CI and
  historical evidence. No unresolved findings within this maintenance scope.
- Renamed the Python package and distribution to `opendefence_integration_mediamtx`.
  Updated imports, build metadata, the lockfile, both spike runners, callback
  mount paths and documentation. `make check` passed all 176 tests; both builds
  and all applicable prek hooks passed. The built wheel imports all six modules
  in isolation and includes `py.typed`. Fixture mount paths match the source.
- Preserved the persisted binding ownership label and all historical live
  result records. Tests use the original stored label independently of the
  implementation constant. External Python callers must use the new import;
  no compatibility alias was added. Reverting `5200799` restores the old package.
- Ponytail review before the rename commit: ship. Checked all imports, build
  artifacts, fixture mounts, binding ownership and evidence references. No
  unresolved findings within the rename scope. Live probes were not repeated.
- Moved the original plan and API draft under `docs/`. The API is byte-identical,
  its relative plan reference resolves, and the contract test uses the new path.
  Current documentation points to these as design references.
- Replaced Make with Task 3.51.1, including CI. Read the official setup action's
  entry point and installer at `a00fbb05ce67b35648be3c78cbc9fd85354c757e` and
  pinned that revision. Task listing, all 176 tests, both package builds and all
  applicable prek hooks passed. The source archive includes the relocated docs,
  Taskfile and mise tool pin. Earlier Make command results are historical evidence.
- The initial base development tasks delegated to a checkout at `../base`, with
  a `BASE_DIR` override and base variables forwarded after `--`. Read the upstream workflow at
  [`b04ff076bc4d3ec6a2ce01074a66f10d0f09b7a6`](https://github.com/opendefence/base/tree/b04ff076bc4d3ec6a2ce01074a66f10d0f09b7a6/taskfiles).
  At that checkpoint, the sibling checkout was at
  `604587f4da6f1e894b68ec6495c45b2d16510cbd`.
- Disposable Task fixtures verified delegation, working directories, forwarded
  variables, quoted archive paths and missing-argument rejection. Task listing
  works without a base checkout. No real base lifecycle command was run, and
  the sibling checkout was not changed. Isolated probe cluster tasks remain separate.
- Ponytail review before the Task migration: ship. Checked callers, document
  links, archived evidence, command ordering, task quoting, CI pins and package
  contents. Hosted CI and live cluster/protocol checks were not repeated.
- Read the updated sibling base at `b04ff076bc4d3ec6a2ce01074a66f10d0f09b7a6`,
  including its instructions and remote-safe registry, cluster and package tasks.
  Replaced checkout delegation with HTTPS includes at that Git revision and
  pinned each reviewed file's SHA-256. Task 3.54.0 is pinned in mise and CI;
  remote includes are enabled without experimental configuration. The official
  [Task documentation](https://taskfile.dev/docs/remote-taskfiles) and
  [changelog](https://taskfile.dev/docs/changelog) were read for this change.
- `base:up` retains sequential registry and cluster setup, then installs an
  explicit `BASE_VERSION` or `BASE_PACKAGE`. Its input precondition precedes
  registry writes. CLI overrides now use native `NAME=value` arguments.
  Package operations retain upstream kube-context guards. `base:down` keeps
  registry data. Unpublished source builds remain checkout-only in `../base`.
- Root Task listing, offline cached listing and individual downloaded include
  listings passed. `task check` passed all 176 tests, Ruff and strict types;
  `task build` produced the source distribution and wheel. All applicable prek
  hooks passed. The three public Taskfile checksums have narrow inline secret
  scanner annotations; the audited secret baseline was not expanded.
- Ponytail review before the remote Task commit: ship. Checked upstream command
  ordering, package inputs, context and ownership guards, task namespaces, CLI
  overrides, CI/tool version agreement and cache handling. Cluster lifecycle
  commands and hosted CI were not run. No package publication is claimed.
  The sibling base checkout and isolated probe lifecycle tasks were not changed.
- Live binding operator probe with registry Cloudcoil 0.8.0: passed. Startup
  replay created missing bindings; deleting a binding recreated it with a new UID.
  Recreating a User created a separate pinned binding. Owned observations stayed
  pending, former orphan readiness was cleared, an unrelated binding's resource
  version stayed unchanged and the application stopped cleanly. The original
  adapter assertions also passed against this release. See the source hashes and
  cleanup results in [operator results](m2-operator-results.json).
- Probe fixtures, namespace, User and installed Core CRDs were removed. The owned
  cluster `mediamtx-5695ccafbf64` and its explicit kubeconfig were removed.
  Sibling clusters `opendefence-dev` and `tak-server-t0` remained present.
  Live operator RBAC enforcement, image deployment and diagnostics were not tested;
  the probe used its explicit fixture Config with diagnostics disabled.
- Live setup exposed imported base Task environment selecting the isolated Kind
  network. The probe script now unsets inherited Docker/Podman network settings.
  A regression test verifies isolation. Removed the initial probe cluster, then
  recreated it with the corrected settings before running operator assertions.
- Offline CLI manifest generation passed with an intentionally absent kubeconfig.
  Manifest tests verify read-only Core permissions, namespace-scoped bindings and
  no Secret/deletion/CRD privileges. Both package builds passed, and the wheel's
  console entry point resolves to the operator. All applicable prek hooks passed.
- Added only four independently verified public source hashes from the new result
  record to the secret baseline; the eight historical entries remain unchanged.
  No file exclusion or detector was relaxed.
- Ponytail review before the operator commit: ship this binding observation slice.
  Checked fresh-read boundaries, UID and namespace guards, negative-only status,
  restart and conflict handling, mapped watches, generated RBAC, console packaging,
  transport ownership, fixture cleanup and existing adapter callers. No unresolved
  findings in this scope. MediaMTX provisioning remains unimplemented and gated.
- Shared-model migration: `task check` passed with 200 tests, Ruff and strict
  Pyrefly (zero errors). `task build` built both distributions. Offline CLI
  manifest generation passed without a kubeconfig and emitted no Core CRD.
  All applicable pre-commit hooks passed.
- The owned Kind probe passed the original binding and running-operator assertions
  against Cloudcoil 0.8.0, `lib-opendefence-core` 0.2.1+261010 and the current
  sibling Core CRDs at `6fd602383616947b8e29e4ee12be61fab3d2443c`
  (file SHA-256 `fb2d59fa58e562a1c20c46cc590458e15d249e1f94b777a14b91eecc15c5b79a`).
  Fixture User, namespace and installed CRDs were removed; the owned cluster
  and kubeconfig were removed. Both sibling clusters remained running. The
  earlier JSON result records remain historical and were not rewritten.
- Ponytail review before the shared-model commit: ship. Checked the model import
  identity, lower-case Core fixture contract, timestamp serialization, status
  guards, offline manifests, registry lock and cleanup. No unresolved findings
  within this migration. Production RBAC enforcement and image deployment remain
  separate gates.

## Runtime record

- Host: macOS, arm64.
- Python: 3.14.7. PyCharm configured `.venv/bin/python`; package manager: uv.
- uv: 0.12.8 locally; CI configuration: 0.12.13.
- Ruff: 0.17.0. Pyrefly: 1.3.2. Pytest: 9.1.1. prek: 0.5.5.
- Task: 3.54.0 from mise locally; CI uses the pinned official setup action.
- Cloudcoil: registry version 0.8.0 with Kubernetes, operator and test extras.
  Core models: `lib-opendefence-core` 0.2.1+261010 from the explicit Nexus
  pypilocal index. Its wheel SHA-256 is
  `ec6eaec3dbd9d5166922beffa24b76d592ce68d538051b8cc9c4602f4c249bdc`.
  The historical live binding probe used Git package version 0.5.0.dev0 at
  `e8ec4ef00c03b2c8974ed7ed0c99a7280ee802c8` (upstream tag 0.8.0).
  HTTPX: 0.28.1. Pydantic: 2.14.0; pydantic-core: 2.50.0. PyYAML: 6.0.3;
  types-PyYAML: 6.0.12.20260906. All resolved versions are in `uv.lock`.
- Podman: 6.0.2. Kind: v0.33.0. kubectl and test Kubernetes: v1.37.0.
- Kind binary: `.local/bin/kind`, fetched from the official release.
  SHA-256: `0c8c7dbe5e23594a198b786c4bc13dacc101fa6196b0cb0b23a1ca44e61f4b4f`.
- Node image: `kindest/node:v1.37.0@sha256:a1ed56cfb0e7b93589bdf97c8cd566405a265939e3620fc4f5de89adff580ae5`.
  Podman inspection confirmed the digest. Source:
  [Kind v0.33.0 release](https://github.com/kubernetes-sigs/kind/releases/tag/v0.33.0).
- Tested context: `kind-mediamtx-5695ccafbf64`. Kubeconfig: `.local/kind/kubeconfig`.
  The cluster and its kubeconfig were removed after the check.
- Probe image: `localhost/mediamtx-foundation:5695ccafbf64`, image ID
  `6ed7f3a5f96eb2ecba9a741c0866a271bdded93f5673e711aa80d6ee3c2fbf43`.
  This scratch image tests archive loading only. It is not a MediaMTX runtime.
- M1 MediaMTX: 1.21.2 with FFmpeg 8.1.2, ARM64.
  `docker.io/bluenviron/mediamtx@sha256:dfbb58bf4f3e6c03ce3ee56e92c90395e7cfd96beb51e13fa7d4007f10507586`.
- M1 Python callback fixture: 3.14.7-slim, ARM64.
  `docker.io/library/python@sha256:67994a05c712036dbfc4385b4bceafc0ce20df950f54b9ea355582c153bf6157`.
- M1 Traefik candidate: 3.7.14, ARM64.
  `docker.io/library/traefik@sha256:060f4c0328bebb33be8a73694ea613055c4591ba26493202a1830f964e171995`.
  This is not a base-approved production selection.
- All fixture images were loaded through named OCI archives. Pods used
  `imagePullPolicy: Never`. Registry fetches were allowed before import; this
  is not a full offline-install test. No application runtime image was built.
- M2 reused the exact ARM64 images and tool versions above. The callback mounted
  the checked-in package modules; their measured hashes are in `m2-results.json`.
  Package source was tested without an API/operator runtime image.

## Skills and model evidence

The actual skill files were read. The hashes below identify the local instructions:

- Ponytail full: SHA-256 `1316a2f3f95741d2300b116fe0c2d81ce4a9568656ed0a62643f54aaf09957f2`.
- Caveman: SHA-256 `0bf09a0a9a017d004a81d4b693e5a2d830e1a28230a5885df773e1ed9c0571cc`.
- Ponytail review, plugin 5.1.0: SHA-256 `33fe4ebe22a460924e5d4a261e223df22e409cc94ab76182bee9fb91a3ef022e`.
- Ponytail audit, plugin 5.1.0: SHA-256 `2b3223a02c386d1263e1b08343cb8eb3a53e444cdafb1d79e26c8ec2a8fcad28`.

The plan requests `gpt-6.1-sol / medium` for M0. The active session did not
provide verifiable model and effort metadata or a session-switch tool.
M0 setup ran in the existing session. No model substitution is claimed.
M1 used the user's explicit confirmation, “Switched; resume M1”, as evidence
for the requested `gpt-6-astra / xhigh` setting. Independent session metadata
was not available. This is the confirmation route allowed by plan section 13.

M2 used the user's explicit confirmation, “Switched; resume M2”, as evidence
for the requested `gpt-6.1-sol / high` setting. Independent session metadata
was not available. Only the independent policy slice and its protocol proof
were implemented while the external contracts remain unresolved.

M2 is not fully implemented. The remaining work needs the external decisions
below. Before a later transition to M3, follow plan section 13 and confirm
`gpt-6-astra / high`. No M3 review or model substitution is claimed here.

## Remaining work and limits

Canonical IDs and paths, exact grant scope, fresh-policy semantics and the
audited regressions are implemented. The semantic fixtures do not prove that
Core supplies this projection. The shared-CRD binding adapter and running binding
operator now pass unit and live checks with registry Cloudcoil 0.8.0. The original
adapter result retains its reviewed Git dependency identity. There is no local
inheritance algorithm or user database.

Binding ownership/schema and the integration's injected-header responsibility
are resolved by the user's M2 clarification. Core policy freshness, effective
permissions and revision, identity restore and approval deadlines remain open.
The previously inspected scaffold and supplied CRDs do not define that projection;
the newly installed model library does not add it. A source
was requested asynchronously; no fallback authority is assumed. Core owns
certificate activation; media sessions are not activation evidence. Validate
header stripping and trusted-only ingress in deployment; do not build ForwardAuth here.

Grant storage has a documented design, not persistence proof. Implement and
test concurrent reservation/create, idempotent retries, conditional updates,
revocation, restart recovery and garbage collection before exposing issuance.
The self-use/sharing purpose decision also blocks that endpoint.

HTTP prefix routing needs a base-approved response rewrite or another agreed
route contract. Strict deadline enforcement during callback, operator or control
outage has no accepted mechanism. Keep the strict-outage capability false.
The 15-second freshness and 30-second removal targets are not measured guarantees.

TAK-specific support stays deferred until the sibling TAK tasks are complete.
This includes TAK video XML and cross-repository integration. Existing TAK names
in the draft API do not advertise runtime support.

The binding observation operator is implemented; MediaMTX provisioning and the
public API are not. Bindings stay `Synced=False` while those dependencies remain
open. Core policy provenance, RTMPS, SRT, WebRTC/ICE, native clients, Core policy
and MediaMTX provisioning faults, trusted ingress, release images,
offline installation, AMD64 and hosted CI execution are not checked.
Image publishing on `arc-runner-set` is deferred until runtime images exist.
The Core companion document was located during M1. Its source hash and the
user-supplied companion search URLs are recorded in `docs/m1-contracts.md`.
