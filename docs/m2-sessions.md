# M2 MediaMTX session removal

The `sessions.py` adapter lists and removes connections by the grant's unique
`g_` username. It uses the v3 routes for HLS, RTSPS, RTMPS, SRT and WebRTC in
MediaMTX 1.21.2. MoQ is pending because its
[session list](https://github.com/bluenviron/mediamtx/blob/v1.21.2/internal/defs/api_moq.go)
has no username.
The routes and list fields match the pinned upstream
[OpenAPI definition](https://github.com/bluenviron/mediamtx/blob/v1.21.2/api/openapi.yaml).
The existing live HLS spike confirmed that a denied callback leaves an active
session usable until its session is kicked.

The caller must persist admission denial before calling `drain_grant_sessions`.
It supplies an authenticated HTTPS client with verified certificate trust for
one MediaMTX instance and the grant's exact enabled protocols. The adapter
reads every page and kicks only matching session IDs. A kick returning `404`
means the session has already disappeared. It requires two successive empty
scans before reporting completion. API failures, malformed data, excessive pages or
sessions that do not drain remain errors; the caller must keep cleanup pending.
The return value counts kick attempts, including sessions already absent.

The [grant retirement adapter](m2-grants.md) persists denial before it calls
this session adapter. Instance discovery, retries after restart and the public
API are still pending.
The package now supplies a private HTTPS control API and a separate service
credential. See [TAK publication](m2-tak.md) for its TLS configuration.
The adapter does not prove a strict deadline when MediaMTX or its control API is
unavailable. TAK feed removal is implemented, but it does not close sessions.

## Callsign session investigation

Date: 2026-10-11. Runtime: MediaMTX 1.21.2 in `kind-opendefence-dev`.
The callsign callback denies new admission after User revocation. Existing
sessions keep running because `mediamtx-operator` does not call session
cleanup. The existing adapter also rejects callsign usernames: it accepts
only the older `g_` grant format.

The private control API can identify and close individual sessions. Its
Transport Layer Security (TLS) connection uses the existing control service
credential. For each route below, use `GET /v3/<route>/list`, select exact
`user` matches, and send `POST /v3/<route>/kick/<id>`.

| Protocol | Route | User identity in the list |
| --- | --- | --- |
| Real Time Streaming Protocol over TLS (RTSPS) | `rtsps/sessions` | `user` |
| Real-Time Messaging Protocol over TLS (RTMPS) | `rtmps/conns` | `user` |
| HTTP Live Streaming (HLS) | `hls/sessions` | `user` |
| Secure Reliable Transport (SRT) | `srt/conns` | `user` |
| Web Real-Time Communication (WebRTC) | `webrtc/sessions` | `user` |
| Media over QUIC (MoQ) | `moq/sessions` | No `user` field |

These routes come from the pinned
[MediaMTX API](https://github.com/bluenviron/mediamtx/blob/v1.21.2/api/openapi.yaml).
Use session identity, not the stream path, to select readers. A revoked User
can read another User's stream. Removing only streams owned by the revoked
User misses those readers. Kicking a publisher also interrupts the viewers
of that publisher's stream.

### Live proof

The probe created two approved test Users and three RTSPS sessions. One User
published and also read the other User's stream. The other User published.
The probe used certificate verification and the packaged private control API.

- The list returned the correct username for the reader and publisher.
- Revocation left both existing sessions running. A new connection failed.
- Two kick requests returned HTTP 200. Both target sessions disappeared and
  both FFmpeg processes exited. Verification took 4.67 seconds, including
  separate Kubernetes exec calls.
- The other User's publisher remained connected.
- A server dry run rejected a callsign change under the current Core CRD.

The first probe used one shared port-forward. Closing one media connection
also closed other forwarded connections, so that run could not prove
isolation. The successful run used separate port-forwards for each client.
The 4.67-second result is one local measurement, not a removal deadline.

Test Users `mtxkick455211`, `mtxkicka7d854`, `mtxkick9cb41c`, and
`mtxkick943033` remain as revoked permanent records. Their password Secrets
were removed. The clients and port-forwards were stopped. The local probe
and sanitized result are `.local/tak/kick_probe.py` and `kick-result.json`.

### Smallest implementation path

Reuse the session adapter and control credential. Preserve the grant API's
strict username check. Add a callsign-aware entry point that shares the
validated list and kick operations. Match exact usernames and validated
session IDs. Handle a kick response of 404 as already absent, then verify
the inventory again.

Strengthen inventory validation before connecting this adapter to User cleanup.
The current parser ignores `itemCount` and does not check stable pagination
totals. A local reproduction supplied `itemCount: 1`, `pageCount: 1`, and
`items: []`. The adapter returned zero kicks after two scans and reported no
error. It must reject that incomplete inventory. Reuse the completeness checks
already used by stream discovery. Add a regression case for this response.

Run cleanup under `mediamtx-operator` leadership, independently of TAK.
Use a periodic session scan and fresh User reads. One pass can inspect each
distinct username once. User watch events can request an earlier scan.
This avoids scanning every protocol once for each UserBinding. Continue
periodic scans after an empty result: admission accepted just before a
revocation can become visible after the first cleanup pass.

Persist denial before kicking. Retry API failures and partial scans. Do not
mark cleanup complete from an incomplete inventory or a failed API request.
Do not treat a Kubernetes outage as proof that a User is absent. No strict
removal guarantee exists while the control API is unavailable. A future
multi-replica MediaMTX deployment must inspect every instance, not a random
Service backend.

Tests must cover revoked readers on another User's path, publishers, unrelated
Users, pagination changes, lost kick replies, restarts, and in-flight admission.
Revoking a User needs no Core schema change. Rename support is a
separate [Core feature handoff](core-user-rename-handoff.md).

### MoQ limit

MoQ has a kick endpoint, but its
[session schema](https://github.com/bluenviron/mediamtx/blob/v1.21.2/internal/defs/api_moq.go)
does not expose the authenticated username. The inspected
[upstream main schema](https://github.com/bluenviron/mediamtx/blob/main/internal/defs/api_moq.go)
also lacks that field. A path or remote address cannot safely identify
the User of a reader session.

Suggested fix: expose the authenticated User in MediaMTX's MoQ session list,
as the other protocols do. The MoQ admission code receives the authenticated
User result but does not retain it in the API record. This needs an upstream
change and runtime proof before username-based cleanup covers MoQ.

An alternative is a durable mapping from callback session ID to User UID.
The [MoQ admission code](https://github.com/bluenviron/mediamtx/blob/v1.21.2/internal/servers/moq/session.go)
sends the session ID to authentication. Our callback validates that ID but
does not retain it. Such a mapping must be stored before admission succeeds,
survive restarts, and be reconciled against live sessions. An in-memory map
would lose ownership after restart. This alternative adds storage and writes
to authentication, so prefer an upstream User field.

This investigation did not change runtime code. RTSPS removal was tested
live. HLS has earlier live grant-session evidence. RTMPS, SRT, WebRTC, and
MoQ removal were not tested with live clients in this investigation.
