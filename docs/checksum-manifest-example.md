# Checksum manifest example

`CHECKSUM_MANIFEST` points to a standard `sha256sum --check --strict` manifest. Generate it from trusted artifacts on the staging host. Do not invent hashes and do not commit client manifests.

Example placeholder format only:

```text
<64 lowercase hex sha256>  illumio-pce-ui-<version>.x86_64.signingkey
<64 lowercase hex sha256>  illumio-pce-<version>.el9.x86_64.rpm
<64 lowercase hex sha256>  illumio-pce-ui-<version>.x86_64.rpm
<64 lowercase hex sha256>  server.crt
<64 lowercase hex sha256>  server.key
<64 lowercase hex sha256>  ca.crt
```

Create a real manifest from trusted staged files:

```bash
cd /usr/local/src
sha256sum \
  illumio-pce-ui-<version>.x86_64.signingkey \
  illumio-pce-<version>.el9.x86_64.rpm \
  illumio-pce-ui-<version>.x86_64.rpm \
  server.crt \
  server.key \
  ca.crt \
  > illumio-checksums.sha256
chmod 600 illumio-checksums.sha256
```

Use it during dry run and install:

```bash
sudo CHECKSUM_MANIFEST=/usr/local/src/illumio-checksums.sha256 \
  PCE_FQDN=pce.example.internal \
  LOAD_BALANCER_IP=192.0.2.10 \
  EMAIL_ADDR=admin@example.internal \
  ./install_illumio.sh --dry-run
```

Paths in the manifest may be absolute, or relative to the manifest file's directory.

## Validate before install

After generating a real manifest outside the repo, validate it with:

```bash
scripts/validate_manifest.sh /usr/local/src/illumio-checksums.sha256
```

## Private package endpoint

If artifacts are published to the private package origin, use the staging helper instead of hand-downloading files. It consumes HTTPS manifests, plus the approved LAN-only `http://packages.hammer.lan` origin for internal QA, marked `status: "ready"`. It downloads artifacts only from the same origin as the manifest, verifies every artifact SHA256 before use, validates RPM metadata for RPM roles, and writes the `CHECKSUM_MANIFEST` consumed by `install_illumio.sh`.

```bash
sudo PACKAGE_AUTH_USER=packages \
  PACKAGE_AUTH_PASSWORD_FILE=/root/packages-basic-auth-password \
  scripts/stage_package_release.py \
    https://packages.hammerlabs.org/illumio/channels/stable.json \
    --output-dir /usr/local/src/illumio-release
```

The generated `/usr/local/src/illumio-release/install.env` contains only local file paths and the checksum manifest path. Keep endpoint credentials outside this repository.

The package endpoint should not be treated as the default path for private keys. Generate or stage server certificate material through the approved client or QA secret path.
