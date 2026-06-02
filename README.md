# Illumio PCE install helper

This repo is a small, intentionally boring helper for one-time Illumio PCE single-node installs. It is meant for client-side install work where the real Illumio artifacts are already staged on the target host.

It is not a daemon, not a standing service, and not something to run just to see what happens. It changes a host for real.

## Read this before running it

`install_illumio.sh` mutates the target host. It installs RPMs, changes sysctl and module settings, writes Illumio config, starts PCE services, initializes the database, and creates the first admin domain. That is a lot of confidence to place in one shell script, so the script tries to make accidental installs difficult.

The short version:

1. Stage the real client artifacts on the target host.
2. Set the required environment variables.
3. Run `--dry-run` first and read what it plans to do.
4. Run the real install only when you mean it, with `--yes`.

Dry run first:

```bash
sudo PCE_FQDN=pce.example.internal \
  LOAD_BALANCER_IP=192.0.2.10 \
  EMAIL_ADDR=admin@example.internal \
  ./install_illumio.sh --dry-run
```

Then, only on the intended target host:

```bash
sudo PCE_FQDN=pce.example.internal \
  LOAD_BALANCER_IP=192.0.2.10 \
  EMAIL_ADDR=admin@example.internal \
  ./install_illumio.sh --yes
```

Without `--yes`, real execution refuses to proceed. That is on purpose.

## What you need to stage

Put the Illumio packages and certificates on the target host before running the helper. The defaults match the historical `/usr/local/src` staging layout, but every path can be overridden.

Required or commonly staged files:

- `ILLUMIO_RPM_KEY`
- `ILLUMIO_PCE_RPM`
- `ILLUMIO_UI_RPM` (optional, skipped if absent)
- `SERVER_CERT_PATH`
- `SERVER_KEY_PATH`
- `CA_CERT`
- `RUN_ENV_FILE`

Site-specific values have no safe defaults. Set them every time:

- `PCE_FQDN`
- `LOAD_BALANCER_IP`
- `EMAIL_ADDR`

Optional bootstrap and verification values:

- `ADMIN_EMAIL`
- `FULL_NAME`
- `ORG_NAME`
- `ADMIN_PASSWORD_FILE`, preferred for non-interactive installs. Do not commit this file.
- `CHECKSUM_MANIFEST`, an optional `sha256sum`-compatible manifest for staged RPM, signing, and certificate files.
- `ALLOW_CONTAINER_INSTALL`, an advanced override for container/LXC hosts. Leave it unset unless Illumio has explicitly approved the platform.

Do not commit client RPMs, private keys, certificates, password files, logs, local environment files, or client-specific checksum manifests. Future-you will appreciate the restraint.

## Host requirements

Run the installer on an EL9/RHEL-like VM or bare-metal host with host-level kernel, module, sysctl, systemd, RPM, and dnf control.

Linux containers and Proxmox LXCs are not a safe default target for this helper. The script allows `--dry-run` in a container so operators can validate inputs, but real installs fail early unless `ALLOW_CONTAINER_INSTALL=1` is set. Use that override only with vendor approval, because PCE setup changes kernel/module/sysctl state that containers commonly cannot own.

## Optional checksum verification

When possible, create a checksum manifest from a trusted source after receiving or staging the real artifacts. Do not invent hashes, and do not commit client-specific manifests.

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

Pass the manifest to the installer:

```bash
sudo CHECKSUM_MANIFEST=/usr/local/src/illumio-checksums.sha256 \
  PCE_FQDN=pce.example.internal \
  LOAD_BALANCER_IP=192.0.2.10 \
  EMAIL_ADDR=admin@example.internal \
  ./install_illumio.sh --dry-run
```

The manifest uses standard `sha256sum --check --strict` format. Paths may be absolute, or relative to the manifest file's directory.

For more detail, see `docs/checksum-manifest-example.md` and `docs/checksum-maintenance.md`.

## Private package endpoint staging

When artifacts are published through a private package endpoint, stage them locally before running the installer. The staging helper accepts HTTPS manifests with `product: "illumio-pce"` and `status: "ready"`. For isolated internal QA, an operator can explicitly allow a local HTTP manifest host with `PACKAGE_ALLOW_HTTP_HOSTS`; credentials are still refused over HTTP. The helper downloads artifacts only from the same origin as the manifest, verifies each SHA256, validates RPM metadata for RPM roles, and writes an installer env file plus `CHECKSUM_MANIFEST`. See `docs/package-manifest-schema.md` for the manifest shape.

Example:

```bash
sudo PACKAGE_AUTH_USER=packages \
  PACKAGE_AUTH_PASSWORD_FILE=/root/packages-basic-auth-password \
  scripts/stage_package_release.py \
    https://packages.example.com/illumio/channels/stable.json \
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

The package endpoint stages Illumio packages and signing keys. Server certificates, private keys, and CA certificates still need to come from the approved client or QA secret path.

## Local checks

Before changing the helper, run the basic checks:

```bash
bash -n install_illumio.sh
python3 tests/static_checks.py
```

If `shellcheck` is available, run it too:

```bash
shellcheck install_illumio.sh
```

Maintainers should run the full repo check before pushing:

```bash
scripts/check_repo.sh
```

## Before a client install

Use `docs/client-install-checklist.md` before touching a real client host. It covers the boring but important bits: target confirmation, artifact staging, dry-run review, intentional install, and post-install checks.

## Maintenance and releases

See `docs/maintenance.md` for the safe-change workflow, release tags, and rollback/recovery guidance. In practice: keep changes small, keep dry-run useful, preserve the `--yes` safety gate, and run `scripts/check_repo.sh`.
