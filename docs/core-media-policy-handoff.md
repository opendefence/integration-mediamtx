# Core media-policy contract: developer handoff

Date: 2026-10-11. This handoff describes the Core input that the MediaMTX
integration needs before it can grant public media access. It describes required
behavior. It does not prescribe a Core API route or custom resource.

## The gap

Core identifies a User and records its direct Role and Group references. Core
also observes UserBindings that integrations create. The current Role model has
a display name but no permissions. The current Core API has enrollment,
certificate, and health routes, but no effective media-policy route. The models
do not say which streams a User may read, whether it may publish, whether it may
share a read credential, or whether it is assigned to this integration.

A UserBinding is an integration-owned provisioning observation. The integration
creates it and writes its `Synced` condition. Core watches it. A binding can be
`Synced=True` while the User has no permission to use media. Core can also report
`BindingsSynced=True` when there are no bindings. Neither condition is an
assignment or an authorization decision.

Core's `approvedAt` records when approval happened. It is not an access
deadline. `revokedAt` records User revocation. These fields do not provide a
complete media-policy result or a freshness limit.

The integration has a local `EffectivePolicy` type and tests for media admission.
That type is a test input, not a Core API message or custom resource. The tests
supply policy fixtures. They do not prove that Core authorized those values or
that a live policy cache is current.

**Result:** The integration can create a UserBinding and report pending work. It
cannot safely mark media provisioning complete, issue public media credentials,
authorize public grant and profile API calls, or accept MediaMTX authentication
from real users until it can obtain and verify effective Core media policy.
Infrastructure and deny-by-default configuration can proceed independently.

| Integration work | Current state and missing input |
| --- | --- |
| Create a UserBinding | Available now. The operator creates a binding and keeps `Synced=False`. |
| Complete provisioning | Needs current Core assignment and permission decisions, then a matching MediaMTX configuration. A binding alone cannot make `Synced=True` meaningful. |
| Serve the proposed `/me` and `/streams` routes | Needs current account state, assignment, and effective read scope. These public routes are not deployed yet. |
| Issue or return a media grant or connection profile | Needs a fresh decision for the exact stream and action. Sharing a reader grant also needs sharing permission. The public API is not deployed yet. |
| Admit a MediaMTX connection | Needs fresh Core policy as well as the integration's stored grant, binding UID, expiry, and revocation checks. |

## Required decision for each User

Core must provide the following meanings through a trusted, versioned contract.
It can provide a short-lived policy projection or a fresh decision service.

| Input | Required meaning |
| --- | --- |
| Subject | The immutable Kubernetes `User.metadata.uid`. A callsign or User name alone is not enough because a deleted User can be recreated with the same name. |
| Account state | Whether the User is currently approved and not revoked. Pending, deleted, unresolved, or revoked Users cannot use media. |
| Assignment | Whether Core currently assigns this User to the MediaMTX integration. Binding existence and `Synced` do not supply this decision. |
| Read scope | Whether the User can read a given stream, including any allowed cross-User stream scope. The contract must identify the stream in a form both systems can compare exactly. |
| Publish scope | Whether the User can publish its own stream. Any wider publish scope needs an explicit decision. |
| Sharing | Whether the User can create a transferable read credential. This is separate from permission to read a stream. A grant label is not permission. |
| Policy version | A revision or equivalent change signal that covers all policy inputs, including User, Group ancestry, Role, permission, and assignment changes. The integration needs a way to reject or refresh old decisions. |
| Freshness | An authoritative evaluation time and expiry, or a bounded fresh decision for each use. A live watch connection alone does not prove that an old value is current. |
| Access deadline | An absolute time after which access ends, or an explicit statement that no deadline applies. A missing field must not mean unlimited approval by accident. |

Core must define how Group and Role references produce these permissions. The
integration must consume the resolved result. It must not implement a second
Group inheritance or Role permission algorithm. Core must also define the deny
result for missing or unresolved references and unknown permission values.

The integration can combine the Core result with its own current UserBinding
UID. Core does not need to store the binding UID in its policy model. The UID
pins grants to one binding generation. The integration also owns the exact media
path, grant action and protocol, grant expiry, stored revocation, and MediaMTX
configuration. A valid Core result cannot enlarge a grant's fixed scope.

## Delivery and freshness choices for Core

Core can choose either of these contract shapes:

1. A versioned policy projection that the integration can read and watch. Each
   projection must have a short, authoritative validity interval. Core must
   publish changes caused by every relevant source, and define ordering or
   resync behavior after a missed event.
2. An authenticated decision API for a subject, integration, action, and exact
   stream. It must return a bounded validity interval or require a fresh call
   for each authorization. It must also give the integration a way to find
   affected grants and sessions when policy changes.

For either shape, agree on the schema version, service identity or read
permission, error result, clock rules, maximum staleness, and behavior during a
Core outage. Missing, malformed, expired, or unavailable policy must deny new
admission. Define how a change reaches the integration so it can stop existing
sessions. The original plan sets **15 seconds for policy freshness** and **30
seconds for denial and session removal** as targets. They are not measured
guarantees. Core's policy contract alone cannot remove a MediaMTX session if the
MediaMTX control API is unavailable; that failure behavior needs a separate
deployment decision.

Core remains responsible for user mutual Transport Layer Security (mTLS)
authentication and for injecting a verified User identifier at the trusted API
edge. The integration consumes that header. It does not need to run Core's
ForwardAuth service or authenticate client certificates itself. The current
default header name is `X-OpenDefence-User-UUID`; the name can change by
agreement. Core must strip any client-supplied copy before it injects the
verified value.

## Acceptance cases

1. A User is approved and its binding is `Synced=True`, but Core has not assigned
   it to MediaMTX. The result denies credentials and media admission.
2. Core assigns a User and allows its own publication. The integration can
   issue a publisher grant only for a stream owned by that User. A reader grant
   requires a separate read decision for its exact stream.
3. A Group ancestor, Role, permission, or assignment changes without a User
   object edit. A new decision reflects the change. An old decision expires or
   is invalidated within the agreed freshness limit.
4. A User loses approval, is revoked, or reaches its absolute access deadline.
   New admission stops. The integration can identify and remove existing
   sessions within the agreed healthy-system target.
5. A User has no access deadline by explicit Core policy. The integration does
   not infer this from an omitted or unreadable deadline.
6. A User is deleted and recreated with the same callsign. The new
   `metadata.uid` differs. Credentials for the old UID do not authorize the new
   User. Core must define any identity-recovery mapping before old grants can
   be restored.
7. Core policy is stale, missing, malformed, or unavailable. New credentials
   and media admission are denied. A recovered policy can restore access only
   after a fresh decision and the integration's own grant checks.
8. A User may read a stream but has no sharing permission. The User cannot
   create a transferable reader grant. MediaMTX bearer credentials do not
   identify the person who receives them.

## Requested Core handoff result

Please provide a versioned schema or API specification, one allowed and one
denied example, the permission and assignment rules, the freshness and change
delivery rules, and contract tests for the cases above. Specify the access
deadline representation, including an explicit no-deadline value. State which
Core component computes the effective decision and which identity an
integration uses to read it. This is enough for the integration to implement a
Core adapter and connect its existing policy tests to live decisions.

The current source of this gap is visible in Core's
[User](https://github.com/opendefence/core/blob/929149db8925881470a37281179f4829029a4354/src/lib_opendefence_core/models/v1alpha1/user.py),
[Role](https://github.com/opendefence/core/blob/929149db8925881470a37281179f4829029a4354/src/lib_opendefence_core/models/v1alpha1/role.py),
[Group](https://github.com/opendefence/core/blob/929149db8925881470a37281179f4829029a4354/src/lib_opendefence_core/models/v1alpha1/group.py), and
[UserBinding](https://github.com/opendefence/core/blob/929149db8925881470a37281179f4829029a4354/src/lib_opendefence_core/models/v1alpha1/userbinding.py)
models, and in its [API router](https://github.com/opendefence/core/blob/929149db8925881470a37281179f4829029a4354/src/opendefence_core/api/app.py).
The integration's [M1 contracts](m1-contracts.md) and
[M2 policy](m2-policy.md) give the local semantics. The
[original plan](integration-mediamtx-plan.md) and
[API draft](openapi.json) are design references, not deployed behavior.
