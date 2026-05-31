# Changelog

All notable client-install and maintenance changes are tracked here.

## Unreleased

- Add a real-install preflight guard for container/LXC hosts and document the VM/bare-metal requirement.
- Apply only the Illumio sysctl file instead of replaying every host sysctl configuration file.
- Add maintenance and release workflow documentation.
- Add checksum manifest maintenance process and validation helper.

## 2026-05-01

- Hardened install helper with dry-run and explicit `--yes` gate.
- Added optional checksum manifest verification.
- Added client-install checklist, checksum example docs, CI, and repository checks.
