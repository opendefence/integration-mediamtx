# Core User rename: developer handoff

Date: 2026-10-11. Status: feature request and design suggestions.
This investigation changed no Core files or Core resource schemas.

## Requested behavior

Allow a person to change their callsign and public name. Keep the same User
identity, approval, Roles, Groups, and integration references. Close media
sessions admitted under the old callsign. Reject new admission under that
callsign. Let the person reconnect with the new callsign after cleanup.

If Core adds a separate display name, define whether changing only that field
affects credentials. Suggested rule: a display name change does not disconnect
sessions. A callsign change does.

## Current constraints

The inspected Core revision is
[`f34aef8`](https://github.com/opendefence/core/tree/f34aef83d5db838ad8d2f28ea2fa9af7147510e9).
Its User custom resource definition (CRD) requires
`spec.callsign == metadata.name`. The installed CRD has the same rule.
A server dry run rejected a callsign change with that validation message.

Kubernetes resource names cannot be changed in place. Keep `metadata.name`
as a stable internal reference and make `spec.callsign` mutable. Existing
Users can keep their original resource names. Do not delete or recreate an
approved User to rename it. Preserve its Kubernetes unique identifier (UID).
See [Kubernetes object identity](https://kubernetes.io/docs/concepts/overview/working-with-objects/names/).

Media passwords are pinned to the User UID. UserBindings reference the User
resource name. The current media callback fetches `User/<media-username>` and
requires the resource name and callsign to match. The TAK catalogue uses the
same lookup rule. Relaxing the Core CRD alone would deny media admission and
remove that User's TAK feeds. The MediaMTX consumers need a planned transition.

## Suggested Core contract

1. Keep one permanent User resource and UID. Keep approval, revocation, Role
   projections, and Group projections on that resource.
2. Provide a unique current callsign and a reliable Kubernetes lookup from
   callsign to User. Enforce uniqueness atomically. Reject ambiguous lookup
   results. Integrations must work from CRD state without a running
   `core-operator` or a Core HTTP service.
3. Record a durable rename revision and the old callsign assignments that
   still need cleanup. Publish that state with the new callsign. Do not rely
   only on watch events or on comparing the latest callsign string.
4. Reserve an old callsign while its sessions and credentials can still be
   used. Suggested first version: do not give an old callsign to another UID.
   Later reuse needs explicit cleanup evidence from each affected integration.
5. Define how each integration acknowledges a rename revision. The existing
   UserBinding `observedGeneration` describes the UserBinding generation. It
   does not acknowledge a User rename. Do not silently change that meaning.
6. Define what happens when certificate replacement, TAK registration, or
   integration cleanup fails. Keep the transition pending and retry. Do not
   report full completion while old access remains usable.

These are contract suggestions. Core developers should choose the field
names and storage model. A timestamp alone cannot identify all sessions
admitted under a prior identity state. Session and Kubernetes clocks can differ.

Two cases require durable state. First, `alpha -> bravo -> alpha` can happen
while `mediamtx-operator` is down. Comparing only the final callsign misses
both changes. Second, reassigning `alpha` to another UID can mix two people's
sessions in MediaMTX's username-only inventory. Cleanup must not disconnect
the new owner or preserve the old owner's access by mistake.

## Ownership and transition

Core owns the rename API, uniqueness, permanent identity, and certificate
policy. Review these source files before changing the contract:

- `src/lib_opendefence_core/models/v1alpha1/user.py`: callsign/name constraint.
- `src/opendefence_core/api/lib/invites.py`: enrollment and callsign lookup.
- `src/opendefence_core/api/dependencies.py`: token subject and UID lookup.
- `src/opendefence_core/naming.py`: certificate and Secret resource names.
- `src/opendefence_core/k8s_operator/controllers/_certificates.py`: certificate
  common name currently comes from the callsign.
- `src/opendefence_core/api/routes/certificates/views.py`: certificate download
  lookup compares the requested callsign with the User resource name.

Keep certificate and UserBinding references stable. If the certificate common
name changes, define when the old certificate stops authenticating and when
the replacement becomes usable. `tak-operator` must reconcile TAK identity
and certificate registration with the same permanent User. A certificate
continues to prove identity only. It grants no Role or Group membership.

`mediamtx-operator` owns media admission, session removal, password delivery,
and TAK feed metadata. It must resolve the new callsign to the same User UID.
It must deny new sessions under old callsigns before removing their existing
sessions. It must remove old TAK feeds and publish new feeds only when their
streams are active. No MediaMTX Role is needed for normal media access.

Suggested rollout: publish compatible shared models and update integration
consumers first. Then enable Core rename operations. Keep old callsigns
reserved throughout rollback. Revocation must take precedence over a rename.

## Acceptance cases

- Rename an approved User. The UID, resource name, approval, memberships,
  and UserBinding references remain unchanged.
- Two concurrent requests claim one callsign. At most one succeeds.
- Old media credentials cannot start a new session under the old callsign.
  Existing readers and publishers are removed. Other Users keep their sessions.
- Stop `mediamtx-operator` during a rename. Restart it and complete cleanup
  from persisted state. Repeat with `alpha -> bravo -> alpha`.
- Delay certificate replacement, TAK registration, or media cleanup. The
  pending revision remains observable. Old callsigns cannot be reassigned.
- Revoke a User during rename. Neither callsign can admit new sessions.
- Supply the projected CRD state directly in integration tests. A running
  `core-operator` is not a test dependency.

The [session investigation](m2-sessions.md#callsign-session-investigation)
records the verified kick mechanism and the remaining Media over QUIC (MoQ)
identity limit. Core rename support does not remove that MediaMTX limit.
