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
No MediaMTX control credentials or routes are exposed by the Zarf package yet.
The adapter does not prove a strict deadline when MediaMTX or its control API is
unavailable. TAK support remains deferred.
