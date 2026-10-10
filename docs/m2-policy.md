# M2 policy implementation

Date: 2026-10-10. This completes the independent policy slice of M2. The public
API, operator and Core adapter still depend on the [M1 contracts](m1-contracts.md).
No new runtime dependency, user database, credential issuer or TAK profile was
added.

## Implemented behavior

[`paths.py`](../src/odintegration_mediamtx/paths.py) normalizes canonical lowercase
UUID text and compact Base64URL to one UUID value. Public IDs and media paths use
the compact form. Paths have exactly three segments: `live/{tool}/{owner}`.
The parser rejects padding aliases, encoded separators, empty or dot segments,
unknown tools, UUID-text path aliases, extra channels and trailing slashes.
Stream IDs have the `s1_` prefix and encode the canonical path. Decoding does
not authorize the stream. The retained tool names are path categories, not a
claim that their client profiles are supported.

[`auth.py`](../src/odintegration_mediamtx/auth.py) parses the selected callback
fields and limits. It accepts missing or null session IDs and ignores unknown
fields. A supplied session ID must be canonical UUID text. A password/token
duplicate is accepted; a conflicting or token-only credential is rejected.
The resulting request retains no token, raw query, IP, session ID or user agent.
Its representation hides all field values because even a username or path is
untrusted input. Grant representations also hide the password.

[`policy.py`](../src/odintegration_mediamtx/policy.py) provides immutable semantic
`EffectivePolicy` and `MediaGrant` records and `authorize_media()`. These types
are not a Core wire schema or a Kubernetes Secret serializer. Construction
rejects malformed records, naive timestamps, empty policy revisions, unsupported
actions/protocols and invalid credentials or lifetimes. Grant IDs select unique
media usernames. Passwords are limited to 22–128 protocol-safe characters;
format validation does not prove random entropy. Issuance must later generate
at least 128 random bits as required by M1.

`authorize_media()` returns a boolean. It requires:

- Matching username and password, checked with constant-time secret comparison.
- One exact stream and action within the grant's enabled protocols.
- A non-revoked grant whose creation time has arrived and expiry has not passed.
- Matching subject and binding UID in the current policy.
- An approved, assigned principal and a currently fresh policy projection.
- Current time strictly before any absolute approval deadline.
- Explicit read permission for the stream, or own-stream publishing permission.

There is no admin shortcut. A read grant cannot gain publishing or control
access from wider principal permissions. Changing effective policy denies access
without changing the User ID. A new binding UID invalidates an old binding's
grant. Any revocation marker denies admission, even if its timestamp is in the
future. Grant lifetime is limited to 24 hours. At exact expiry or deadline,
access is denied. A shortened approval deadline caps access for an existing
grant without extending its recorded expiry.

The caller supplies time and the verified deployment's enabled public protocols.
Upstream `rtsp` and `rtmp` map to `rtsps` and `rtmps` only through that explicit
enablement. The pure function cannot verify listeners or TLS. Do not populate
the enabled set from the callback's protocol string. SRT and WebRTC policy cases
are unit tests; their network and client support remains gated.

## Verification and limits

The unit suite covers identity and path aliases, both audited authorization
failures, malformed callback fields, token normalization, exact time boundaries,
revocation, pending accounts, removed assignments, binding replacement and
effective permission changes. It also checks secret-safe model representations.
All 126 tests passed: 48 path cases, 68 admission cases and 10 foundation tests.
Ruff, strict Pyrefly, the dependency lock check and both package builds passed.

The existing [protocol runner](../spikes/m1/README.md) now loads the actual package
source into its disposable callback Pod and uses canonical compact paths. Its
Core policy and grant inputs remain explicit fixtures. The management credential
has a separate fixture-only check and does not depend on media policy freshness.
The result records source hashes so the tested policy can be identified.
The original M1 baseline remains in commit `d3da9cd` and `docs/m1-results.json`;
the current M2 run is recorded separately in `docs/m2-results.json`.
The live run passed RTSPS publishing, HLS reading, stale-projection denial,
paginated HLS session removal, callback shutdown and certificate pinning checks.
It retrieved 26,508 MPEG-TS bytes after admission denial, then denied the segment
after the session kick. Two kicks and immediate denial verification took 0.061
seconds locally. This starts after denial is set and is not a policy-change
latency guarantee. The known broken prefix redirect remains a passing negative
assertion. Generated-credential checks passed for current Pod logs and the
callback event sample.

These checks prove pure admission behavior and its selected MediaMTX callback
compatibility. They do not prove Core provenance or freshness, grant persistence,
credential issuance, concurrent quota enforcement, status reconciliation, public
authentication, session-drain automation or client support. A false admission
decision does not terminate an existing HLS session. The strict-outage and
HTTP-prefix gates from M1 remain open. TAK remains deferred.
