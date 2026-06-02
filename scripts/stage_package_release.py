#!/usr/bin/env python3
"""Stage Illumio install artifacts from a private package manifest."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen


HEX64 = re.compile(r"^[0-9a-f]{64}$")
ENV_BY_ROLE = {
    "rpm_key": "ILLUMIO_RPM_KEY",
    "pce_rpm": "ILLUMIO_PCE_RPM",
    "ui_rpm": "ILLUMIO_UI_RPM",
    "server_cert": "SERVER_CERT_PATH",
    "server_key": "SERVER_KEY_PATH",
    "ca_cert": "CA_CERT",
}
RPM_ROLES = {"pce_rpm", "ui_rpm"}


def fatal(message: str) -> None:
    print(f"[ERROR] {message}", file=sys.stderr)
    raise SystemExit(1)


def read_basic_auth_header(user: str | None, password_file: str | None) -> str | None:
    if not user and not password_file:
        return None
    if not user or not password_file:
        fatal("PACKAGE_AUTH_USER and PACKAGE_AUTH_PASSWORD_FILE must be supplied together")
    password = Path(password_file).read_text(encoding="utf-8").rstrip("\r\n")
    if not password:
        fatal("PACKAGE_AUTH_PASSWORD_FILE is empty")
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def fetch_bytes(url: str, auth_header: str | None) -> bytes:
    headers = {"User-Agent": "illumio-package-stager/1.0"}
    if auth_header:
        headers["Authorization"] = auth_header
    with urlopen(Request(url, headers=headers), timeout=30) as response:
        return response.read()


def allowed_http_hosts() -> set[str]:
    raw_hosts = os.environ.get("PACKAGE_ALLOW_HTTP_HOSTS", "")
    return {host.strip().lower() for host in raw_hosts.split(",") if host.strip()}


def parse_manifest_url(url: str):
    parsed = urlparse(url)
    if parsed.scheme == "https":
        return parsed
    if parsed.scheme == "http" and parsed.hostname and parsed.hostname.lower() in allowed_http_hosts():
        return parsed
    fatal("Manifest URL must use HTTPS, or PACKAGE_ALLOW_HTTP_HOSTS must explicitly allow the local HTTP host")


def require_same_origin(manifest_url: str, artifact_url_value: str) -> str:
    manifest = urlparse(manifest_url)
    artifact = urlparse(artifact_url_value)
    if artifact.scheme not in {"http", "https"} or not artifact.netloc:
        fatal(f"Artifact URL must be absolute HTTP(S): {artifact_url_value}")
    if (artifact.scheme, artifact.netloc) != (manifest.scheme, manifest.netloc):
        fatal(f"Artifact URL must stay on manifest origin: {artifact_url_value}")
    return artifact_url_value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_command(command: str) -> None:
    if shutil.which(command) is None:
        fatal(f"Required command not found: {command}")


def validate_rpm(path: Path) -> None:
    result = subprocess.run(
        ["rpm", "-qp", "--queryformat", "%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}\n", str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        fatal(f"Downloaded artifact is not a readable RPM: {path}")


def artifact_url(manifest_url: str, release_base_url: str | None, artifact: dict[str, object]) -> str:
    path = str(artifact.get("path", ""))
    if path:
        if ".." in Path(path).parts:
            fatal(f"Invalid artifact path in manifest: {path!r}")
        if path.startswith("/"):
            manifest = urlparse(manifest_url)
            return urlunparse((manifest.scheme, manifest.netloc, path, "", "", ""))
        base = release_base_url or manifest_url
        if not base.endswith("/"):
            base += "/"
        return require_same_origin(manifest_url, urljoin(base, path))

    if "url" in artifact:
        return require_same_origin(manifest_url, str(artifact["url"]))

    fatal("Artifact must include path or url")


def artifact_name(artifact: dict[str, object]) -> str:
    return str(artifact.get("filename") or artifact.get("name") or Path(str(artifact.get("path", ""))).name)


def is_pce_rpm(artifact: dict[str, object]) -> bool:
    name = artifact_name(artifact)
    return (
        artifact.get("kind") == "rpm"
        and name.startswith("illumio-pce-")
        and not name.startswith("illumio-pce-ui-")
    )


def is_ui_rpm(artifact: dict[str, object]) -> bool:
    return artifact.get("kind") == "rpm" and artifact_name(artifact).startswith("illumio-pce-ui-")


def select_one(candidates: list[dict[str, object]], role: str) -> dict[str, object]:
    if not candidates:
        fatal(f"Manifest is missing required artifact role: {role}")
    if len(candidates) > 1:
        names = ", ".join(artifact_name(candidate) for candidate in candidates)
        fatal(f"Manifest has multiple candidates for {role}; add explicit roles: {names}")
    return candidates[0]


def infer_artifact_roles(manifest: dict[str, object]) -> list[dict[str, object]]:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        fatal("Manifest must contain a non-empty artifacts list")

    if any(isinstance(artifact, dict) and artifact.get("role") for artifact in artifacts):
        return artifacts

    version = str(manifest.get("version", ""))
    pce_candidates = [artifact for artifact in artifacts if isinstance(artifact, dict) and is_pce_rpm(artifact) and ".el9." in artifact_name(artifact)]
    ui_candidates = [
        artifact
        for artifact in artifacts
        if isinstance(artifact, dict)
        and is_ui_rpm(artifact)
        and (not version or artifact_name(artifact).startswith(f"illumio-pce-ui-{version}."))
    ]
    key_candidates = [
        artifact
        for artifact in artifacts
        if isinstance(artifact, dict)
        and artifact.get("kind") == "signing-key"
        and artifact_name(artifact).startswith("illumio-pce-ui-")
        and (not version or artifact_name(artifact).startswith(f"illumio-pce-ui-{version}."))
    ]

    selected = [
        dict(select_one(key_candidates, "rpm_key"), role="rpm_key"),
        dict(select_one(pce_candidates, "pce_rpm"), role="pce_rpm"),
    ]
    if ui_candidates:
        selected.append(dict(select_one(ui_candidates, "ui_rpm"), role="ui_rpm", required=False))
    return selected


def validate_release_base(manifest_url: str, release_base_url: object) -> str | None:
    if not release_base_url:
        return None
    base_url = str(release_base_url)
    parsed = urlparse(base_url)
    if parsed.scheme or parsed.netloc:
        return require_same_origin(manifest_url, base_url)
    if ".." in Path(base_url).parts:
        fatal(f"Invalid base_url in manifest: {base_url!r}")
    return urljoin(manifest_url, base_url)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest_url", help="HTTPS URL for the channel or release manifest")
    parser.add_argument("--output-dir", default="/usr/local/src/illumio-release", help="Directory for staged artifacts")
    parser.add_argument("--auth-user", default=os.environ.get("PACKAGE_AUTH_USER"))
    parser.add_argument("--auth-password-file", default=os.environ.get("PACKAGE_AUTH_PASSWORD_FILE"))
    args = parser.parse_args()

    manifest_origin = parse_manifest_url(args.manifest_url)
    if manifest_origin.scheme == "http" and (args.auth_user or args.auth_password_file):
        fatal("Package credentials are not allowed with HTTP manifests")

    auth_header = read_basic_auth_header(args.auth_user, args.auth_password_file)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_dir.chmod(0o700)

    manifest = json.loads(fetch_bytes(args.manifest_url, auth_header).decode("utf-8"))
    if manifest.get("product") != "illumio-pce":
        fatal("Manifest product must be illumio-pce")
    if manifest.get("status") != "ready":
        fatal(f"Manifest is not ready: status={manifest.get('status')!r}")

    artifacts = infer_artifact_roles(manifest)
    release_base_url = validate_release_base(args.manifest_url, manifest.get("base_url"))
    checksum_lines: list[str] = []
    env_lines: list[str] = []
    seen_roles: set[str] = set()

    if any(isinstance(artifact, dict) and artifact.get("role") in RPM_ROLES for artifact in artifacts):
        require_command("rpm")

    for artifact in artifacts:
        if not isinstance(artifact, dict):
            fatal("Each artifact entry must be an object")
        role = str(artifact.get("role", ""))
        filename = str(artifact.get("filename") or Path(str(artifact.get("path", ""))).name)
        expected_sha = str(artifact.get("sha256", ""))
        required = bool(artifact.get("required", True))

        if role not in ENV_BY_ROLE:
            fatal(f"Unsupported artifact role: {role!r}")
        if not filename or "/" in filename or filename in {".", ".."}:
            fatal(f"Invalid artifact filename for role {role}: {filename!r}")
        if not HEX64.match(expected_sha):
            fatal(f"Invalid sha256 for role {role}: {expected_sha!r}")

        url = artifact_url(args.manifest_url, str(release_base_url) if release_base_url else None, artifact)
        destination = output_dir / filename
        destination.write_bytes(fetch_bytes(url, auth_header))
        actual_sha = sha256_file(destination)
        if actual_sha != expected_sha:
            destination.unlink(missing_ok=True)
            fatal(f"SHA256 mismatch for {filename}: expected {expected_sha}, got {actual_sha}")

        if role in RPM_ROLES:
            validate_rpm(destination)

        checksum_lines.append(f"{actual_sha}  {destination.name}")
        if required or role != "ui_rpm":
            env_lines.append(f"{ENV_BY_ROLE[role]}={destination}")
        elif destination.exists():
            env_lines.append(f"{ENV_BY_ROLE[role]}={destination}")
        seen_roles.add(role)

    for role in ("rpm_key", "pce_rpm"):
        if role not in seen_roles:
            fatal(f"Manifest is missing required artifact role: {role}")

    checksum_path = output_dir / "illumio-checksums.sha256"
    checksum_path.write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
    checksum_path.chmod(0o600)

    env_path = output_dir / "install.env"
    env_path.write_text("\n".join(env_lines + [f"CHECKSUM_MANIFEST={checksum_path}"]) + "\n", encoding="utf-8")
    env_path.chmod(0o600)

    print(f"Staged {len(artifacts)} artifacts in {output_dir}")
    print(f"Checksum manifest: {checksum_path}")
    print(f"Installer env file: {env_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
