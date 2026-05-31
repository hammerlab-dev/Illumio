#!/usr/bin/env python3
"""Static checks for the Illumio install helper."""

from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "install_illumio.sh"
text = SCRIPT.read_text(encoding="utf-8")

checks = {
    "script uses strict bash mode": "set -euo pipefail" in text,
    "real execution requires explicit --yes": "Refusing to mutate this host without --yes" in text,
    "dry-run mode is implemented": "--dry-run" in text and "DRY_RUN" in text,
    "site fqdn has no unsafe default": 'PCE_FQDN="${PCE_FQDN:-}"' in text,
    "load balancer ip has no unsafe default": 'LOAD_BALANCER_IP="${LOAD_BALANCER_IP:-}"' in text,
    "notification email has no unsafe default": 'EMAIL_ADDR="${EMAIL_ADDR:-}"' in text,
    "runtime yaml references installed certificate paths": "/var/lib/illumio-pce/cert/server.key" in text,
    "password file supported instead of hardcoded password": "ADMIN_PASSWORD_FILE" in text,
    "placeholder guard exists": "validate_not_placeholder" in text,
    "expect reads password from file path instead of process environment": "<<'EOF'" in text and "$env(ADMIN_PASSWORD_PATH)" in text and "$env(ADMIN_PASSWORD)" not in text,
    "inherited password exports are cleared before reads": "unset ADMIN_PASSWORD ADMIN_PASSWORD2" in text,
    "optional checksum manifest is supported": "CHECKSUM_MANIFEST" in text and "sha256sum --check --strict" in text,
    "container/LXC preflight guard exists": "check_supported_host" in text and "ALLOW_CONTAINER_INSTALL" in text and "Container/LXC environment detected" in text,
    "sysctl applies only Illumio settings": "sysctl -p /etc/sysctl.d/99-illumio.conf" in text and "sysctl --system" not in text,
    "rpm files are validated before mutation": "validate_rpm_package" in text and "rpm -qp --queryformat" in text,
    "manifest validation helper exists": (ROOT / "scripts" / "validate_manifest.sh").exists(),
    "help documents dry-run and yes controls": "--dry-run" in text and "--yes" in text and "--help" in text,
    "mutation refusal without explicit confirmation remains": "Refusing to mutate this host without --yes" in text,
    "placeholder validation covers unsafe defaults": "validate_not_placeholder PCE_FQDN" in text and "validate_not_placeholder LOAD_BALANCER_IP" in text and "validate_not_placeholder EMAIL_ADDR" in text,
}

failures = [name for name, ok in checks.items() if not ok]

try:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
except subprocess.CalledProcessError as exc:
    failures.append(f"bash syntax check failed: {exc.stderr.strip()}")

try:
    help_result = subprocess.run([str(SCRIPT), "--help"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if "CHECKSUM_MANIFEST" not in help_result.stdout or "--dry-run" not in help_result.stdout:
        failures.append("--help output is missing checksum or dry-run guidance")
except subprocess.CalledProcessError as exc:
    failures.append(f"--help failed: {exc.stderr.strip()}")

for forbidden in [
    'ADMIN_PASSWORD="${ADMIN_PASSWORD:-}"',
    'LOAD_BALANCER_IP="x.x.x.x"',
    'PCE_FQDN="illumio.dev"',
    'EMAIL_ADDR="admin@email.com"',
]:
    if forbidden in text:
        failures.append(f"forbidden legacy placeholder/default remains: {forbidden}")

for assignment in re.findall(r"(?im)^\s*(?:export\s+)?([A-Z0-9_]*(?:PASSWORD|TOKEN|SECRET|PRIVATE_KEY)[A-Z0-9_]*)=(.+)$", text):
    name, value = assignment
    value = value.strip()
    if name.endswith(("_FILE", "_PATH")):
        continue
    if "$" in value or "${" in value or "$(" in value or value in {'""', "''"}:
        continue
    failures.append(f"potential hardcoded sensitive assignment found: {name}")

if failures:
    print("Static checks failed:", file=sys.stderr)
    for failure in failures:
        print(f"- {failure}", file=sys.stderr)
    sys.exit(1)

print(f"{len(checks)} static checks passed")
