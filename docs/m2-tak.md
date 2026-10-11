# TAK stream publication

`mediamtx-operator` publishes ready canonical streams to the TAKServer video
catalogue. It uses the `/Marti/api/video` API through mutual Transport Layer
Security (mTLS). `tak-operator` registers the integration identity with
administrator access. This identity is separate from User identities.

## Reconciliation

Each scan reads all MediaMTX path pages through the private HTTPS control API.
It keeps only ready `live/{tool}/{callsign}` paths whose User is approved and
not revoked. It reads the User resource directly. No running `core-operator`
is required. An invalid or incomplete snapshot stops the scan before TAK writes.

Each TAK collection has an alias, one RTSPS URL, and a stable feed ID:
`mediamtx:{namespace}:{stream_id}`. The URL has no username or password.
Viewers must use their own media credentials. TAK applies its normal group
visibility rules to the collection. The integration does not change User groups.

The next scan starts ten seconds after the previous scan ends. Each scan has
a sixty-second timeout. The scan updates changed feeds and removes stopped,
revoked, or missing-owner feeds. It preserves feed IDs from other installations.
It verifies every write with a readback. A failed read, write, or readback
causes a retry. An unavailable source is not treated as an empty catalogue.
Existing feed records can therefore remain during an outage.

The process needs no local ownership database. Feed IDs identify the records
that it can reconcile after a restart. Run one writer per integration namespace.
The package uses one replica and Cloudcoil's Kubernetes leader lease to prevent
overlapping writers during upgrades. The worker stops when leadership is lost.
The update strategy stops the old Pod before it waits for the new leader.
The authorization callback is unavailable briefly during this transition.
Do not reuse that namespace identity from
another cluster against the same TAKServer.

## Deployment

Deploy the sibling `integration-tak` package first. Supply
`Secret/mediamtx-tak-admin` in the MediaMTX namespace with `tls.crt`, `tls.key`,
and `ca.crt`. Use a client certificate in TAK's trusted User certificate chain.
Have `tak-operator` register its public certificate with `ROLE_ADMIN`.
The local certificate common name is `integration-mediamtx-admin`.
The [administrator checkpoint](implementation-status.md#tak-administrator-access-checkpoint)
records the current development registration. Zarf does not create this Secret
or register the extra identity. The generic registration contract remains pending.

Set these Zarf values:

```yaml
takUrl: https://tak-server.integration-tak.svc.cluster.local:8443
takServerName: tak.localtest.me
```

`takUrl` is the connection address. `takServerName` selects the certificate
name for TLS verification and Server Name Indication (SNI). An empty
`takServerName` uses the URL hostname. Certificate verification stays enabled.
The local overlay supplies these values. Production defaults to an empty
`takUrl`, which disables publication.

The package mounts the TAK key only in the `mediamtx-operator` container.
It also mounts the public CA for the private MediaMTX API. MediaMTX mounts
its separate control certificate. NetworkPolicy permits port 9997 only from
the `mediamtx-operator` Pod. The callback checks the control password even if
the cluster does not enforce NetworkPolicy.

The advertised URL is `rtsps://{domain}:8322/live/{tool}/{callsign}`.
Configure a public route to that port before using an external TAK client.
The development hostname resolves to loopback. The local cluster test does
not supply public media ingress or prove native TAK client playback.

To run `mediamtx-operator` outside the package, set `TAK_URL`,
`TAK_SERVER_NAME`, and `MEDIA_RTSPS_URL`. Provide the client certificate files
under `/var/run/tak/` and the MediaMTX control CA at
`/var/run/mediamtx-control/ca.crt`.

## Operation and limits

The polling loop reloads its CA and client certificate files on each scan.
TAK still needs the renewed client fingerprint registered before that
certificate can authenticate. Automated registration is not implemented.
MediaMTX and the callback still need a restart after their server certificates
renew. Strict TAK integration identity admission remains unavailable.

Removing a feed does not terminate its media sessions. Session cleanup and
public credential delivery remain separate work. Publication errors do not
stop the authorization callback or make pending UserBindings report ready.

Before disabling publication or removing the package, stop its publishers and
wait for the owned TAK feeds to disappear. Disabling the polling loop leaves
existing TAK records unchanged. Check `mediamtx-operator` logs for errors:

```sh
kubectl -n integration-mediamtx-dev logs deployment/mediamtx-operator -c operator
```

The log records error types without remote response bodies or credentials.
Unit tests cover incomplete snapshots, User revocation, API failures, lost
write replies, ownership after restart, and worker shutdown.
