# M2 grant records

The internal grant adapter stores one Kubernetes Secret for each reserved media
grant. It does not issue a grant to a User. A caller must first obtain a stored
reservation and apply this integration's Role rules to a fresh Core User
projection before it creates a grant record.

`create_grant_record` uses the reservation's grant ID and lifetime. It stores
the grant's subject, binding, stream, action, and protocols with the
reservation's request and key digests. On a retry, it compares these values
with the stored record. An atomic Secret create selects one password. If
another creator wins, the adapter returns the stored password. It never
returns the losing password. A changed request or a revoked or expired record
fails closed.

The Secret name is a digest of the grant ID. Its labels show integration
ownership and the User UID, but no credential or request key. Its versioned
payload contains the grant, password, subject and binding UIDs, and request
digests. Reads reject missing ownership fields, changed labels, malformed data,
unknown schema versions, and invalid grants. `load_grant` returns a record for
policy evaluation; loading it does not authorize a MediaMTX request.
`list_grants_for_subject` selects the User's records by UID label and validates
each Secret. It includes revoked records so later reconciliation can finish
session cleanup.

`revoke_grant` checks the User UID and writes a revocation marker with Secret
UID and resource-version guards. It retries write conflicts and preserves an
existing revocation marker. The caller must persist revocation before it drains
sessions. The record stays available until cleanup is complete.

The unit tests cover concurrent creation, User-scoped listing, a changed
request, invalid stored data, guarded revocation, conflict retry, and retry
after revocation. The operator still has no Secret permission. There is no
production credential issuer, HTTP callback, or grant cleanup loop. Core's
effective Role projection is still required before this adapter can serve
public access.
