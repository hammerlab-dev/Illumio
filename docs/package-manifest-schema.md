# Private package manifest schema

`scripts/stage_package_release.py` consumes a private HTTPS JSON manifest and stages local installer artifacts only after hash verification.

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
