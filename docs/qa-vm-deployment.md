# Illumio QA VM deployment

This note captures the disposable VM path used to validate the installer against the private package origin.

## Scope

- Repo branch: `improve/package-endpoint-validation`
- Tested commit: `49c54535478e274872947072e89a4c0e9fc17409`
- Package channel: `http://packages.hammer.lan/illumio/channels/stable.json`
- Illumio release: `25.2.40`
- PCE RPM: `illumio-pce-25.2.40-141.el9.x86_64.rpm`
- UI RPM: `illumio-pce-ui-25.2.40.UI1-95.x86_64.rpm`

## VM

- Proxmox node: `fwd-proxmox`
- VMID/name: `154` / `illumio-qa`
- OS: Rocky Linux 9.8
- Network: VLAN 117, `10.117.0.154/24`
- Firewall: Proxmox firewall enabled, inbound default DROP
- Allowed inbound: SSH `22`, PCE UI `8443`, and ICMP from management clients
- Public/Caddy exposure: none

Snapshots:

```bash
qm listsnapshot 154
```

Expected snapshots:

- `clean-el9-baseline`
- `pre-illumio-install`

## Validation Commands

Run repo checks before deployment:

```bash
scripts/check_repo.sh
```

Stage packages on the VM:

```bash
sudo scripts/stage_package_release.py \
  http://packages.hammer.lan/illumio/channels/stable.json \
  --output-dir /usr/local/src/illumio-release
```

Verify staged artifacts:

```bash
sudo bash -lc 'cd /usr/local/src/illumio-release && sha256sum --check --strict illumio-checksums.sha256'
sudo rpm -qp --queryformat '%{NAME} %{VERSION}-%{RELEASE}.%{ARCH}\n' /usr/local/src/illumio-release/*.rpm
```

Run the installer dry-run before host mutation:

```bash
sudo bash -lc '
set -a
. /usr/local/src/illumio-release/install.env
set +a
SERVER_CERT_PATH=/usr/local/src/illumio-release/illumio-qa.crt \
SERVER_KEY_PATH=/usr/local/src/illumio-release/illumio-qa.key \
CA_CERT=/usr/local/src/illumio-release/qa-ca.crt \
PCE_FQDN=illumio-qa.hammer.lan \
LOAD_BALANCER_IP=10.117.0.154 \
EMAIL_ADDR=admin@hammer.lan \
./install_illumio.sh --dry-run
'
```

After a clean dry-run, snapshot before real install:

```bash
qm snapshot 154 pre-illumio-install --description "Artifacts staged and dry-run passed, before Illumio host mutation"
```

Post-install checks:

```bash
sudo -u ilo-pce illumio-pce-ctl cluster-status
curl -kI https://10.117.0.154:8443
```

Expected results:

- `Cluster status: RUNNING`
- `HTTP/1.1 200 OK`

## Cleanup

Remove temporary QA admin password files and logs after validation:

```bash
sudo rm -f /root/illumio-admin-password /tmp/illumio-admin-create.log
```

Destroy the disposable VM when no longer needed:

```bash
qm stop 154
qm destroy 154 --purge
rm -f /etc/pve/firewall/154.fw
```

Rollback instead of destroy:

```bash
qm rollback 154 pre-illumio-install
```

## Learnings

- A real VM is required for meaningful QA. LXC/container dry-runs are useful for input validation only.
- The package origin manifest publishes `kind`, `name`, `path`, and `sha256`; the stager must infer installer roles for this live format.
- Artifact downloads must stay on the manifest origin so endpoint credentials are not sent to an unexpected host.
- Initial admin password handling must suppress terminal echo and avoid durable logs.
