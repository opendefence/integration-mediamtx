# M1 contracts and dependency gates

Date: 2026-10-10. These are integration design decisions and requirements for
Core review, updated with the user's M2 clarification. They are not a running API. The
[protocol findings](m1-findings.md) distinguish live evidence from design.

Decision update, 2026-10-11: the user selected callsign-based media paths and
the legacy read-all, publish-own path rule for normal media users. Core will let
integrations define Roles and will project effective Role membership onto the
User. This integration defines what `mediamtx-user` permits. Core's global
`superadmin` Role grants all media access in this integration.
There is no `productuser` type. See the [current Core handoff](core-media-policy-handoff.md).
This update replaces the UUID-based media path and permission assumptions below.
User and grant identity still use the immutable Core User UID.
Only current `superadmin` Users and this integration's own service identity may
use MediaMTX `api`, `metrics`, or `pprof`. Ordinary media grants cannot use them.
Core's operator will project effective Roles and Groups into the User after
Role, Group, and assignment changes. This integration already watches User
events. The effective Role schema and bounded freshness fields are pending.

## Core evidence

The working `rasenmaeher-core-architecture-handoff.md` was found in the local
Downloads directory. Its date is 2026-10-10; its SHA-256 is
`33a41720b2255535570a1cc782cd8ca29b13ab97cccb1da580c19926487992be`.
It leaves the Integration Manifest, policy freshness and identity recovery open.
The M2 clarification below supplies binding ownership and the identity-header boundary. The accompanying
API handoff is `3.0.0-draft.6`; it does not supply a versioned media-policy feed.

The local Core operator prototype was read at
`5278b09e9776020b48ccba17f51d7d93e4378d2c`. Its
`src/rmk8soperator/models/v1alpha1/userbinding.py` lets integrations create
namespaced bindings with `spec.userRef.name`. Its status has shared conditions,
and `is_synced()` accepts any `Synced=True` condition. That is not the planned
Core-owned assignment or proof that the current generation is ready. Do not
copy this prototype into a production adapter without a shared decision.

Companion search paths include both user-supplied discussions:
[Core discussion](https://chatgpt.com/share/6aca5977-77e0-83eb-8d24-6162f8327167)
and [integration discussion](https://chatgpt.com/share/6ac980bb-d5dc-83eb-82ab-31ae4dded1ee).
The working handoff and locally cached discussion text informed this review.
The handoff's open items remain open.

## Identity and policy boundary

Core remains the identity authority. Preserve its current `metadata.uid` source.
Normalize canonical UUID text and compact Base64URL into the same UUID value.
Emit compact, unpadded Base64URL for public IDs. Do not infer identity from a
callsign or silently introduce a persistent UUID field. Core must supply a
mapping before grants are restored against recreated Users. Certificate CN
encoding and certificate activation remain Core decisions.

The current path is `live/{tool}/{callsign}` with tools `icu`, `gopro`, `uas`
and `ipcam`. Match exact owner and path segments. Reject encoded separators,
empty or dot segments, invalid callsigns and trailing slashes. Do not enable
subordinate channels until a client needs them. A versioned stream ID encodes
the canonical path; decoding it never grants access. The original M1 spike's
UUID-text paths and the draft's compact UUID paths are historical fixtures.

The shared policy function needs these semantics, without assuming CRD fields:

| Input | Required meaning |
| --- | --- |
| Subject and binding | Immutable subject ID, approved account and current UserBinding UID. An effective MediaMTX Role or `superadmin` supplies integration assignment. |
| Effective Roles | Core-resolved direct and Group-derived Role names and UIDs. This integration maps them to read, publish, sharing and control permissions. No local Group inheritance. |
| Revision | Opaque revision that covers User, Group ancestry and Role assignment changes. |
| Freshness | Authoritative evaluation time and expiry, or a bounded fresh authorization read. A watch connection alone is insufficient. |
| Account deadline | Absolute general account deadline if Core has one, or an explicit statement that Core has none. Missing data is not unlimited approval. |

Deny unknown, missing, malformed or stale Role projections. A media decision
intersects this integration's Role rules with the grant's exact stream, one
action, allowed protocols, expiry and persisted revocation state. Equality
with any deadline means expired.
Use injected time in pure policy tests. Do not invent a clock-skew allowance.
The production adapter must settle clock tolerance and freshness with Core.
Keep the plan's 15-second freshness and 30-second removal targets as unverified
acceptance targets.

The integration operator is the sole integration-status writer. The API writes
grant intent to Secrets. Core supplies effective Roles; this integration
decides access and assignment from them. Readiness must match the binding
generation, Role projection revision, and current MediaMTX instance and
configuration. Old `Synced=True` is insufficient.

The user supplied `../opendefence_core_crds.yaml` during M2, SHA-256
`105bede6c1dd9f77c9effb6d8525d5882822a6ca67c75f14f2f59f64f106a747`.
It supersedes the prototype assumptions above. `platform.opendefence.fi/v1alpha1`
UserBinding is an integration-owned observation: the integration creates one
per User in its own namespace and writes `Synced`. Core only watches it. Spec
contains `userRef.name`. Status contains `conditions` and `observedGeneration`.
Do not write account IDs, callsigns, policy revisions or credential references to
status: the structural schema would prune them. Resolve display data from User;
keep grant and policy metadata in bounded integration Secrets. Binding existence
or `Synced=True` is not an access assignment or a fresh policy projection.

Core owns user mTLS authentication and any ForwardAuth configuration. The
integration consumes one injected user UUID header, with configurable default
`X-OpenDefence-User-UUID`. The parser accepts canonical UUID text or compact
Base64URL, matches header names without case, and rejects duplicate headers,
joined values and aliases. Preserve header pairs until validation; a dictionary
that drops duplicates is unsuitable. Do not inspect client certificates, Basic
credentials or legacy certificate-DN headers to authenticate REST callers.
Core's edge must remove client-supplied identity headers and inject the verified
UUID. Limit the integration listener to that trusted route. Header parsing alone
does not prove authentication, policy freshness or access. Ingress enforcement
is still a deployment check, not a second authentication server in this repo.

Read Core's repository at `af0375a41aad095ce464ba588544930d0a486793`:
[source](https://github.com/opendefence/core/tree/af0375a41aad095ce464ba588544930d0a486793).
It is a scaffold at this revision and adds no effective-policy wire contract.

## Grant storage and restart behavior

Use schema-versioned, namespace-scoped Secrets. Each grant record contains its
random `g_` ID and username, subject and binding UID, canonical stream, action,
protocols, creation and expiry times, normalized request digest, idempotency-key
digest, password and monotonic revocation marker. Use at least 128 random bits
for each ID and password. Rotation creates a new ID. Scope and expiry do not
change in place. Keep credentials and request keys out of labels and status.

Derive a DNS-safe Secret name from a length-delimited subject and idempotency-key
digest. Atomic create selects the winning password. On `AlreadyExists`, read
the stored record, verify subject and request digest, and return that grant.
A changed request returns 409. Never return a newly generated losing password.
Retries recheck current authorization and never reactivate a revoked record.
Use resource-version preconditions for updates. A caller's stale `If-Match`
remains a failed precondition after any retry.

Initial integration limits for implementation: eight active or pending grants
per subject, 64 total retained records per subject, a maximum lifetime of 24
hours, and a 24-hour idempotency retry window from creation. Eight grants cover
one publisher and reader for each initial tool. Core approval can only shorten
lifetime. No automatic grant is issued on a read or UI refresh. Advertise the
configured limits. These defaults do not assert a strict security profile.

A list-then-create count cannot enforce quotas under concurrent API requests.
Use one bounded reservation Secret per subject, updated with resource-version
preconditions before creating an individual grant. Store only grant IDs, request
digests, reservation deadlines and cleanup-complete markers there, keyed by the
idempotency-key digest. Concurrent equal keys reuse one reservation; changed
payloads conflict. Pending reservations count against the active quota. After
persisted denial and confirmed session removal, mark the reservation complete
to release active capacity; its entry still counts against the retained limit.
A retry resumes a reserved creation. Orphan reservations can expire only
after their original grant expiry; a delayed creator must recheck that expiry
before creating a credential. Do not release a live reservation by a short
timeout. This is credential bookkeeping, not a duplicate user database.

Persist denial before draining sessions. The operator scans every relevant
session-list page on each MediaMTX instance and matches the grant username.
Treat an absent session as successful removal; repeat the scan to catch admission
races. Rebuild observations after restart. Keep cleanup incomplete on dependency
failure. Grant status must distinguish denial from completed removal.

Keep a tombstone until session removal is confirmed and both the original grant
expiry and retry window have passed. Keep the revoked grant record readable
while cleanup is pending. After confirmed session removal, mark the reservation
complete to release active quota. Retain the revoked grant record and the
reservation entry for retries. Delete them only after the retention window,
with UID and resource-version guards. An interrupted cleanup may temporarily
consume quota; it must never restore access. Stop new issuance when retained
records fill the bound. Do not discard unresolved revocations to make space.
Explicitly reconcile cross-namespace cleanup; do not use invalid owner
references.

These storage rules require concurrent-create, conflict, restart and cleanup
tests in M2. The spike does not prove them. Kubernetes RBAC must exclude writers
that bypass these invariants, and Secret encryption remains a base requirement.

## Media boundary and release gates

Use external HTTPS authorization and `authHTTPExclude: []`. Ordinary media grants
cannot authorize `api`, `metrics` or `pprof`. Permit these actions only for a
current Core `superadmin` with a separate control credential or for this
integration's own service credential. The service credential must be available
before reconciliation starts. Enable `pprof` only when it is needed and apply
the same authorization rule. Require a username for each credential; accept the
upstream duplicate password/token representation. A token
alone has no reliable grant-to-session mapping in this design.

Upstream reports `rtsp` for RTSPS and `rtmp` for RTMPS. Treat them as secure public
protocols only when the observed deployment enforces strict TLS and disables
the corresponding plaintext listener. Unknown configuration is not evidence
of transport security. A callback success is not proof of a connected client.

The HTTP prefix contract is blocked: StripPrefix alone fails the live redirect
test. Require a base-approved response rewrite or an agreed upstream change.
A separate configured media origin is an alternative deployment decision, not
an implicit hostname convention. Do not add a sidecar or payload proxy.

Strict outage enforcement remains false. The callback cannot expire an existing
HLS session, and callback unavailability also blocks authenticated control calls.
No mechanism has been selected that ends sessions by an absolute deadline when
reconciliation or control is unavailable. Do not advertise that guarantee.

The draft also lacks an explicit self-use versus sharing purpose on grants.
Do not use a free-text label as authorization. Settle the typed purpose and the
sharing flow before implementing grant issuance; a self-use bearer password
can still be copied. Keep archive playback, workload identities, client profile
claims and final UI federation gated. TAK profiles and sibling integration work
remain deferred by the user's instruction.

M2 can start canonical identity, paths, grant scope and pure policy regression
tests against these semantic inputs. The supplied CRD now permits binding adapter
implementation. Production policy reads,
public authentication, issuance and public media routing require the listed
contract decisions. Do not convert an internal test fixture into a Core schema.
