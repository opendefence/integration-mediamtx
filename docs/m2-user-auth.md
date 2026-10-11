# MediaMTX callsign authorization

Date: 2026-10-11. MediaMTX sends a username and password to
`POST /internal/mediamtx/auth`. The username is the callsign and the Kubernetes
User resource name. The callback reads that User for each request. It does not
cache Roles or call `core-operator`.

An approved, unrevoked User can read any path and publish to
`live/{tool}/{own-callsign}`. The tool must be `icu`, `gopro`, `uas`, or
`ipcam`. Publishing matches the full callsign segment, so `alpha` cannot
publish to `alpha2` or to an extra path segment. Playback uses the same read
rule if the MediaMTX playback service is enabled.

Only the exact projected Role name `superadmin` adds an override. It permits
all supported media paths and the `api`, `metrics`, and `pprof` actions.
It still requires the correct password and an active User. A Role reference
in spec, a Group named `superadmin`, or a certificate grants no override.
Normal media access requires no MediaMTX Role. The existing User model is
sufficient for these checks.

The callback accepts MediaMTX's `rtsp`, `rtmp`, `hls`, `webrtc`, `srt`, and
`moq` protocol names. Unknown actions and protocols are denied. Password and
token fields may contain the same value. A conflicting or token-only value
is denied. See the pinned [MediaMTX request fields](https://github.com/bluenviron/mediamtx/blob/v1.21.2/internal/auth/request.go)
and the [legacy callsign rules](https://github.com/pvarki/python-mediamtx-rmmtxauthz/blob/main/src/rmmtxauthz/web/mediamtx.py).

## Password storage

`mediamtx-operator` creates one namespace-scoped Secret named
`mediamtx-user-<User UID without hyphens>`. The unique identifier (UID) is the
Kubernetes resource identity. The Secret's `password` data key contains a
random 256-bit password encoded as URL-safe text. Atomic creation preserves
the stored password across restarts and concurrent reconciliation.
The Secret's annotation pins it to the User UID. Credential reads check the
name, namespace, ownership label, UID annotation, and password format.

The callback validates the password before it applies the Role override.
It never creates a password during an authentication request. A missing
credential denies access. Revocation denies access even if the Secret remains.
The callback reads projected Role changes on each request. It does not infer
Roles from certificate properties or inspect Role and Group resources.

## Run the private callback

Use a Kubernetes identity that can get cluster-scoped Users and get Secrets
in the integration namespace. Use an approved test User only when its resource
will remain as a permanent record. The unit tests use in-memory API fixtures
and do not create approved Users in the shared cluster.

Run `mediamtx-operator` to create the User's password. Then start the callback
with the server certificate and private key for the callback hostname:

```sh
export CLOUDCOIL_NAMESPACE=integration-mediamtx-dev
task auth:run TLS_CERT_FILE=/absolute/path/server.crt TLS_KEY_FILE=/absolute/path/server.key
```

The listener defaults to `127.0.0.1:9443`. The `mediamtx-auth` command also
accepts `--namespace`, `--host`, and `--port`. TLS files are required.
The listener serves only the private callback route. It limits request size
to 32 KiB, request processing to five seconds, and concurrent connections.
It returns an empty 204 on success, 403 on denial, 400 for an invalid body,
and 503 if Kubernetes is unavailable. Responses disable caching. Request
bodies, passwords, and access logs are not written to logs.

For a manual MediaMTX test, set `authMethod: http`, `authHTTPExclude: []`, and
`authHTTPAddress` to the HTTPS callback URL. MediaMTX must trust the callback
certificate or use its verified `authHTTPFingerprint`. Limit network access
to MediaMTX. Do not expose this listener as a public user API.

## Current limits

The Zarf package runs the callback beside `mediamtx-operator`. A private
Service exposes port 9443 only to the MediaMTX Pod. A namespace-local
cert-manager certificate authority (CA) signs the callback certificate. MediaMTX mounts only the
public CA certificate and verifies the callback service name over HTTPS.
The callback fails closed when Kubernetes is unavailable. `mediamtx-operator`
reports `Synced=False` until the remaining lifecycle work is complete.
The integration's control identity is `mediamtx-control`. Its stable password
is stored in a namespace Secret with the same name. Only `mediamtx-operator`
creates that Secret. The callback permits this identity to use only the control
API. It grants no media read or publish access and requires no User record.
The public credential-delivery API, password rotation, and automated removal
of existing sessions remain pending.
Denial of a new callback does not end an existing media session.
The callback loads its server certificate at startup. Restart the
`mediamtx-operator` Deployment after certificate renewal. Restart MediaMTX
after a CA certificate replacement. Automated certificate reload is pending.

The older scoped-grant policy and protocol probe remain available for their
recorded tests. They are not used by this callsign callback. Their synthetic
Role, revision, and freshness fields are not new Core requirements.
