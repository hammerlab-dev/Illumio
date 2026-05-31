# Illumio PCE install helper

This repository contains a one-time helper for client-side Illumio PCE single-node installs. It is not a daemon or standing service.

## Safety model

The installer mutates the host: it installs RPMs, changes sysctl/module settings, writes Illumio configuration, starts PCE services, initializes the database, and creates the first admin domain. For that reason it refuses real execution unless `--yes` is supplied.

Run a validation pass first:

```bash
sudo PCE_FQDN=pce.example.internal \
  LOAD_BALANCER_IP=192.0.2.10 \
  EMAIL_ADDR=admin@example.internal \
  ./install_illumio.sh --dry-run
```

Then run intentionally on the target host:

```bash
sudo PCE_FQDN=pce.example.internal \
  LOAD_BALANCER_IP=192.0.2.10 \
  EMAIL_ADDR=admin@example.internal \
  ./install_illumio.sh --yes
```

## Required inputs

Stage the Illumio RPMs, signing key, server certificate/key, and CA certificate on the target host. Defaults match the historical `/usr/local/src` staging layout, but every path can be overridden:

- `ILLUMIO_RPM_KEY`
- `ILLUMIO_PCE_RPM`
- `ILLUMIO_UI_RPM` (optional; skipped if absent)
- `SERVER_CERT_PATH`
- `SERVER_KEY_PATH`
- `CA_CERT`
- `RUN_ENV_FILE`

Site-specific values have no safe defaults and must be set:

- `PCE_FQDN`
- `LOAD_BALANCER_IP`
- `EMAIL_ADDR`

Optional admin bootstrap values:

- `ADMIN_EMAIL`
- `FULL_NAME`
- `ORG_NAME`
- `ADMIN_PASSWORD_FILE` - preferred for non-interactive installs; do not commit this file.
- `CHECKSUM_MANIFEST` - optional `sha256sum`-compatible manifest for staged RPM/signing/certificate files.
- `ALLOW_CONTAINER_INSTALL` - advanced override for container/LXC hosts. Leave unset unless Illumio has explicitly approved the platform.

## Host requirements

Run the installer on an EL9/RHEL-like VM or bare-metal host with host-level kernel, module, sysctl, systemd, RPM, and dnf control.

Linux containers and Proxmox LXCs are not a safe default target for this helper. The script allows `--dry-run` in a container so operators can validate inputs, but real installs fail early unless `ALLOW_CONTAINER_INSTALL=1` is set. Use that override only with vendor approval, because PCE setup changes kernel/module/sysctl state that containers commonly cannot own.

## Optional checksum verification

For client installs, create the checksum manifest from a trusted source after receiving or staging the real artifacts. Do not invent hashes and do not commit client-specific manifests.

Example on the staging host:

```bash
cd /usr/local/src
sha256sum \
  illumio-pce-ui-24.5.0.UI1-2981.x86_64.signingkey \
  illumio-pce-24.5.0-2379.el9.x86_64.rpm \
  illumio-pce-ui-24.5.0.UI1-2981.x86_64.rpm \
  illumio.dev.crt \
  illumio.dev.key \
  ca.crt \
  > illumio-checksums.sha256
chmod 600 illumio-checksums.sha256
```

Then pass it to the installer:

```bash
sudo CHECKSUM_MANIFEST=/usr/local/src/illumio-checksums.sha256 \
  PCE_FQDN=pce.example.internal \
  LOAD_BALANCER_IP=192.0.2.10 \
  EMAIL_ADDR=admin@example.internal \
  ./install_illumio.sh --dry-run
```

The manifest uses standard `sha256sum --check --strict` format. Paths may be absolute, or relative to the manifest file's directory.

## Private package endpoint staging

When artifacts are published through a private package endpoint, stage them locally before running the installer. The staging helper accepts only HTTPS manifests with `product: "illumio-pce"` and `status: "ready"`, downloads the listed artifacts, verifies each SHA256, validates RPM metadata for RPM roles, and writes an installer env file plus `CHECKSUM_MANIFEST`. See `docs/package-manifest-schema.md` for the manifest shape.

Example:

```bash
sudo PACKAGE_AUTH_USER=packages \
  PACKAGE_AUTH_PASSWORD_FILE=/root/packages-basic-auth-password \
  scripts/stage_package_release.py \
    https://packages.hammerlabs.org/illumio/channels/stable.json \
    --output-dir /usr/local/src/illumio-release

sudo set -a
sudo . /usr/local/src/illumio-release/install.env
sudo set +a

sudo PCE_FQDN=pce.example.internal \
  LOAD_BALANCER_IP=192.0.2.10 \
  EMAIL_ADDR=admin@example.internal \
  ./install_illumio.sh --dry-run
```

Do not pass a channel whose manifest says `status: "empty"` or `status: "pending"`. Do not bypass the generated checksum manifest.

## Local checks

```bash
bash -n install_illumio.sh
python3 tests/static_checks.py
```

If `shellcheck` is available, run it too:

```bash
shellcheck install_illumio.sh
```

## Client install readiness

Before a real client install, follow `docs/client-install-checklist.md`. For checksum manifests, see `docs/checksum-manifest-example.md`.

Repository maintainers should run:

```bash
scripts/check_repo.sh
```

## Maintenance and releases

See `docs/maintenance.md` for the safe-change workflow, release tags, and rollback/recovery guidance. See `docs/checksum-maintenance.md` for maintaining checksum manifests over time.
