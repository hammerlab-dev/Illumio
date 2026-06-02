# Repo review - 2026-05-31

## Scope

Reviewed the Illumio PCE single-node install helper and tested it in a disposable Proxmox LXC:

- Host: internal Proxmox node
- Test CT: disposable LXC
- OS: Rocky Linux 9.4
- IP: private lab address

No client RPMs, real signing keys, real certificates, or secrets were used. The LXC used dummy staged files and a one-day self-signed certificate only to exercise installer control flow.

## Findings

The installer is intentionally host-mutating and already has good safety controls:

- `--dry-run` validation mode
- explicit `--yes` gate for real changes
- required site-specific values
- checksum manifest support
- password-file support for non-interactive admin bootstrap
- repository static checks

The main issue found during LXC testing was platform mismatch. A real run in a Proxmox LXC failed during kernel/sysctl configuration:

```text
sysctl: permission denied on key "kernel.yama.ptrace_scope"
sysctl: permission denied on key "kernel.core_pattern"
sysctl: permission denied on key "fs.file-max"
```

That is expected for unprivileged containers: the PCE install path needs host-level control over kernel modules and sysctls. A VM or bare-metal host is the safer default target.

## Changes made

- Added a container/LXC preflight guard for real installs.
- Kept container `--dry-run` useful, but it now warns clearly that real install should move to a VM or bare-metal host.
- Added `ALLOW_CONTAINER_INSTALL=1` as an explicit vendor-approval override.
- Changed sysctl application from `sysctl --system` to `sysctl -p /etc/sysctl.d/99-illumio.conf` so the script applies only the Illumio settings it writes.
- Updated README, install checklist, changelog, and static checks.

## Validation

Local repository checks:

```text
18 static checks passed
Illumio repository checks passed.
```

LXC dry-run after the change:

```text
[INFO] Dry run selected; no host changes will be made.
[WARN] Container/LXC environment detected. Dry-run will continue, but real install requires a VM or bare-metal host unless Illumio approves this platform.
[INFO] Dry run complete before initial admin creation.
```

LXC real run after the change:

```text
[INFO] Install confirmation received via --yes.
[ERROR] Container/LXC environment detected. Illumio PCE install needs host-level kernel, module, and sysctl controls; use a VM or bare-metal host, or set ALLOW_CONTAINER_INSTALL=1 only with vendor approval.
```

Override test with `ALLOW_CONTAINER_INSTALL=1` still fails at the expected LXC kernel/sysctl boundary:

```text
sysctl: permission denied on key "fs.file-max"
net.core.somaxconn = 16384
```

## Recommendation

Do not deploy the Illumio PCE installer to Proxmox LXC by default. Use an EL9/RHEL-like VM with adequate rollback/rebuild access, stage the real Illumio artifacts outside the repo, run `--dry-run`, then run `--yes` only after the dry-run output is reviewed.

## VM follow-up

After the LXC test, the helper was tested in a disposable Rocky Linux 9.8 Proxmox VM:

- Host: internal Proxmox node
- Test VM: disposable VM
- IP: private lab address

The VM `--dry-run` passed without a container warning. A real `--yes` run with a valid Rocky RPM GPG key and a dummy PCE RPM got through prerequisite package install, targeted sysctl application, and `nf_conntrack` module handling, then failed at the dummy RPM artifact:

```text
fs.file-max = 2000000
net.core.somaxconn = 16384
[INFO] Importing Illumio GPG key...
[INFO] Installing Illumio PCE RPM...
error: open of dummy-rpm failed: No such file or directory
```

That showed the VM platform is viable past the LXC-only kernel/sysctl boundary, but also exposed a sequencing issue: invalid RPM artifacts were detected only after host mutation. The helper now validates staged RPM files with `rpm -qp` before making host changes.

Re-running the updated helper with the same dummy RPM now stops before the install confirmation or any host-mutating phase:

```text
[ERROR] ILLUMIO_PCE_RPM is not a readable RPM package: /usr/local/src/illumio-pce-24.5.0-2379.el9.x86_64.rpm
```
