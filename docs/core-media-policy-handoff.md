# Core User projection: developer handoff

Date: 2026-10-11. This handoff describes the Core data that the MediaMTX
integration needs. Core owns User identity, account state, and effective Role
and Group membership. Core does not decide what a MediaMTX role permits. This
integration owns those meanings and the media access decision.

## Current gap

The current Core User status lists direct Roles and Groups. Its `roles` field
does not include Roles inherited from Groups. Core plans to reconcile changes
to Roles, Groups, assignments, and account state into each User object. The
integration already watches Users. A User update queues its UserBinding for
reconciliation.

The current User model has no complete effective Role set or bounded freshness
rule. The integration cannot treat direct Role references as the complete
access decision. It cannot safely issue public media credentials, admit live
MediaMTX connections, or mark media provisioning complete from those fields.
Its running operator keeps `UserBinding.status` at `Synced=False`.

A UserBinding is an integration-owned provisioning observation. Its existence
or `Synced=True` condition does not assign a Role. Core can report
`BindingsSynced=True` when a User has no bindings. Neither condition grants
media access.

## Data Core must project

Core must publish the following general User data. It does not need to publish
read, publish, share, or MediaMTX control permissions.

| Data | Required meaning |
| --- | --- |
| User identity | `User.metadata.uid` is the immutable subject. A recreated User gets a new UID, even if it has the same callsign. |
| Callsign | The current User callsign. The integration uses it in media paths, not as a credential identity. |
| Account state | Whether the User is approved, pending, revoked, or deleting. A revoked or unapproved User has no media access. |
| Effective Roles | Names and UIDs of all current Roles, including direct and Group-derived Roles. Include the global `superadmin` Role. |
| Resolution state | A clear result for missing or unresolved Role and Group references. The integration denies access while the effective set is incomplete. |
| Revision | A change marker that covers all inputs to the effective set, including Group ancestry and Role assignments. |
| Freshness | An evaluation time and expiry, or another bounded rule that lets the integration reject a stale projection. A watch connection alone cannot prove that Core is still reconciling. |
| Account deadline | State whether Core has a general account access deadline. If it does, project the absolute deadline or an explicit no-deadline value. This is separate from a media grant's expiry. |

The integration needs the effective Role names to apply its own Role meanings.
It also needs the UID and revision to detect replacement or stale references.
Core must define how an integration registers its Roles. It must state when a
new User projection is written after a direct Role edit, Group Role edit,
Group ancestry edit, approval change, or revocation. Core does not need to
assign a User to MediaMTX through a separate permission field: an effective
MediaMTX Role, or `superadmin`, supplies that result here.

## MediaMTX Role meanings owned by this integration

The first integration Role is `mediamtx-user`. It permits reading every
supported media path and publishing only to `live/{tool}/{own-callsign}`.
The planned `mediamtx-share` Role permits a User who can read a stream to
issue a transferable reader grant. It grants no media access by itself. The
public sharing route is not implemented yet.

The global `superadmin` Role permits all supported media paths and sharing.
Only a current `superadmin` User or this integration's own service identity
may use MediaMTX `api`, `metrics`, or `pprof`. A normal media grant never
becomes a control credential. A superadmin control credential must identify
that User by UID and be checked against current effective Roles. The service
identity is separate from User Roles. There is no `productuser` type.
The MediaMTX callback receives credentials, not Core's mTLS identity. A
username alone cannot prove a User or service identity. The integration has
no production control-credential issuer or User control route yet.

The canonical path is `live/{tool}/{callsign}`. The current tools are `icu`,
`gopro`, `uas`, and `ipcam`. Match the complete callsign segment: `alpha` must
not match `alpha2`. Core currently requires lowercase callsigns of 3 to 30
letters or digits. A media grant keeps the User UID and UserBinding UID, so a
new User cannot use an old grant with the same callsign.

This integration computes `EffectivePolicy` from fresh Core identity and
effective Roles. It also checks its current UserBinding UID, exact grant
stream, action, protocol set, expiry, and stored revocation. The local
`EffectivePolicy` type is a semantic input for tests. It is not a Core wire
schema. Core does not need to run the integration's path or grant logic.

## Update delivery and freshness

Core's operator will update the User when relevant Role, Group, or account
inputs change. The integration watches cluster-scoped Users and maps each
event to the User's UID-pinned binding. Startup listing and periodic
reconciliation also queue work. The integration does not need to watch Roles
or Groups or calculate Group inheritance.

Core must define the projection version, evaluation time, expiry or refresh
rule, and behavior when a reference is unresolved. It must define a maximum
delay from an upstream edit to the User update. Missing, malformed, incomplete,
expired, or unavailable data denies new admission. The original plan names
15 seconds for policy freshness and 30 seconds for denial and session removal
as targets. These targets are not measured guarantees. The integration cannot
remove a MediaMTX session while its control API is unavailable.

Core owns User mutual Transport Layer Security (mTLS) authentication. At the
trusted API edge, Core strips any client-supplied User identity header and
injects the verified User UUID. The integration currently accepts
`X-OpenDefence-User-UUID` by default. It does not run ForwardAuth or inspect
client certificates.

## Certificate identity metadata

Core plans to publish accepted User certificate records in one User annotation.
Each record has a Secure Hash Algorithm 256 (SHA-256) fingerprint of the leaf
certificate's Distinguished Encoding Rules (DER) bytes. It also has a positive
serial number, an issuer identifier, and validity times. Core must derive
these fields from the issued certificate and publish only credentials that it
accepts. Issuance alone does not activate a credential. Consumers must deny a
disabled User even when the annotation still contains a record.

This integration can parse the proposed version-one record format. Missing or
malformed metadata yields no credential records. A consumer must also check
the account state and each certificate's validity time. It must not use the
certificate common name as an identity fallback. The final annotation key and
issuer identifier format are still open. MediaMTX does not use these records
for User access today; Core still supplies the verified User UUID in the
trusted HTTP header.

An integration workload is not a User. Core plans a separate Integration
Manifest for workload identity and client credentials. Do not create service
Users or UserBindings for it. The manifest schema and connection contract are
still open. TAKServer integration work remains deferred.

## Acceptance cases

1. A User has a `Synced=True` binding but no effective MediaMTX Role or
   `superadmin` Role. The integration denies media access.
2. A User with callsign `alpha` has `mediamtx-user` through a direct or Group
   assignment. The integration permits reading supported paths and publishing
   to `live/icu/alpha`. It denies publishing to `live/icu/alpha2`.
3. A User has only `mediamtx-share`. The integration denies media access. A
   User with `mediamtx-user` and `mediamtx-share` can request a transferable
   reader grant only after the sharing route exists.
4. A User has effective `superadmin`. The integration permits any supported
   media path without a separate MediaMTX Role. Its media grant still has one
   stream, action, protocol set, and expiry.
5. A Role or Group changes without an edit to User spec. Core updates the
   effective Role projection on that User. The integration receives the User
   update and denies or drains grants that are no longer allowed.
6. Approval ends, a User is revoked, or a general account deadline passes.
   New admission stops. The integration finds and removes existing sessions
   within the agreed healthy-system target.
7. A User is deleted and recreated with the same callsign. The new UID does
   not authorize the old User's grants.
8. The projection is missing, incomplete, malformed, stale, or unavailable.
   The integration denies new credentials and media admission.
9. A current `superadmin` or this integration's service credential may use
   enabled `api`, `metrics`, and `pprof` actions. Normal media grants cannot.

## Requested Core handoff result

Please provide the versioned User status projection schema, an allowed and a
denied User example, effective Role resolution rules, an unresolved-reference
result, revision and freshness rules, and User-update timing. Define how
integrations register Roles and how the global `superadmin` Role appears in
the effective set. State whether Core has a general account deadline. Core
does not need to define MediaMTX Role meanings or stream permissions.

The current gap is visible in Core's
[User](https://github.com/opendefence/core/blob/929149db8925881470a37281179f4829029a4354/src/lib_opendefence_core/models/v1alpha1/user.py),
[Role](https://github.com/opendefence/core/blob/929149db8925881470a37281179f4829029a4354/src/lib_opendefence_core/models/v1alpha1/role.py),
[Group](https://github.com/opendefence/core/blob/929149db8925881470a37281179f4829029a4354/src/lib_opendefence_core/models/v1alpha1/group.py), and
[UserBinding](https://github.com/opendefence/core/blob/929149db8925881470a37281179f4829029a4354/src/lib_opendefence_core/models/v1alpha1/userbinding.py)
models. The [M1 contracts](m1-contracts.md) and [M2 policy](m2-policy.md)
record local integration rules. The [original plan](integration-mediamtx-plan.md)
and [API draft](openapi.json) are historical design references. The
[legacy handler](https://github.com/pvarki/python-mediamtx-rmmtxauthz/blob/main/src/rmmtxauthz/web/mediamtx.py)
is the source of the initial read and publish path rule. Its `productuser`
branch does not apply here.
