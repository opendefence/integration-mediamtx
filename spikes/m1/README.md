# Media protocol spike

This is a disposable integration test, not the API, operator or Core adapter.
It uses standard-library Python and three digest-pinned ARM64 images from
`images.json`. The MediaMTX image also contains FFmpeg. Traefik is a test
candidate; it is not a base-approved production selection.
Since M2, the fixture mounts the package's actual admission policy and canonical
path implementation. Core state remains explicit test data. The original M1
fixture is preserved at commit `d3da9cd`.

Start Podman and install Kind v0.33.0, kubectl and OpenSSL. Use the configured
Python 3.14 environment. From the repository root:

```sh
make sync
make kind-up
uv run --locked python spikes/m1/run.py
make kind-down
```

If Kind is installed in `.local/bin`, add that directory to PATH first. Run the
spike once at a time. It needs free localhost ports 19997, 18888 and 28443 and
registry access to fetch the pinned images. Pods use explicitly loaded archives
and `imagePullPolicy: Never`; this does not prove a complete offline install.

The runner checks this checkout's cluster ownership and explicit context. It
refuses an existing `mediamtx-m1` namespace. It creates a short-lived test
certificate and random passwords, deploys a private authorization fixture,
publishes synthetic video over RTSPS, and exercises HTTPS HLS and control calls.
TLS verification is enabled; the callback uses an exact leaf-certificate pin.
No Core certificate or production credential is used.

Assertions cover scoped admission, copied HLS query and cookie sessions,
paginated session matching, removal and reconnect denial, a broken prefix
redirect, callback shutdown and a wrong certificate pin. Negative findings are
expected assertions. Success does not mean those upstream limitations are fixed.
An additional check expires the fixture policy projection and confirms denial
of new media access while management remains available. Fixture freshness lasts
five minutes; this is not the production freshness contract.
Do not run Python with `-O`; that would disable assertions.

The runner deletes the namespace and port forwards on completion or failure.
An abrupt process termination can leave fixtures; use `make kind-down` to remove
only this checkout's owned cluster. `.local/m1/results.json` contains the last
successful report. `.local/m1/failure.log` contains password-redacted diagnostic
logs after a failure. Both are ignored, as are image archives and temporary
certificate files. The runner checks current Pod logs and the callback event
sample for generated credentials; this is not a platform-wide log audit.

See [M1 findings](../../docs/m1-findings.md) for measured results and limits.
See [M2 policy](../../docs/m2-policy.md) for the package implementation and its
separate result record.
