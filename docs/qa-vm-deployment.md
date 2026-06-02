# Illumio QA VM deployment

This runbook describes a reusable disposable-VM validation path for the
Illumio installer. It intentionally uses placeholders and documentation
addresses so the public repository does not carry site-specific hostnames,
VMIDs, IP addresses, credentials, or package endpoints.

Replace every `PCE_*`, `QA_*`, and `PACKAGE_MANIFEST_URL` value with values from
the private engagement or lab runbook before running these commands.

## Scope

- Installer source: this repository, from the release or commit being tested
- Package channel: `PACKAGE_MANIFEST_URL`
- Illumio release: `PCE_RELEASE_VERSION`
- PCE RPM: `PCE_RPM_NAME`
- UI RPM: `PCE_UI_RPM_NAME`, if used

Keep package artifacts, signing keys, certificates, private keys, admin
passwords, generated logs, and checksum manifests outside this repository.

## VM

Use a real VM or bare-metal host for meaningful validation. Linux containers and
Proxmox LXCs are useful only for dry-run input validation because PCE setup needs
host-level kernel, module, sysctl, systemd, RPM, and dnf control.

Suggested baseline:

- Hypervisor: any supported VM platform
- VMID/name: `QA_VMID` / `QA_VM_NAME`
- OS: EL9/RHEL-like VM, such as Rocky Linux 9
- Network: `QA_NETWORK`, with a static address such as `192.0.2.10/24`
- Firewall: enabled, inbound default DROP
- Allowed inbound: SSH `22`, PCE UI `8443`, and ICMP from approved management clients
- DNS: `PCE_FQDN -> LOAD_BALANCER_IP`
- Public exposure: none unless a separate security review approves it

Snapshots:

```bash
qm listsnapshot QA_VMID
```

Recommended snapshots:

- `clean-el9-baseline`
- `pre-illumio-install`
- `post-illumio-running`

## Validation Commands

Run repo checks before deployment:

```bash
scripts/check_repo.sh
```

Stage packages on the VM:

```bash
sudo scripts/stage_package_release.py \
  PACKAGE_MANIFEST_URL \
  --output-dir /usr/local/src/illumio-release
```

Verify staged artifacts:

```bash
sudo bash -lc 'cd /usr/local/src/illumio-release && sha256sum --check --strict illumio-checksums.sha256'
sudo rpm -qp --queryformat '%{NAME} %{VERSION}-%{RELEASE}.%{ARCH}\n' /usr/local/src/illumio-release/*.rpm
```

Generate or stage server certificate material through the approved private
secret path. For isolated QA only, a short-lived self-signed certificate can be
generated on the VM:

```bash
sudo openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout /usr/local/src/illumio-release/qa-server.key \
  -out /usr/local/src/illumio-release/qa-server.crt \
  -days 7 \
  -subj "/CN=PCE_FQDN" \
  -addext "subjectAltName=DNS:PCE_FQDN,IP:LOAD_BALANCER_IP"
sudo cp /usr/local/src/illumio-release/qa-server.crt /usr/local/src/illumio-release/qa-ca.crt
sudo chmod 600 /usr/local/src/illumio-release/qa-server.key
```

Run the installer dry-run before host mutation:

```bash
sudo bash -lc '
set -a
. /usr/local/src/illumio-release/install.env
set +a
SERVER_CERT_PATH=/usr/local/src/illumio-release/qa-server.crt \
SERVER_KEY_PATH=/usr/local/src/illumio-release/qa-server.key \
CA_CERT=/usr/local/src/illumio-release/qa-ca.crt \
PCE_FQDN=PCE_FQDN \
LOAD_BALANCER_IP=LOAD_BALANCER_IP \
EMAIL_ADDR=ADMIN_EMAIL_ADDRESS \
./install_illumio.sh --dry-run
'
```

After a clean dry-run, snapshot before real install:

```bash
qm snapshot QA_VMID pre-illumio-install --description "Artifacts staged and dry-run passed, before Illumio host mutation"
```

Run the real install only on the intended target:

```bash
sudo bash -lc '
set -a
. /usr/local/src/illumio-release/install.env
set +a
SERVER_CERT_PATH=/usr/local/src/illumio-release/qa-server.crt \
SERVER_KEY_PATH=/usr/local/src/illumio-release/qa-server.key \
CA_CERT=/usr/local/src/illumio-release/qa-ca.crt \
PCE_FQDN=PCE_FQDN \
LOAD_BALANCER_IP=LOAD_BALANCER_IP \
EMAIL_ADDR=ADMIN_EMAIL_ADDRESS \
./install_illumio.sh --yes
'
```

## Post-Install Checks

```bash
sudo -u ilo-pce illumio-pce-ctl cluster-status
sudo -u ilo-pce illumio-pce-ctl get-runlevel
getent hosts PCE_FQDN
curl -kI https://PCE_FQDN:8443/login
```

Expected results:

- `Cluster status: RUNNING`
- runlevel `5`
- `PCE_FQDN` resolves to `LOAD_BALANCER_IP`
- login URL returns `HTTP 200` or a documented expected redirect

Browser validation:

```bash
npx --yes playwright screenshot \
  --browser=chromium \
  --ignore-https-errors \
  https://PCE_FQDN:8443/login \
  /tmp/illumio-qa-login.png
```

The browser should show the Illumio login page. Testing only the direct IP URL
is not enough because the application may redirect users to the configured PCE
FQDN.

## Cleanup

Remove temporary QA admin password files and logs after validation:

```bash
sudo rm -f /root/illumio-admin-password /tmp/illumio-admin-create.log
```

Destroy the disposable VM when no longer needed:

```bash
qm stop QA_VMID
qm destroy QA_VMID --purge
rm -f /etc/pve/firewall/QA_VMID.fw
```

Rollback instead of destroy:

```bash
qm rollback QA_VMID pre-illumio-install
```

## Learnings

- A real VM is required for meaningful QA.
- LXC/container dry-runs are useful for input validation only.
- Package manifests must be marked `status: "ready"` before staging.
- Artifact downloads must stay on the manifest origin so endpoint credentials are not sent to an unexpected host.
- Initial admin password handling must suppress terminal echo and avoid durable logs.
- DNS for `PCE_FQDN` must exist before browser validation.
- `systemctl status illumio-pce` is not a reliable success signal for every package build. Use `illumio-pce-ctl get-runlevel` and `illumio-pce-ctl cluster-status`.
