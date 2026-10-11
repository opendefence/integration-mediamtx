# M1 protocol findings

Date: 2026-10-10. Scope: one ARM64 MediaMTX instance in an isolated Kind cluster.
The [runner](../spikes/m1/run.py) is an assertion-based test with a private
fixture callback. It does not implement Core policy or the integration API.
See [contracts and gates](m1-contracts.md) for the implementation decisions.

## Exact candidates

| Component | Version | ARM64 image digest |
| --- | --- | --- |
| MediaMTX with FFmpeg | 1.21.2; FFmpeg 8.1.2 | `sha256:dfbb58bf4f3e6c03ce3ee56e92c90395e7cfd96beb51e13fa7d4007f10507586` |
| Python fixture | 3.14.7-slim | `sha256:67994a05c712036dbfc4385b4bceafc0ce20df950f54b9ea355582c153bf6157` |
| Traefik candidate | 3.7.14 | `sha256:060f4c0328bebb33be8a73694ea613055c4591ba26493202a1830f964e171995` |

The fully qualified pins are in [images.json](../spikes/m1/images.json).
The reviewed MediaMTX source is
[`914e39535ece709919ac325aaeed98d394ed9093`](https://github.com/bluenviron/mediamtx/tree/914e39535ece709919ac325aaeed98d394ed9093).
Traefik is a fixture candidate, not a base-selected release. AMD64 was not tested.

## Admission and session evidence

The spike publishes synthetic H.264 over verified RTSPS and reads HLS over
verified HTTPS. The callback has separate publisher, reader and control
credentials. It checks one exact path, action and upstream protocol. It returns
204 on allow, 401 for missing identity and 403 on denial. MediaMTX maps these
HTTP-facing authentication failures to 401.

The following assertions passed in the live fixture:

- Missing and wrong passwords, wrong action and a different configured stream
  are denied. A media reader cannot authenticate to the control API.
- The RTSPS callback reports protocol `rtsp`. Password can equal token. Control
  requests have an empty protocol and a null session ID.
- HLS query sessions and cookie sessions can read without resending Basic
  credentials. Denying future reader requests leaves these sessions usable.
  The test also retrieves an MPEG-TS segment after denial and checks its packet
  sync byte. That segment URL is denied after the session is kicked.
- A session list with one item per page finds both sessions by their grant
  username. Kicking both sessions makes copied query and cookie requests fail.
  A repeated kick returns 404. The list becomes empty and reconnect is denied.
- Removing the callback Pod denies new reads and authenticated control requests.
  An existing HLS query session remains readable. This is a real callback outage,
  not a test of `core-operator` or `mediamtx-operator` availability.
- A wrong callback leaf pin is rejected. Updating `authHTTPFingerprint` through
  the control API also recreates the protocol listeners and ends old sessions.
  This reload must not be confused with an unplanned callback outage.
- Current Pod logs and the sampled callback event log exclude the generated
  passwords. The Pod check also excludes their Basic authentication encoding.

The checked-in [result record](m1-results.json) contains the measured kick time.
It measures the two kicks and immediate verification after denial was already
set. It is not a policy-to-revocation latency guarantee or a load test.

MediaMTX rejects an unconfigured path with 404 before the callback. The scope
test therefore uses a second configured path. The API uses zero-based pages and
`itemsPerPage`; do not confuse it with the public API's opaque cursors.

Source review confirms that HLS authenticates when creating a session and has
no grant-expiry timer. Query and cookie identifiers select existing sessions.
An inactivity timeout does not bound a continuously used session. See the pinned
[session implementation](https://github.com/bluenviron/mediamtx/blob/914e39535ece709919ac325aaeed98d394ed9093/internal/servers/hls/session.go)
and [HTTP handling](https://github.com/bluenviron/mediamtx/blob/914e39535ece709919ac325aaeed98d394ed9093/internal/servers/hls/http_server.go).

## TLS and callback limits

The fixture uses a generated certificate trusted by the clients. MediaMTX uses
the exact SHA-256 leaf fingerprint for callback trust. A source review of
[`MakeConfig`](https://github.com/bluenviron/mediamtx/blob/914e39535ece709919ac325aaeed98d394ed9093/internal/protocols/tls/make_config.go)
shows that pinning replaces normal CA, hostname and expiry validation with an
exact leaf comparison. This is a trust mode, not CA validation plus a pin.
Production must manage the pin and its certificate rotation. The default
unpinned client instead uses system trust.

The callback protocol field cannot prove TLS. Strict RTSPS configuration and
disabled plaintext admission provide that property in this test. MediaMTX
supplies credentials in the callback; they do not prove caller workload identity.
Production still needs private exposure, network restrictions and the agreed
transport-security boundary. The fixture does not claim callback mTLS.

The control permission is broad `api`; it cannot express read-only control.
Callback unavailability also prevents `mediamtx-operator` from authenticating to kick
sessions through that API. Keep management credentials independent of Core
policy freshness, but do not claim this removes the callback availability risk.
The pinned [authentication implementation](https://github.com/bluenviron/mediamtx/blob/914e39535ece709919ac325aaeed98d394ed9093/internal/auth/manager.go)
and [configuration reload](https://github.com/bluenviron/mediamtx/blob/914e39535ece709919ac325aaeed98d394ed9093/internal/core/core.go)
support these conclusions.

## HTTP routing result

Traefik's HTTPS router accepts
`/integrations/mediamtx/media/hls/{path}/index.m3u8` and removes the prefix before
forwarding to MediaMTX over verified HTTPS. MediaMTX returns a 302 whose Location
starts at `/{path}/`, outside that public route. Following it returns 404.
This test proves StripPrefix alone is insufficient; it does not prove the
completed production route. No response-rewriting component has been selected.

This matches the official
[MediaMTX subfolder requirements](https://mediamtx.org/docs/features/expose-the-server-in-a-subfolder)
and [Traefik StripPrefix behavior](https://doc.traefik.io/traefik/reference/routing-configuration/http/middlewares/stripprefix/).
The latter supplies `X-Forwarded-Prefix`; this MediaMTX redirect does not use it.
Keep the public prefix gated until base approves a tested response rewrite or
another explicit routing contract. Do not add a payload proxy or sidecar.

## Limits and next evidence

This test does not prove the production authorization policy, Kubernetes grant
durability, Core freshness, ForwardAuth headers, public API or
`mediamtx-operator` restart recovery, admission races or an absolute session
deadline. Strict outage enforcement remains unverified and must not be advertised. The 15/30-second targets remain
unverified. Native Safari, hls.js, VLC and mobile clients were not exercised.

RTMPS, SRT, WebRTC/ICE, recording, client import/update behavior, AMD64 and full
offline deployment remain later tests. TAK work stays deferred. Generated
fixture passwords and certificates are not release credentials. No integration
runtime image or public service was released by M1.
