# Changelog

All notable client-install and maintenance changes are tracked here.

## Unreleased

- Pass the configured service startup wait to Illumio as well as the external timeout, avoiding its shorter default wait.
- Verify native full-runlevel status output and use standard exit semantics for the final cluster check.
- Interpret Illumio's explicit standard status codes for each expected runlevel and verify the reported runlevel before continuing.
- Apply the SNC database memory setting and PAM process/file limits for direct PCE user sessions; verify limits before startup.
- Fail initial admin creation on command errors, missing prompts, or a configurable timeout while keeping password output suppressed.
- Replace fixed startup delays with bounded PCE service-readiness checks.
- Require the final login smoke check to pass certificate hostname/CA and HTTP validation.
- Add a real-install preflight guard for container/LXC hosts and document the VM/bare-metal requirement.
- Apply only the Illumio sysctl file instead of replaying every host sysctl configuration file.
- Validate staged RPM files before making host changes.
- Add maintenance and release workflow documentation.
- Add checksum manifest maintenance process and validation helper.

## 2026-05-01

- Hardened install helper with dry-run and explicit `--yes` gate.
- Added optional checksum manifest verification.
- Added client-install checklist, checksum example docs, CI, and repository checks.
