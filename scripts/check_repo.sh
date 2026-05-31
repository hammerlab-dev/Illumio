#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

bash -n install_illumio.sh
bash -n scripts/validate_manifest.sh
python3 -m py_compile scripts/stage_package_release.py
python3 tests/static_checks.py
./install_illumio.sh --help >/dev/null
git diff --check

forbidden='(^|/)\.env($|\.)|(^|/)secrets/|(^|/)client-data/|\.rpm$|\.key$|\.pem$|\.p12$|\.pfx$|\.crt$|\.csr$|\.log$|\.bak(\.|$)|(^|/)backups/|(^|/)__pycache__/|\.pyc$'
if git ls-files | grep -E "$forbidden"; then
  echo "Forbidden client, secret, package, backup, or generated paths are tracked." >&2
  exit 1
fi

echo "Illumio repository checks passed."
