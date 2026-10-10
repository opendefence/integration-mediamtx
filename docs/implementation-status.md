# Implementation status

Date: 2026-10-10. Gate: M1 protocol spike and contract checkpoint saved.
External Core and deployment decisions remain open. M2 has not started.

Reviewed implementation HEAD: `1248079bef9cd1526418168d2d62ed7ecc575cea`.
M1 spike commit: `d3da9cd`. Contract and evidence commit: `1248079`.
This checkpoint is a separate documentation commit after that implementation.
Run `git log -1 --format=%H -- docs/implementation-status.md` to get its commit ID.

## Completed work

- Read the implementation plan and all of `openapi.json`.
- Read the exact TAK prototype foundation at
  `b332e527c7dedf5e3f0a972b792c7d697dcace6b` from the local Git history.
- Created the Python package, uv lockfile, strict type checks, lint checks,
  pytest checks, local prek hooks and Make entry points.
- Added checks in GitHub Actions. Top-level checkout and shared setup actions
  use commit references. The shared setup action was read at its pinned revision.
  Its nested actions use the tags defined by that upstream revision.
- Kept Snyk explicitly disabled. No security scan result is claimed.
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
  No public API or operator was added.

## Evidence

- `make check`: passed. Ruff lint and format passed. Strict Pyrefly reported
  zero errors. The lock check passed. Pytest reported 10 passed.
- `make build`: passed. Both the source distribution and wheel were built.
- `uv run --locked prek validate-config .pre-commit-config.yaml`: passed.
- `uv run --locked prek run --all-files`: all four hooks passed after staging.
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
  now includes spike code. The 10 pytest tests cover the foundation; the live
  spike is a separate explicit command, not part of default pytest.
- M1 namespace cleanup and owned cluster cleanup passed. Sibling clusters
  `opendefence-dev` and `tak-server-t0` remained present.
- Ponytail review: ship this isolated spike and contract checkpoint. Checked
  connected callers, fixture lifecycle, credentials, assertions, documentation
  and dependent tooling. No unresolved code findings at the one-runner scope.
  The M0 foundation audit remains valid; the final runtime audit is reserved
  for M5. The product gates below are not waived by this review.

## Runtime record

- Host: macOS, arm64.
- Python: 3.14.7. PyCharm configured `.venv/bin/python`; package manager: uv.
- uv: 0.12.8 locally; CI configuration: 0.12.13.
- Ruff: 0.17.0. Pyrefly: 1.3.2. Pytest: 9.1.1. prek: 0.5.5.
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

The next stage requires `gpt-6.1-sol / high`. Stop before M2 until the user
confirms that setting or explicitly waives the gate. Start only its independent
policy slice while the external contracts below remain unresolved.

## Remaining work and limits

M2 can implement canonical IDs and paths, exact grant scope, fresh-policy
semantics and pure regression tests. It must deny the audited admin-sharing
and overlapping-owner failures. Use semantic fixtures without pretending that
Core supplies an agreed policy projection. Add Cloudcoil at a reviewed commit
only when a real adapter needs it.

Production Core binding ownership/schema, policy freshness and revision,
trusted ForwardAuth headers, identity restore and approval deadlines remain
unsettled in the working handoff. The prototype is not a substitute contract.
Core owns certificate activation; media sessions are not activation evidence.

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

The API and operator are not implemented yet. Production policy, RTMPS, SRT,
WebRTC/ICE, native clients, Core/operator faults, ForwardAuth, release images,
offline installation, AMD64 and hosted CI execution are not checked.
Image publishing on `arc-runner-set` is deferred until runtime images exist.
The Core companion document was located during M1. Its source hash and the
user-supplied companion search URLs are recorded in `docs/m1-contracts.md`.
