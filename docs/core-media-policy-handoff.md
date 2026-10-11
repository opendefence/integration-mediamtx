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
Core plans to let integrations define their own roles. Core will also always
have a global `superadmin` role. This planned role support does not yet provide
the integration with a current, resolved decision.

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
| Callsign | The current Core User callsign for media paths. A grant still belongs to the immutable User UID. |
| Account state | Whether the User is currently approved and not revoked. Pending, deleted, unresolved, or revoked Users cannot use media. |
| Assignment | Whether Core currently assigns this User to the MediaMTX integration, or the User has the global `superadmin` role. Binding existence and `Synced` do not supply this decision. |
| Read scope | A normal media user may read every supported media path. `superadmin` may also read every supported media path. |
| Publish scope | A normal media user may publish under `live/{tool}/{its-callsign}`. `superadmin` may publish under every supported media path. |
| Sharing | Whether the User can create a transferable read credential. This is separate from permission to read a stream. `superadmin` can share; other users need an explicit role permission. A grant label is not permission. |
| Control actions | For User requests, Core must identify the current `superadmin` role. Only that User or this integration's own service identity may use MediaMTX `api`, `metrics`, or `pprof`. All other Users and media grants must be denied. |
| Global role | Whether the User currently has the effective `superadmin` role. Core must resolve direct and Group-derived roles. |
| Policy version | A revision or equivalent change signal that covers all policy inputs, including User, Group ancestry, Role, permission, and assignment changes. The integration needs a way to reject or refresh old decisions. |
| Freshness | An authoritative evaluation time and expiry, or a bounded fresh decision for each use. A live watch connection alone does not prove that an old value is current. |
| Access deadline | An absolute time after which access ends, or an explicit statement that no deadline applies. A missing field must not mean unlimited approval by accident. |

The first MediaMTX role can use the legacy path rule: a normal media user can
read all supported streams, and it can publish only under its own callsign.
The canonical path in this integration is `live/{tool}/{callsign}`. The initial tools are
`icu`, `gopro`, `uas`, and `ipcam`. Match the complete callsign segment:
`alpha` must not match `alpha2`. Current Core requires a lowercase callsign of
3 to 30 letters or digits. A callsign is a media path label, not the grant's
identity. The grant keeps the User UID and UserBinding UID so a recreated User
cannot reuse an old grant even if it has the same callsign.
The current parser accepts exactly these three path segments. The legacy prefix
check also accepted suffixes; add channels only when a client needs them.

Core must define how an integration registers its roles and how direct and
Group-derived roles produce the effective result. The integration must consume
that result. It must not implement a second Group inheritance or Role permission
algorithm. Core must define the deny result for missing or unresolved references
and unknown role values. There is no `productuser` account type or general
product credential bypass in this integration.

`superadmin` grants all media permissions and access to the MediaMTX `api`,
`metrics`, and `pprof` actions. A media credential still has one exact stream,
action, protocol set, and expiry; it does not become a control credential.
A superadmin control credential must be tied to that User UID and checked
against fresh Core policy on every authorization. The integration's own service
credential uses a separate identity and does not depend on a User role. This
service identity is integration-owned; it is not a `productuser`. The
MediaMTX callback receives credentials, not Core's user mTLS identity, so a
username alone cannot prove either control identity. The integration has no
production control-credential issuer or user control route yet. The package's
current ingress policy permits the operator Pod to reach the private control
port. Other network policies can add access.
Any later superadmin route must preserve authentication at the trusted edge.

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
2. An authenticated decision API for a subject, integration, and action. Media
   actions also identify the exact stream. The API must return a bounded
   validity interval or require a fresh call for each authorization. It must
   also let the integration find affected grants and sessions when policy
   changes.

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

1. A User is approved and its binding is `Synced=True`, but it has no MediaMTX
   role or `superadmin` role. The result denies credentials and media admission.
2. Core assigns a normal media role to a User with callsign `alpha`. The User
   can read supported media paths and publish to `live/icu/alpha`. It cannot
   publish to `live/icu/alpha2` or a path for another User.
3. A User has the effective `superadmin` role. It can read and publish on any
   media path, even without a separate MediaMTX assignment. A media credential
   still has its own exact stream, action, protocol, and expiry.
4. A current `superadmin` or the integration's own service credential can use
   `api`, `metrics`, and `pprof` when the respective endpoint is enabled. A
   normal media user, a read or publish grant, and an expired superadmin
   credential cannot use these actions. Removing the `superadmin` role denies
   the User's next control request within the agreed freshness limit.
5. A Group ancestor, Role, permission, or assignment changes without a User
   object edit. A new decision reflects the change. An old decision expires or
   is invalidated within the agreed freshness limit.
6. A User loses approval, is revoked, or reaches its absolute access deadline.
   New admission stops. The integration can identify and remove existing
   sessions within the agreed healthy-system target.
7. A User has no access deadline by explicit Core policy. The integration does
   not infer this from an omitted or unreadable deadline.
8. A User is deleted and recreated with the same callsign. The new
   `metadata.uid` differs. Credentials for the old UID do not authorize the new
   User. Core must define any identity-recovery mapping before old grants can
   be restored.
9. Core policy is stale, missing, malformed, or unavailable. New credentials
   and media admission are denied. A recovered policy can restore access only
   after a fresh decision and the integration's own grant checks.
10. A User may read a stream but has no sharing permission. The User cannot
   create a transferable reader grant. MediaMTX bearer credentials do not
   identify the person who receives them.

## Requested Core handoff result

Please provide a versioned schema or API specification, one allowed and one
denied example, the permission and assignment rules, the freshness and change
delivery rules, and contract tests for the cases above. Specify the access
deadline representation, including an explicit no-deadline value. State which
Core component computes the effective decision and which identity an
integration uses to read it. Include the way integrations define roles and the
effective `superadmin` signal. This is enough for the integration to implement a
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
The callsign path and role decisions in this handoff replace the older UUID
path and permission assumptions in those original documents. The
[legacy authorization handler](https://github.com/pvarki/python-mediamtx-rmmtxauthz/blob/main/src/rmmtxauthz/web/mediamtx.py)
is the source of the baseline read and publish rules. Its `productuser` branch
does not apply to this integration.
