# Client install checklist

Use this checklist before running `install_illumio.sh` on a client Illumio PCE host.

## 1. Confirm target host

- Host is the intended single-node PCE target.
- Host is a VM or bare-metal system, not a container/LXC, unless Illumio has explicitly approved that platform.
- OS is an EL9/RHEL-like system with `dnf`, `rpm`, systemd, and required Illumio package compatibility.
- You have an approved maintenance window.
- You have rollback or rebuild access for the host.

## 2. Stage local artifacts

Stage artifacts outside the repository, commonly under `/usr/local/src`:

- Illumio PCE RPM
- Optional Illumio UI RPM
- Illumio signing key
- server certificate
- server private key
- CA certificate
- optional checksum manifest
- optional admin password file

Do not commit any of these files.

## 3. Prepare configuration

Required environment values:

- `PCE_FQDN`
- `LOAD_BALANCER_IP`
- `EMAIL_ADDR`

Optional overrides:

- `SERVICE_DISCOVERY_FQDN`
- `LOGIN_BANNER`
- `RUN_ENV_FILE`
- artifact path variables listed in `README.md`
- `CHECKSUM_MANIFEST`
- `ADMIN_PASSWORD_FILE`
- `ALLOW_CONTAINER_INSTALL` only when Illumio has approved a container/LXC target.

## 4. Verify checksums when possible

If a trusted manifest is available, pass it with `CHECKSUM_MANIFEST`. See `docs/checksum-manifest-example.md`.

## 5. Dry run first

```bash
sudo CHECKSUM_MANIFEST=/usr/local/src/illumio-checksums.sha256 \
  PCE_FQDN=pce.example.internal \
  LOAD_BALANCER_IP=192.0.2.10 \
  EMAIL_ADDR=admin@example.internal \
  ./install_illumio.sh --dry-run
```

If using the private package endpoint, stage artifacts first with `scripts/stage_package_release.py`. Do not consume an endpoint manifest until it is `status: "ready"` and all downloaded artifact hashes validate.

Review every planned action before proceeding.

If the dry run reports a container/LXC warning, move the install to a VM or bare-metal host before running `--yes`.

## 6. Confirm real install intentionally

Only after the dry run looks correct:

```bash
sudo CHECKSUM_MANIFEST=/usr/local/src/illumio-checksums.sha256 \
  PCE_FQDN=pce.example.internal \
  LOAD_BALANCER_IP=192.0.2.10 \
  EMAIL_ADDR=admin@example.internal \
  ./install_illumio.sh --yes
```

Without `--yes`, the script must refuse host mutation.

## 7. Post-install checks

- Confirm `illumio-pce-ctl cluster-status` is healthy.
- Confirm the service reaches the expected runlevel.
- Confirm the admin account can sign in.
- Store local admin password files securely or destroy them according to the client procedure.
- Record the exact artifact versions and checksum manifest used.
