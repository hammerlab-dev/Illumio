# Private package manifest schema

`scripts/stage_package_release.py` consumes a private package JSON manifest and stages local installer artifacts only after hash verification.

Manifest URLs must use HTTPS, except for the approved LAN-only host `packages.hammer.lan`. If credentials are supplied, the manifest must use HTTPS. Artifact paths are resolved on the same origin as the manifest so endpoint credentials are not sent to a different host.

Required top-level fields:

```json
{
  "product": "illumio-pce",
  "channel": "stable",
  "version": "24.5.0",
  "status": "ready",
  "base_url": "https://packages.hammerlabs.org/illumio/releases/24.5.0/",
  "artifacts": []
}
```

Required artifact fields:

```json
{
  "role": "pce_rpm",
  "filename": "illumio-pce-24.5.0-2379.el9.x86_64.rpm",
  "path": "illumio-pce-24.5.0-2379.el9.x86_64.rpm",
  "sha256": "<64 lowercase hex sha256>",
  "required": true
}
```

Supported artifact roles:

- `rpm_key` maps to `ILLUMIO_RPM_KEY`
- `pce_rpm` maps to `ILLUMIO_PCE_RPM`
- `ui_rpm` maps to `ILLUMIO_UI_RPM`
- `server_cert` maps to `SERVER_CERT_PATH`
- `server_key` maps to `SERVER_KEY_PATH`
- `ca_cert` maps to `CA_CERT`

The stager rejects non-HTTPS manifests, non-ready manifests, invalid paths, invalid SHA256 values, unsupported roles, missing `rpm_key`, and missing `pce_rpm`. RPM roles are validated with `rpm -qp` after checksum verification.

## Packages origin channel manifests

The live packages origin publishes artifact entries with `kind`, `name`, `path`, and `sha256` fields instead of installer-specific `role` fields. For that format, the stager infers:

- `pce_rpm` from the single EL9 `illumio-pce-*.rpm`
- `ui_rpm` from the matching-version `illumio-pce-ui-*.rpm`
- `rpm_key` from the matching-version `illumio-pce-ui-*.signingkey`

Server certificates, private keys, and CA certificates are not inferred from the package channel. Stage or generate those through the client-approved secret path and pass them to `install_illumio.sh` with `SERVER_CERT_PATH`, `SERVER_KEY_PATH`, and `CA_CERT`.
