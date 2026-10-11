# M2 grant reservations

The internal reservation adapter stores one Kubernetes Secret for each User
who requests a grant.
The Secret contains a versioned ledger. Each entry stores a digest of the
idempotency key, a request digest, a random grant identifier, an expiry time
and a cleanup marker. It does not store the raw key or a media password.

`reserve_grant` creates the Secret atomically. Later reservations use the
Secret's unique identifier and resource version as write preconditions.
Concurrent active requests with the same key reuse the same grant identifier.
A changed request cannot reuse that key. The ledger permits eight active
reservations and 64 retained entries per User. An expired or completed entry
cannot become active again.

Call `mark_cleanup_complete` only after denial is stored and all matching
sessions are removed. The caller supplies the stored key digest and grant
identifier. It does not need the raw idempotency key after a restart.
Completion releases active capacity but keeps the entry for retries.
A failed Secret write leaves the previous state in place.
The [grant retirement adapter](m2-grants.md) applies this order when its
caller supplies every active MediaMTX instance.
After grant expiry and the 24-hour idempotency retry window, the grant
retention adapter deletes a completed, revoked grant record before it removes
the ledger entry. An interrupted removal leaves the ledger entry for retry.

This adapter does not issue credentials. The separate
[grant record adapter](m2-grants.md) stores individual grant Secrets. A
scheduled cleanup loop and the public API still need implementation. The
`mediamtx-operator` has no Secret permissions yet. Do not use these adapters for
production issuance until those parts and Core's effective Role projection are
ready.
