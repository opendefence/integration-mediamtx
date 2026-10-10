# Integration MediaMTX: audit and implementation plan

Date: 2026-10-10

Target repository: **`opendefence/integration-mediamtx`**

Proposed Python package: **`odintegration_mediamtx`**

Status: planning document. No repository or deployment was changed.

Implementation update, 2026-10-10: repository foundation work has started.
The user deferred TAK support until the related sibling repository work is
complete. This includes TAK video XML profiles and cross-repository integration.
See `docs/implementation-status.md` for current work and evidence.

## 1. Recommended result

Build a small Kubernetes integration around the upstream MediaMTX image. Keep external HTTP authorization, stream discovery, client configuration and scoped sharing. Replace the RASENMAEHER callbacks and payload proxy with Core reconciliation and a resource API.

**Do not add a user database.** Core owns User identity and effective access. Report provisioning conditions and observed generation in **`UserBinding.status`**, as permitted by the supplied CRD. Read account identity and callsign from Core User. Store credentials and bounded grant metadata in namespace-scoped Kubernetes Secrets. Do not put passwords, tokens or credential-bearing URLs in status.

Run the API, operator and MediaMTX in separate Pods. Use one Python package for the API and operator. Use the same policy functions in both processes. Do not add sidecars, Redis, a message broker or a workflow engine.

Use Simplified Technical English for documentation. Use Ponytail and Caveman during implementation. Make small conventional commits with concise subjects. Section 13 defines mandatory model-switch gates.

## 2. Evidence and scope

**What this repo does:** `rmmtxauthz` checks MediaMTX authentication requests against local user and product records. It also supplies credentials, stream URLs and a federated UI. The UI prepares configurations for TAK, UAS Tool, OpenTAK ICU, GoPro and VLC.

Assumed load: fewer than a few hundred enrolled identities. Media traffic passes through MediaMTX, not the Python API.

| Source | Audited revision or role |
| --- | --- |
| Legacy integration [R1] | `1e2d8fea4c80c4391f27d25ed07d57205e39bd9d`, `main`; package version `1.6.5+260921`. |
| Legacy runtime fixture [R2] | MediaMTX `1.12.3`; PostgreSQL `12`; MediaMTX uses internal authentication in these tests. |
| Upstream comparison [R3] | MediaMTX `v1.21.2`, commit `914e39535ece709919ac325aaeed98d394ed9093`. Candidate baseline, not a tested deployment recommendation. |
| Core architecture | Supplied `rasenmaeher-core-architecture-handoff(1).md`, dated 2026-10-10. |
| Development foundation [R4] | TAK operator prototype, commit `b332e527c7dedf5e3f0a972b792c7d697dcace6b`. |

Reviewed: Python routes, models, settings, control client, startup, build configuration, CI and relevant tests. Traced UI credential retrieval, publishing instructions, playback and exported profiles. Checked upstream authorization, session records, disconnect routes and SRT handshake ordering.

Two policy failures were reproduced locally. The probe executed unchanged legacy functions with in-memory dependencies. This verifies function behavior, not deployed network reachability. Podman and Kind were unavailable here. No live media session or mobile client was tested.

## 3. Ponytail audit

### Must fix

1. **A read-only credential gains admin access.** [R5]
   - **What:** Each user has a main password and a shareable read-only password.
   - **Problem:** `check_rmuser()` returns success for admins before applying read-only restrictions. The probe returned `204` for `api` and arbitrary publishing with an admin's read-only password.
   - **Fix:** Intersect credential scope with current principal permissions. Never let a media credential authorize the control API.
   - **If skipped:** Sharing a video credential can also share server administration rights.

2. **Path ownership uses an incomplete prefix comparison.** [R5]
   - **What:** Publishing and read-only sharing use `user_publish_path_rules()`.
   - **Problem:** User `ALPHA` can publish or read `live/icu/ALPHA2`. The probe returned `204` for both cases.
   - **Fix:** Parse canonical path segments. Match the complete owner segment and the permitted channel.
   - **If skipped:** Users with overlapping names can cross stream boundaries.

3. **Identity still depends on callsign.** [R6]
   - **What:** Direct routes read certificate CN as a username. Proxy routes select users by callsign.
   - **Problem:** `user_updated()` finds the UUID but never updates an existing username. UUID-only certificate CNs also fail this lookup model.
   - **Fix:** Bind identity, grants and stream ownership to the immutable Core User ID. Read callsign as display metadata.
   - **If skipped:** Renaming a user breaks credential retrieval or leaves old names active.

4. **Secret handling crosses too many interfaces.** [R5, R7, R8]
   - **What:** Stream lists include full credentials. Several exported reader profiles use the user's main password.
   - **Problem:** Main passwords also permit publishing. Log redaction hides `password` but leaves the raw query, which can contain RTMP credentials. Configuration debug output also contains plain secret fields.
   - **Fix:** Return secret-free stream metadata. Issue scoped reader grants. Log an explicit allowlist of fields and redact all generated connection material.
   - **If skipped:** Shared files, logs or copied URLs can disclose broader access than the reader needs.

5. **Lifecycle callbacks can report incomplete work as success.** [R6, R7]
   - **What:** User creation commits a database row, then patches SRT defaults.
   - **Problem:** A retry can hit unique constraints. Callers ignore the patch helper's `False` result. Revocation only marks the database record deleted; it does not disconnect active sessions.
   - **Fix:** Reconcile current Core intent. Separate grant denial, configuration readiness and session removal.
   - **If skipped:** Retries fail after partial success, and existing media access can outlive revocation.

### Should fix

6. **The new architecture makes the local identity layer redundant.** [R6, R9]
   - **What:** SQL models, database initialization and event callbacks duplicate platform identity state.
   - **Problem:** They require a database, local file locking and a second user lifecycle. The file lock also does not coordinate separate Pods.
   - **Fix:** Use Core resources, integration-owned binding status and Secrets. Remove the SQL layer and callback routes.
   - **If skipped:** The new integration retains the old synchronization and deployment costs.

7. **SRT configuration changes depend on unrelated user events.** [R6, R7]
   - **What:** Creation, promotion and callsign updates patch global SRT passphrases.
   - **Problem:** Configuration repair is coupled to those events. All paths also share deployment-wide read and publish passphrases.
   - **Fix:** Reconcile path configuration independently. Use separate read and publish passphrases per canonical stream path.
   - **If skipped:** Configuration recovery remains unreliable, and a disclosed passphrase affects unrelated streams.

8. **The same connection contract exists in Python and TypeScript.** [R7, R8]
   - **What:** Both layers construct URLs. The UI also invents an `mtx.` hostname and fixed ports.
   - **Problem:** Path routing and port changes must update several builders. A generated URL is treated as proof that a stream is live. Replacing slashes with hyphens also produces ambiguous UI identifiers.
   - **Fix:** Define typed stream metadata and server-produced connection profiles. Use stable stream IDs and actual MediaMTX readiness.
   - **If skipped:** The UI can advertise inactive streams or unusable connection details.

9. **Tests do not verify the deployed authentication chain.** [R2, R10]
   - **What:** Tests exercise the Python callback directly and patch a real MediaMTX control API.
   - **Problem:** The fixture uses `authMethod: internal`. It does not establish real media sessions through external HTTP authorization. The prefix and admin-sharing failures are not covered.
   - **Fix:** Keep focused policy tests. Add real publish, read, denial and disconnect tests with the selected MediaMTX image.
   - **If skipped:** Passing tests still leave protocol authentication unverified.

10. **Container startup carries obsolete platform plumbing.** [R11]
   - **What:** Startup edits `/etc/hosts`, invokes `kw_product_init` and copies UI files to a shared volume.
   - **Problem:** These steps depend on the previous Docker deployment and product registration flow.
   - **Fix:** Use Kubernetes DNS, mounted configuration, Core integration registration and packaged UI assets.
   - **If skipped:** The new deployment still needs old hostnames, initialization files and shared-volume behavior.

**Verdict:** Keep the media workflows. Replace the identity, credential scope and lifecycle boundaries first.

**Lean:** About 580 legacy lines can be retired from the reviewed SQL and callback/proxy modules. At least three direct dependencies can go: `sqlmodel`, `psycopg2-binary` and `filelock`. This is deletion scope, not a promised net reduction after new reconciliation code.

**Not checked:** Complete UI component coverage, private `libpvarki` internals, production ingress configuration, real clients and live failure recovery. This is not a full penetration test.

## 4. Keep, replace and defer

| Capability | Decision |
| --- | --- |
| Publish and read streams | Keep RTSPS, RTMPS, SRT and HTTP-based playback. Advertise only tested protocols. |
| Browser player | Keep HLS. Verify native Safari playback separately from `hls.js`. Gate WebRTC on the network tests. |
| Sharing | Keep scoped read access. Use an independently revocable grant for each intended sharing purpose. |
| Client setup | Keep useful OpenTAK ICU, GoPro, UAS Tool, TAK video XML and VLC profiles. Validate each format with a real client. |
| Product interoperability | Keep explicit service grants for approved integrations. Remove the rule that products can perform every action. |
| User CRUD and admin callbacks | Remove. Consume Core identity and permission state. |
| Direct/proxy route duplication | Replace with one authenticated resource API. Remove the RASENMAEHER payload proxy. |
| Product descriptions | Move registration and UI metadata to the versioned Core Integration Manifest. |
| Recording and playback archives | Preserve a distinct `playback` authorization action. Do not add recording storage or an archive UI without a deployment requirement. |
| Extra services | Defer transcoding, cameras pulled by URL, CDN mode, MoQ and media clustering. They are not required for parity. |

Normal users currently read any stream. Carry this forward only through an explicit Core media-read permission. Sharing a user's own stream remains narrower. Neither behavior should emerge from a password type or a global admin flag.

## 5. Ownership and persistence

| State | Owner and location |
| --- | --- |
| Identity, callsign, approval, roles and groups | Core User and shared policy resources. |
| Integration assignment and desired access | Core effective-policy projection; binding existence does not grant access. |
| Provisioning observation | Integration creates `UserBinding.spec.userRef` and owns its status. |
| Media grant, password, expiry and revocation marker | Integration namespace Secret, using one versioned schema. |
| SRT read/publish passphrases | Integration namespace Secrets, keyed by canonical stream path. |
| Non-secret workload settings | ConfigMaps and deployment manifests. |
| Current streams and sessions | Read from MediaMTX. Keep only bounded in-memory snapshots. |
| Audit history | Structured platform logs. Do not grow binding status into an event log. |

The supplied `../opendefence_core_crds.yaml` defines `platform.opendefence.fi/v1alpha1`. Integrations create one namespaced UserBinding per User. Core watches these observations and does not admit or reconcile them. The binding spec contains only `userRef.name`; it is not a Core assignment record. Status permits only conditions and observed generation. Read identity and callsign from the referenced User. Keep policy and credential metadata in bounded integration Secrets. Extra status properties would be pruned by Kubernetes.

Use the shared status shape:

```yaml
status:
  observedGeneration: 7
  conditions:
    - type: Synced
      status: "True"
      observedGeneration: 7
      reason: Reconciled
      message: Provisioning is complete.
      lastTransitionTime: "2026-10-10T12:00:00Z"
```

The operator is the only writer of integration status. The API creates or revokes grant Secrets. It does not use binding status as a command queue. The operator reads those records and reports the observed result. Write Secret changes with resource-version preconditions.

Use the Core UUID encoding and recovery contract when it is settled. Do not silently replace Core's current `metadata.uid` model. Require a migration mapping if restore assigns new IDs.

Watch permission changes that affect bindings. Group ancestry and role changes can alter access without a User edit. Use Core's effective-policy contract; do not implement a second inheritance algorithm.

Do not create another CRD for each REST resource. At this scale, binding status and bounded Secrets are sufficient. Set grant quotas, expiry and garbage collection. Reconsider storage only if measured write volume exceeds this design.

## 6. Identity, paths and credentials

### Stable stream ownership

Use canonical paths such as `live/{tool}/{userId}`. Retain approved subordinate channels as complete path segments. Keep `icu`, `gopro`, `uas` and `ipcam` as initial tool values.

Callsign is display metadata. A callsign change must preserve path, stream ID, grant and password. Update the UI label and profile display fields. Already imported client aliases might need a new profile import.

Define one path parser. Reject empty segments, dot segments, encoded separators and invalid owner IDs. Never use a bare `startswith()` ownership check. Set length limits that leave room for credentials inside SRT's Stream ID limit.

Proposed stream ID: a versioned Base64URL encoding of the canonical path. Treat it as opaque in clients. Decoding an ID does not authorize access. This avoids a separate stream-ID database and ambiguous UI slugs.

### Scoped grants

Use short, randomly generated media credentials with at least 128 bits of entropy. Use protocol-safe characters. Prefer one action and one exact stream per grant. Support explicit subtree scope only for a confirmed multi-channel client requirement.

Give every grant generation a unique media username, such as `g_<opaque-id>`. Map it to the owning UserBinding through its Secret. Do not use callsign as the media username. Distinct usernames let session inspection distinguish old and new generations.

An authorization decision requires all of these checks:

1. The credential matches and has not expired or been revoked.
2. Its owner remains approved and assigned to the integration.
3. Core policy is fresh and permits the requested action and stream.
4. The grant scope permits that action, stream and protocol.
5. Any absolute approval deadline has not passed.

Use constant-time secret comparison. Keep raw secrets only where repeated profile delivery requires them. Apply namespace RBAC and the platform's Secret encryption policy. Do not access users' private certificate keys; MediaMTX credentials do not require them.

Sharing a reader grant transfers a bearer credential. It does not identify each recipient. Require an explicit sharing permission and expiry. Label shared profiles clearly. UAS Tool must receive separate publishing and observer credentials.

### SRT passphrases

MediaMTX has one publish passphrase and one read passphrase per path. It does not supply a separate encryption passphrase for every reader. Use path-level Secrets and enforce each reader's grant through HTTP authorization. [R12]

Revoking one reader grant need not rotate the path passphrase. Rotate that passphrase when disclosure policy requires it. All affected readers then need updated profiles. Test whether configuration changes disconnect current sessions.

The HTTP authorization callback happens before the final SRT passphrase check. A successful callback is not proof of a working connection. [R12, R13]

Treat Stream ID disclosure as a protocol test requirement. Do not assume media payload encryption protects every handshake field. Use an approved tunnel where the strict profile requires additional protection.

## 7. Authentication method and revocation

### Use external HTTP authorization first

Retain MediaMTX's HTTP callback. It supports legacy username/password clients and current Core policy checks. Native JWT mode avoids a callback per authentication, but adds token, key and revocation coordination. Do not implement both modes for the first release. [R14]

Use a private endpoint such as `POST /internal/mediamtx/auth`. This is an upstream protocol adapter, not a public REST resource.

- Accept the selected MediaMTX version's JSON fields. These include `token`, `userAgent` and a nullable session ID.
- Return `204` only for an allowed request. Return `401` for a missing-credential challenge and `403` for denied access.
- Fail closed on malformed input, unsupported actions, unavailable policy or secret-read failures.
- In current upstream code, `token` can duplicate the password. Normalize this correctly; do not reject valid Basic authentication merely because both fields exist.
- Require a non-empty canonical grant username for media access. This preserves session-to-grant mapping. Do not enable token-only media access without another reliable mapping.
- Set `authHTTPExclude: []`. Explicitly scope control credentials to `api` and monitoring credentials to `metrics`. Keep `pprof` disabled.

The callback request contains media credentials, not proof of the calling workload. Restrict its Service and ingress with network policy. Protect credentials in transit with verified TLS. Validate certificate trust or a managed fingerprint against the selected image. Do not assume the callback supports client certificates or custom authentication headers.

Core owns user mTLS authentication and any ForwardAuth configuration. This integration only consumes the injected user UUID header. Use `X-OpenDefence-User-UUID` as the configurable default. Require one canonical UUID text or compact Base64URL value; reject duplicate and joined values. Core's edge must strip client-supplied identity headers and inject the verified value. Restrict the integration listener to that trusted route. The integration does not implement ForwardAuth or parse client certificates.

### Revoke current sessions as well as future access

MediaMTX `v1.21.2` exposes session or connection `user` fields and disconnect operations. HLS also has sessions and a disconnect endpoint. Use the exact API routes for the selected version. [R15]

| Protocol | Candidate upstream disconnect route |
| --- | --- |
| HLS | `POST /v3/hls/sessions/kick/{id}` |
| RTSP / RTSPS | `POST /v3/rtsp/sessions/kick/{id}` / `/v3/rtsps/sessions/kick/{id}` |
| RTMP / RTMPS | `POST /v3/rtmp/conns/kick/{id}` / `/v3/rtmps/conns/kick/{id}` |
| SRT | `POST /v3/srt/conns/kick/{id}` |
| WebRTC | `POST /v3/webrtc/sessions/kick/{id}` |

On revocation or expiry, persist the denial first. Then list all relevant pages and disconnect matching sessions. Match the grant generation, not callsign or IP. Include the MediaMTX instance when handling session IDs.

Repeat the scan to catch connections accepted during the race. Treat an already absent session as success. Keep a revocation record until cleanup is confirmed. Rebuild observations after an operator restart; a callback ledger is not required.

Current HLS sessions use cookies or query session identifiers after initial authorization. Do not assume every segment causes a fresh authorization check. Test copied session URLs, cookies and reconnect attempts after revocation. [R16]

Proposed healthy-system targets: policy freshness within 15 seconds; denial and session removal within 30 seconds. These are acceptance targets, not measured guarantees. Core must define how the integration proves freshness. Watch connectivity alone is insufficient.

If the operator or control API fails, existing sessions might continue. Do not claim strict deadline enforcement in that state. Strict-profile release requires an agreed fail-closed mechanism and outage tests. Do not hide this limitation with a sidecar.

Media credentials must not extend an absolute Core approval deadline. A MediaMTX connection also does not prove use of a new Core certificate. Core remains responsible for certificate activation and retirement. If media passwords rotate, confirm the new generation through an established session before retiring the old grant under that policy.

## 8. Proposed public API contract

Base path: **`/integrations/mediamtx/api/v1`**. Route directly through Traefik to the integration API. The names below are a proposed contract, not a claim that Core already supplies these schemas.

| Method and resource | Result |
| --- | --- |
| `GET /capabilities` | Enabled protocols, supported profile formats and relevant limits. No secrets. |
| `GET /me` | Stable identity, callsign, effective media permissions, binding state and default publishing destinations. |
| `GET /streams` | Authorized stream metadata, opaque cursor and explicit live state. No passwords or secret URLs. |
| `GET /streams/{streamId}` | One authorized stream. Use the stable ID in UI routes. |
| `POST /access-grants` | Create a scoped credential resource. Return `201`, `Location`, expiry and readiness state. |
| `GET /access-grants` | List the caller's grant metadata. Privileged views require explicit permission. |
| `GET /access-grants/{grantId}` | Grant scope, expiry, revocation and cleanup state. No secret by default. |
| `GET /access-grants/{grantId}/connection-profile` | Deliver the authorized connection representation or file. Never create or rotate credentials during GET. |
| `DELETE /access-grants/{grantId}` | Persist revocation. Return `202` and the grant `Location` while sessions drain; repeated calls remain safe. |

Use a new grant for credential rotation. Avoid mutable scopes and a separate rotate action. Keep a short tombstone so retries and session cleanup can identify the old generation.

Example creation request:

```json
{
  "streamId": "<opaque stream ID>",
  "actions": ["read"],
  "protocols": ["rtmps"],
  "expiresAt": "2026-10-10T18:00:00Z",
  "label": "UAS observer"
}
```

The server chooses the owner and credential. It rejects unauthorized scope or an expiry beyond the approval deadline. Service-to-service callers use the agreed Core workload identity contract, not an arbitrary caller-supplied owner.

Contract rules:

- Return `application/problem+json` errors with stable problem types.
- Use opaque ETags and `If-Match` where a caller changes existing state. Preserve preconditions across retries.
- Support `Idempotency-Key` on grant creation. Derive the Secret name from the principal and key digest. Use atomic Kubernetes create. On `AlreadyExists`, compare the stored request digest. Repeated requests return the same grant; changed payloads return `409`. Set a documented retry window and retain its tombstone.
- Bound grants per principal and expiry history. Reuse a valid grant for UI refreshes instead of creating one on each stream poll.
- Use `Cache-Control: no-store` for credentials and profiles. Use safe filenames and correct MIME types. Escape XML, URL and playlist fields by format.
- Authorize every profile retrieval. Grant possession or grant ID alone must not authorize retrieval. No anonymous package-download endpoint is required for parity.
- Distinguish `pending`, `ready`, `revoked` and failed cleanup. Report `409` when the profile is not ready. Report `503` for a dependency outage.
- Use actual MediaMTX `ready` state for live streams. Follow pagination and filter before disclosure. Do not turn an upstream error into an empty successful list.
- Configure external origins, ports and prefixes explicitly. Never mutate global settings from the first request's `Host` header.

The profile representation contains structured endpoints and authentication fields. Generate native-client URLs only when required. Use browser headers or a tested session flow for playback. Do not rely on embedded `user:password@host` URLs for browsers.

Legacy mapping: `/direct/*` and `/proxy/*` become the resources above. `/srt_default` disappears; an authorized profile contains only its required path passphrase. `/users/{created,updated,promoted,demoted,revoked}` disappears. `/interop/add` and `/interop/authz` become binding reconciliation and scoped service grants.

Do not wrap MediaMTX's whole control API. Keep its verb-based upstream contract inside one small adapter. Public API redesign does not require an upstream API fork.

## 9. Kubernetes deployment and routing

Use the upstream image by digest. Start with one MediaMTX replica. Arbitrary replicas behind a Service do not provide shared stream state or session placement.

The operator owns generated path configuration and repairs drift. Keep desired settings in ConfigMaps and Secrets. MediaMTX control API changes are runtime state; reapply them after restart. Use one configuration writer. Avoid simultaneous file and API ownership of the same fields. [R17]

The control API has a broad `api` permission. It does not supply separate list-only and configuration-write permissions through this callback. Restrict its callers to trusted workloads. Do not expose their control credentials through the public API.

Keep Secret references namespace-scoped. Define explicit cleanup for cross-namespace bindings; do not rely on invalid cross-namespace owner references. On removal, deny grants and drain sessions before deleting Secrets or the operator. Restore Core identity mappings before restoring grants. Do not restore revoked grants as active.

Establish default-deny authorization before publishing or reading is enabled. Load the callback's management credential before querying the control API. Keep liveness independent from Core availability. Readiness must report stale policy and incomplete configuration without creating a startup dependency loop.

| Traffic | Exposure |
| --- | --- |
| Integration REST and UI | Same origin, distinct paths; Core HTTP authentication where required. |
| HLS | HTTPS route to the MediaMTX HLS Service. Native readers authenticate with scoped media grants. |
| WHIP/WHEP signaling | HTTPS route to the WebRTC Service. Test session `Location`, PATCH and DELETE. |
| RTSPS / RTMPS | Explicit TCP Services or TCP ingress. HTTP path routing does not route these protocols. |
| SRT | Explicit UDP exposure. Its Stream ID selects the media path. |
| WebRTC media | Advertised ICE addresses and reachable UDP/TCP ports; optional separately deployed TURN. |
| Control API / callback / metrics | Internal Services with distinct access policies. No public control API route. |

Proposed HTTP media prefixes: `/integrations/mediamtx/media/hls/` and `/integrations/mediamtx/media/webrtc/`.

Upstream requires request-prefix removal and response `Location` rewriting for subfolder exposure. A Traefik `StripPrefix` rule alone is insufficient. Verify the selected Traefik version's solution before fixing the route contract. Use a base-approved middleware or an upstream change if required; do not silently add an Nginx sidecar. Test HLS cookies, relative playlists and all WHIP/WHEP session URLs. [R18]

Media grants must work for native clients that lack Core mTLS certificates. Do not put unconditional Core ForwardAuth on those media routes. Keep their MediaMTX authorization active. For the browser UI, test scoped Basic credentials with `hls.js` and the upstream HTTPS session flow. Gate Safari support on real native playback.

WebRTC signaling success is not media success. Test ICE connectivity through the actual Kubernetes exposure. Do not rely on public STUN or TURN services in an offline deployment. [R19]

Disable automatic mesh sidecar injection for these workloads under the no-sidecar requirement. Coordinate an approved transport-security alternative with `base`. Do not assume NetworkPolicy encrypts traffic or that installed Linkerd means these Pods are meshed.

Standalone use remains Kubernetes-native: install the required base/Core subset and this integration. Do not rebuild a second standalone identity system. Recording, when enabled, requires an explicit PVC, retention policy and restore procedure.

## 10. UI and TAK boundary

The old UI has useful flows, but its host contract must change. Remove hard-coded RASENMAEHER proxy routes, `mtx.` hostname derivation and credential-bearing catalogue data.

Keep an isolated UI harness with API fixtures. Test stream listing, playback, scoped sharing and profile downloads there. Final module-federation integration depends on Core's user/session, navigation, locale and permission contracts.

Generate connection details once in the backend. Let the UI render and download them. Scope query caches to the active identity and clear secrets on identity change or logout.

Keep TAK video-feed XML separate from TAK certificate ZIPs. `integration-mediamtx` owns media endpoints and media grants. `integration-tak` can consume a narrow profile contract when packaging video configuration. Do not create a dependency on TAK JNI or copy TAK certificate-rotation behavior into this integration.

Use deterministic feed identifiers where client update behavior supports them. Test import-over-existing behavior. The old generator creates a new random TAK feed UID on every export; do not assume that updates an existing feed.

## 11. Migration and acceptance

### Migration

1. Inventory required clients, protocols, service integrations and existing channel suffixes.
2. Map legacy `rmuuid` values to Core User IDs. Stop on ambiguous mappings; do not infer identity from callsign.
3. Reconcile bindings and stable paths in the new deployment.
4. Issue fresh scoped credentials and client profiles. Do not import global admin behavior or deployment-wide SRT defaults.
5. Test a small set of real publishers and readers before cutover.
6. Disable legacy authorization and disconnect old sessions at the agreed cutover point.
7. Retain only the approved audit and rollback material. Do not leave a parallel legacy endpoint accepting revoked credentials.

The default migration changes client paths and credentials. If temporary aliases are required, bind each alias to a User ID. Give aliases an expiry and explicit authorization. Do not reuse old callsigns as durable identities.

### Required evidence

| Test group | Acceptance case |
| --- | --- |
| Policy | Reproduce both audited failures as denied requests. Test unknown actions, missing credentials and malformed paths. |
| Core changes | Rename callsign without changing paths or credentials. Remove access through a group change without editing the User. |
| Persistence | Restart API and operator during grant creation/revocation. Repeated requests create no duplicate grants. |
| Real protocols | Publish and read with RTSPS, RTMPS and SRT. Test wrong grant, wrong action, wrong path and wrong passphrase. |
| Sessions | Revoke each protocol during streaming. Test admission races, reconnects, paginated lists and operator restart. |
| HLS | Test `hls.js`, native Safari, redirects, cookies, copied session URLs and grant expiry. |
| WebRTC | Test WHIP/WHEP creation and cleanup, ICE, NAT, UDP/TCP exposure and the supported offline network profile. |
| Profiles | Import TAK XML, UAS Tool, ICU and VLC files. Verify escaping, stable identifiers and overwrite behavior. |
| Faults | Stop Core access, Secret watches, the callback, operator and control API separately. Measure denial and cleanup delays. |
| Secrets | Scan captured logs, API metadata, binding status, traces and UI caches for test credentials. |
| Deployment | Install, restart and upgrade with internet egress blocked. Verify image loading, DNS, trust and optional data restore. |

Run live tests with Podman and a dedicated Kind cluster. Pin node images and load application images explicitly. Verify rootless networking before diagnosing UDP failures as application bugs. Cleanup must target only owned resources. [R20]

## 12. Repository and delivery plan

Copy the prototype's development foundation: Python 3.14, `uv`, `prek`, Ruff, strict `pyrefly`, pytest and task entry points. Copy useful CI patterns, not TAK dependencies. Pin Cloudcoil and shared CI actions to reviewed revisions. Remove private legacy package-index requirements where the new code no longer needs them.

Use `arc-runner-set` where the existing build/publish workflow requires it. Validate BuildKit access and both target architectures. Keep Snyk explicitly disabled until the new organization is configured. Never report the disabled job as a successful scan.

Build API/operator images and the UI assets reproducibly. Include runtime images, manifests and tests in the release compatibility record. Package offline dependencies through Zarf. Keep publishing credentials out of untrusted pull-request jobs.

Deliver in this order:

1. Repository foundation and a concise decision record.
2. Core status/permission adapter and the proposed OpenAPI 3.1 contract.
3. Pure policy functions, canonical paths and regression tests.
4. Binding reconciliation, grant Secrets and private HTTP authorization.
5. MediaMTX workload, path configuration and internal control adapter.
6. Public catalogue and connection-profile API.
7. Session revocation and fault tests.
8. UI fixtures and tested client profiles.
9. Core federation integration after its upstream contract is ready.
10. Offline release, migration runbook and final audit.

Each step must produce a reviewable result. Do not implement a generic framework for later integrations.

## 13. Local agent instructions and model gates

This section applies when implementation starts. It does not require a model switch merely to read this plan.

Load these skills before code changes:

- **Ponytail**, full mode. Run `ponytail-review` before each completed change is committed. Run `ponytail-audit` at final review.
- **Caveman**, for concise chat. Use normal grammatical STE in documentation. Keep commit messages concise and conventional.
- Read the actual skill files. If a required skill is unavailable, pause and ask the user to provide or enable it.

Verified skill sources: [Ponytail, `9b58c1f`](https://github.com/DietrichGebert/ponytail/tree/9b58c1ffb790c075ca32e70a89cf1d80588f4abf) and [Caveman, `2e08b91`](https://github.com/JuliusBrussee/caveman/blob/2e08b9177c07bb7249a8a2d1a6758e5db281d002/skills/caveman/SKILL.md).

| Gate | Model and effort | Work and exit evidence |
| --- | --- | --- |
| M0 | `gpt-6.1-sol` / `medium` | Inspect local instructions and runtime. Create the repository foundation and scoped Kind workflow. |
| M1 | `gpt-6-astra` / `xhigh` | Resolve Core policy/status ownership, grant durability, HTTP routing and session expiry. Produce reviewed contracts and a small protocol spike. |
| M2 | `gpt-6.1-sol` / `high` | Implement the agreed API, operator, profiles and tests in small commits. |
| M3 | `gpt-6-astra` / `high` | Review live authorization, rotation and outage evidence. Escalate unexplained behavior to `xhigh`. |
| M4 | `gpt-6.1-sol` / `high` | Fix findings and finish the approved UI adapter. Keep blocked Core UI work explicit. |
| M5 | `gpt-6-astra` / `high` | Perform a fresh final review and Ponytail audit. Check strict-profile claims against measured behavior. |
| M6 | `gpt-6.1-sol` / `medium` | Finish STE runbooks, release records and the implementation handoff. |

Use the model pairs already agreed for this project. [Model reference](https://learn.chatgpt.com/docs/models).

Before every transition, including a downward switch:

1. Save completed work and test evidence. Commit each coherent change separately.
2. Update `docs/implementation-status.md` with the gate, HEAD, remaining work and exact runtime versions.
3. Record skill revisions, image digests, Kind context and test results. Include blocked checks.
4. Verify the active model and effort from session metadata.
5. If the host can switch the active session, switch and verify it.
6. Otherwise, stop before the next stage and use the request below.

> Model gate **[ID]** reached. **[Completed result and test result.]**
>
> The next stage, **[stage]**, requires **[model / effort]** because **[reason]**.
>
> I cannot change or verify the active setting. Please switch to **[model / effort]**, then reply **“Switched; resume [ID].”**
>
> Checkpoint: **docs/implementation-status.md**, **[commit or uncommitted state]**. I am paused before starting that stage.

Resume after verified session metadata or explicit user confirmation. Record which evidence was used. A plain “continue” does not confirm a switch. Ask for an available substitute or explicit waiver if the required pair is unavailable. Do not silently substitute models.

Commit examples: `feat(auth): enforce grant scope`, `fix(paths): match owner segments`, `test(srt): verify revocation`, `docs: add recovery steps`. Keep subjects near 50 characters. Add a body only when it explains a necessary reason or limit.

## 14. Decisions required at M1

| Decision | Recommended starting point |
| --- | --- |
| Core UserBinding schema and writer contract | Supplied CRD: integration creates userRef bindings and writes Synced status; Core observes. Policy assignment remains a separate Core input. |
| Effective-policy freshness | Versioned Core projection with an expiry, or a bounded fresh authorization read. Never duplicate role inheritance. |
| Normal read and sharing scope | Explicit media-read permission; separate permission for bearer sharing. |
| Credential expiry and quotas | Bound every grant by the approval deadline. Set small deployment quotas and garbage-collection limits. |
| HTTP subfolder behavior | Prove Traefik request and response rewriting with the selected MediaMTX version. |
| High-OPSEC outage behavior | Define what ends existing streams when reconciliation or the control API fails. |
| Native clients and Core UI | Agree the supported client matrix. Wait for the host UI contract before final federation work. |

These gaps block their dependent features, not repository setup or isolated policy tests.

## Sources

- **R1 — Legacy baseline:** [repository at audited commit](https://github.com/pvarki/python-mediamtx-rmmtxauthz/tree/1e2d8fea4c80c4391f27d25ed07d57205e39bd9d).
- **R2 — Legacy runtime:** [Compose fixture](https://github.com/pvarki/python-mediamtx-rmmtxauthz/blob/1e2d8fea4c80c4391f27d25ed07d57205e39bd9d/tests/docker-compose.yml), [MediaMTX configuration](https://github.com/pvarki/python-mediamtx-rmmtxauthz/blob/1e2d8fea4c80c4391f27d25ed07d57205e39bd9d/tests/mediamtx.yml).
- **R3 — Upstream baseline:** [MediaMTX v1.21.2 source](https://github.com/bluenviron/mediamtx/tree/914e39535ece709919ac325aaeed98d394ed9093).
- **R4 — Development foundation:** [TAK operator prototype](https://github.com/pvarki/python-tak-operator/tree/b332e527c7dedf5e3f0a972b792c7d697dcace6b).
- **R5 — Authorization findings:** [legacy policy functions](https://github.com/pvarki/python-mediamtx-rmmtxauthz/blob/1e2d8fea4c80c4391f27d25ed07d57205e39bd9d/src/rmmtxauthz/web/mediamtx.py#L19).
- **R6 — Identity and callbacks:** [user lifecycle](https://github.com/pvarki/python-mediamtx-rmmtxauthz/blob/1e2d8fea4c80c4391f27d25ed07d57205e39bd9d/src/rmmtxauthz/web/usercrud.py), [direct routes](https://github.com/pvarki/python-mediamtx-rmmtxauthz/blob/1e2d8fea4c80c4391f27d25ed07d57205e39bd9d/src/rmmtxauthz/web/userdirect.py), [proxy routes](https://github.com/pvarki/python-mediamtx-rmmtxauthz/blob/1e2d8fea4c80c4391f27d25ed07d57205e39bd9d/src/rmmtxauthz/web/userproxy.py).
- **R7 — Control client:** [SRT configuration and URL generation](https://github.com/pvarki/python-mediamtx-rmmtxauthz/blob/1e2d8fea4c80c4391f27d25ed07d57205e39bd9d/src/rmmtxauthz/mediamtx.py), [application logging](https://github.com/pvarki/python-mediamtx-rmmtxauthz/blob/1e2d8fea4c80c4391f27d25ed07d57205e39bd9d/src/rmmtxauthz/web/application.py).
- **R8 — UI contracts:** [profile generators](https://github.com/pvarki/python-mediamtx-rmmtxauthz/blob/1e2d8fea4c80c4391f27d25ed07d57205e39bd9d/ui/src/hooks/useStreamPackages/packages.ts), [profile credentials](https://github.com/pvarki/python-mediamtx-rmmtxauthz/blob/1e2d8fea4c80c4391f27d25ed07d57205e39bd9d/ui/src/hooks/useStreamPackages/index.ts), [path helpers](https://github.com/pvarki/python-mediamtx-rmmtxauthz/blob/1e2d8fea4c80c4391f27d25ed07d57205e39bd9d/ui/src/lib/stream-utils.ts), [broadcast wizard](https://github.com/pvarki/python-mediamtx-rmmtxauthz/blob/1e2d8fea4c80c4391f27d25ed07d57205e39bd9d/ui/src/components/BroadcastWizard.tsx).
- **R9 — SQL layer:** [user model](https://github.com/pvarki/python-mediamtx-rmmtxauthz/blob/1e2d8fea4c80c4391f27d25ed07d57205e39bd9d/src/rmmtxauthz/db/user.py), [database initialization](https://github.com/pvarki/python-mediamtx-rmmtxauthz/blob/1e2d8fea4c80c4391f27d25ed07d57205e39bd9d/src/rmmtxauthz/db/dbinit.py), [dependencies](https://github.com/pvarki/python-mediamtx-rmmtxauthz/blob/1e2d8fea4c80c4391f27d25ed07d57205e39bd9d/pyproject.toml).
- **R10 — Tests:** [media authorization tests](https://github.com/pvarki/python-mediamtx-rmmtxauthz/blob/1e2d8fea4c80c4391f27d25ed07d57205e39bd9d/tests/test_mediamtx.py), [lifecycle tests](https://github.com/pvarki/python-mediamtx-rmmtxauthz/blob/1e2d8fea4c80c4391f27d25ed07d57205e39bd9d/tests/test_usercrud.py).
- **R11 — Startup:** [container initialization](https://github.com/pvarki/python-mediamtx-rmmtxauthz/blob/1e2d8fea4c80c4391f27d25ed07d57205e39bd9d/docker/container-init.sh), [entrypoint](https://github.com/pvarki/python-mediamtx-rmmtxauthz/blob/1e2d8fea4c80c4391f27d25ed07d57205e39bd9d/docker/entrypoint.sh), [Dockerfile](https://github.com/pvarki/python-mediamtx-rmmtxauthz/blob/1e2d8fea4c80c4391f27d25ed07d57205e39bd9d/Dockerfile).
- **R12 — SRT implementation:** [upstream connection handling](https://github.com/bluenviron/mediamtx/blob/914e39535ece709919ac325aaeed98d394ed9093/internal/servers/srt/conn.go), [path configuration](https://github.com/bluenviron/mediamtx/blob/914e39535ece709919ac325aaeed98d394ed9093/mediamtx.yml).
- **R13 — SRT protocol guidance:** [Haivision Stream ID access control](https://github.com/Haivision/srt/blob/master/docs/features/access-control.md), read 2026-10-10.
- **R14 — Authentication:** [upstream HTTP/JWT implementation](https://github.com/bluenviron/mediamtx/blob/914e39535ece709919ac325aaeed98d394ed9093/internal/auth/manager.go), [request fields](https://github.com/bluenviron/mediamtx/blob/914e39535ece709919ac325aaeed98d394ed9093/internal/auth/request.go), [official authentication documentation](https://mediamtx.org/docs/features/authentication).
- **R15 — Sessions and control:** [upstream API specification](https://github.com/bluenviron/mediamtx/blob/914e39535ece709919ac325aaeed98d394ed9093/api/openapi.yaml), [registered routes](https://github.com/bluenviron/mediamtx/blob/914e39535ece709919ac325aaeed98d394ed9093/internal/api/api.go).
- **R16 — HLS sessions:** [session implementation](https://github.com/bluenviron/mediamtx/blob/914e39535ece709919ac325aaeed98d394ed9093/internal/servers/hls/session.go), [HTTP request handling](https://github.com/bluenviron/mediamtx/blob/914e39535ece709919ac325aaeed98d394ed9093/internal/servers/hls/http_server.go).
- **R17 — Runtime configuration:** [upstream configuration handling](https://github.com/bluenviron/mediamtx/blob/914e39535ece709919ac325aaeed98d394ed9093/internal/core/core.go).
- **R18 — Subfolder routing:** [official reverse-proxy requirements](https://mediamtx.org/docs/features/expose-the-server-in-a-subfolder).
- **R19 — WebRTC networking:** [official connectivity guidance](https://mediamtx.org/docs/features/webrtc-specific-features).
- **R20 — Local cluster:** [Kind provider selection](https://kind.sigs.k8s.io/docs/user/quick-start/), [rootless Podman requirements](https://kind.sigs.k8s.io/docs/user/rootless/).
