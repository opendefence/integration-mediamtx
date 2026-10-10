# Implementation status

Date: 2026-10-10. Gate: M0 foundation complete. M1 has not started.

Reviewed implementation HEAD: `05f8b002bdac2f6122c9e18b046b3a8fef77aee0`.
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
- Ponytail review: ship this foundation. The ownership flow, callers, tests,
  packaging and CI were checked. No unresolved findings.
- Ponytail audit: the foundation is healthy for one developer running serial
  cluster commands. This is not the final M5 runtime audit.

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
- MediaMTX and application runtime images: not selected or deployed in M0.

## Skills and model evidence

The actual skill files were read. The hashes below identify the local instructions:

- Ponytail full: SHA-256 `1316a2f3f95741d2300b116fe0c2d81ce4a9568656ed0a62643f54aaf09957f2`.
- Caveman: SHA-256 `0bf09a0a9a017d004a81d4b693e5a2d830e1a28230a5885df773e1ed9c0571cc`.
- Ponytail review, plugin 5.1.0: SHA-256 `33fe4ebe22a460924e5d4a261e223df22e409cc94ab76182bee9fb91a3ef022e`.
- Ponytail audit, plugin 5.1.0: SHA-256 `2b3223a02c386d1263e1b08343cb8eb3a53e444cdafb1d79e26c8ec2a8fcad28`.

The plan requests `gpt-6.1-sol / medium` for M0. The active session did not
provide verifiable model and effort metadata or a session-switch tool.
M0 setup ran in the existing session. No model substitution is claimed.
M1 requires `gpt-6-astra / xhigh`. Stop before M1 until the user confirms
that setting or explicitly waives the gate, as required by plan section 13.

## Remaining work and limits

M1 must settle Core binding ownership, effective-policy freshness, identity
encoding and recovery, grant durability, HTTP routing and outage behavior.
It must produce reviewed contracts and a small protocol test. Then implement
canonical paths, scoped policy, Secrets, API, operator and session removal in
the order defined by the plan. Add Cloudcoil at a reviewed commit when needed.

TAK-specific support stays deferred until the sibling TAK tasks are complete.
This includes TAK video XML and cross-repository integration. Existing TAK names
in the draft API do not advertise runtime support.

The API and operator are not implemented yet. Media authorization, UDP networking,
real clients, fault recovery, ForwardAuth, release images, offline installation,
multi-architecture builds and hosted CI execution are not checked.
Image publishing on `arc-runner-set` is deferred until runtime images exist.
The shared chat URLs could not be fetched. The Core architecture companion
document was not located. Do not invent its missing contract.
