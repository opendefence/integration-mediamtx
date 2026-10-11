# Core User projection: developer handoff

Date: 2026-10-11. This replaces the earlier effective media-policy proposal.
The current User schema is sufficient for the first MediaMTX authorization
rule. No new media Role, policy revision, expiry field, or Core permission
endpoint is required.

## Current authorization rule

The media username is the User callsign. Core uses that callsign as
`User.metadata.name`. For each authorization request, the integration reads
`User/<username>` directly from Kubernetes. It checks the current User state
and the integration-issued password stored for that User UID.

- An approved, unrevoked User can read any media path.
- Publishing requires `live/{tool}/{own-callsign}`. The accepted tools are
  `icu`, `gopro`, `uas`, and `ipcam`. The callsign segment must match exactly.
- A User with `superadmin` in `User.status.roles` can use any media path and
  the supported `api`, `metrics`, and `pprof` actions.
- The password and account checks also apply to `superadmin`.
- Other Role names and Group names add no MediaMTX permissions at this stage.

Core owns the projected Role and Group lists. This integration trusts those
lists. It does not resolve Role references or Group inheritance. The
integration reads `superadmin` only from `status.roles`, never from
`spec.roleRefs`, a Group name, a certificate, or a request header.
`mediamtx-user` and `mediamtx-share` are not required.

## Identity and account state

The integration pins each media password to `User.metadata.uid`. A new User
with the same callsign cannot use the old User's password. Core keeps
`spec.callsign` equal to `metadata.name`.

`spec.approvedAt` must be set. Any `spec.revokedAt` value or deletion timestamp
denies admission. An approved User is a permanent record. Revoke it with
`spec.revokedAt` and retain the resource. Only unapproved fixtures may be
deleted and recreated in tests.

The inspected sibling `core-operator` delete validator checks UserBindings
but does not yet reject deletion based on `approvedAt`. Core must enforce
that retention rule before normal operation relies on it.

Traefik ends User mutual Transport Layer Security (mTLS) and sends a verified
User UUID to the public REST API. A User certificate grants no Role or Group
membership. This integration does not read User certificate properties.
MediaMTX stream clients use the integration-issued username and password.
An integration workload is a separate service identity, not a User.

## Projection updates and integration work

`core-operator` writes Role and Group projections into User resources.
`mediamtx-operator` watches those resources. Tests can write the same state
directly with kubectl. Neither reconciliation nor callback authorization
requires a running `core-operator`.

The callback reads the current User for every request. Missing Users,
revocation, wrong passwords, and Kubernetes read failures deny new admission.
Removing projected `superadmin` removes the override on the next callback.
It does not remove ordinary callsign-based access from an active User.

`mediamtx-operator` now creates one password Secret for each active User.
The packaged MediaMTX server uses the private HTTPS callback. Automated
removal of existing sessions and public credential delivery remain integration
work. Bindings remain `Synced=False` until that lifecycle is complete.
These tasks are not blocked by a new Core media-policy contract. The integration's own
control credential is separate; it is not implemented by the User callback.

## Acceptance cases

1. An active User with no Roles can read and publish to its own callsign path
   with the correct password. It cannot publish to another callsign.
2. An active User with projected `superadmin` and the correct password can
   publish to another path and use supported control actions.
3. A `superadmin` reference only in spec, or a Group named `superadmin`, does
   not grant the override. A valid certificate does not grant it either.
4. Removing projected `superadmin` removes control access on the next callback.
5. A wrong password, unapproved User, or revoked User denies every action.
6. An unapproved test User recreated with the same name gets a new UID and
   cannot use a credential pinned to the old UID.

See [the callback implementation and test procedure](m2-user-auth.md).
