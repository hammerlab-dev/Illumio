#!/usr/bin/env bash

###############################################################################
# Illumio PCE Single-Node Installation Script                                  #
###############################################################################

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: sudo ./install_illumio.sh [--dry-run] [--yes]

Installs and bootstraps a single-node Illumio PCE host from locally staged RPM,
certificate, and CA files. This script is intended for one-time client installs,
not ongoing service management.

Safety controls:
  --dry-run      Validate inputs and print planned actions without changing host state.
  --yes          Confirm that host-mutating install actions are intentional.
  --help         Show this help.

Required configuration is supplied with environment variables. Defaults are only
for conventional staging paths; site-specific values such as PCE_FQDN and
LOAD_BALANCER_IP must be explicitly set.

Common variables:
  ILLUMIO_RPM_KEY          Default: /usr/local/src/illumio-pce-ui-24.5.0.UI1-2981.x86_64.signingkey
  ILLUMIO_PCE_RPM          Default: /usr/local/src/illumio-pce-24.5.0-2379.el9.x86_64.rpm
  ILLUMIO_UI_RPM           Default: /usr/local/src/illumio-pce-ui-24.5.0.UI1-2981.x86_64.rpm (optional)
  SERVER_CERT_PATH         Default: /usr/local/src/illumio.dev.crt
  SERVER_KEY_PATH          Default: /usr/local/src/illumio.dev.key
  CA_CERT                  Default: /usr/local/src/ca.crt
  RUN_ENV_FILE             Default: /etc/illumio-pce/runtime_env.yml
  PCE_FQDN                 Required, no safe default
  LOAD_BALANCER_IP         Required, no safe default
  EMAIL_ADDR               Required, no safe default
  LOGIN_BANNER             Default: No unauthorized access!
  SERVICE_DISCOVERY_FQDN   Default: same as PCE_FQDN
  ADMIN_EMAIL              Optional; prompted if empty
  FULL_NAME                Optional; prompted if empty
  ORG_NAME                 Optional; prompted if empty
  ADMIN_PASSWORD_FILE      Optional path to a root-readable file containing the initial password
  CHECKSUM_MANIFEST        Optional sha256sum-compatible manifest for staged package/signing files
  ALLOW_CONTAINER_INSTALL  Set to 1 only with vendor approval to bypass the container/LXC guard
EOF
}

DRY_RUN=0
ASSUME_YES=0

while (($#)); do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      ;;
    --yes)
      ASSUME_YES=1
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "[ERROR] Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

log() { printf '[INFO] %s\n' "$*"; }
warn() { printf '[WARN] %s\n' "$*" >&2; }
fatal() { printf '[ERROR] %s\n' "$*" >&2; exit 1; }

run() {
  if ((DRY_RUN)); then
    printf '[DRY-RUN]'
    printf ' %q' "$@"
    printf '\n'
  else
    "$@"
  fi
}

write_file() {
  local path=$1
  local mode=${2:-0644}
  local owner=${3:-root:root}
  local tmp

  if ((DRY_RUN)); then
    log "Would write ${path} (mode ${mode}, owner ${owner})"
    cat >/dev/null
    return 0
  fi

  tmp="$(mktemp "${path}.tmp.XXXXXX")"
  cat >"$tmp"
  chmod "$mode" "$tmp"
  chown "$owner" "$tmp"
  mv "$tmp" "$path"
}

yaml_escape() {
  local value=$1
  value=${value//\\/\\\\}
  value=${value//\"/\\\"}
  printf '"%s"' "$value"
}

require_file() {
  local file=$1
  [[ -f "$file" ]] || fatal "Required file not found: ${file}"
}

require_command() {
  local command_name=$1
  command -v "$command_name" >/dev/null 2>&1 || fatal "Required command not found: ${command_name}"
}

validate_not_placeholder() {
  local name=$1
  local value=$2
  [[ -n "$value" ]] || fatal "${name} must be set"
  case "$value" in
    x.x.x.x|example.com|illumio.dev|admin@email.com|changeme|CHANGE_ME|TODO|TODO_*)
      fatal "${name} is still a placeholder (${value}); set a site-specific value"
      ;;
  esac
}

check_fqdn_resolution() {
  local fqdn=$1
  local expected_ip=$2
  local resolved_ips

  if ! command -v getent >/dev/null 2>&1; then
    warn "Cannot validate DNS for ${fqdn}; getent is not available."
    return 0
  fi

  resolved_ips="$(getent ahostsv4 "$fqdn" 2>/dev/null | awk '{print $1}' | sort -u || true)"
  if [[ -z "$resolved_ips" ]]; then
    warn "${fqdn} does not resolve from this host. The PCE may redirect browsers to https://${fqdn}:8443, so create DNS before user validation."
    return 0
  fi

  if grep -Fxq "$expected_ip" <<<"$resolved_ips"; then
    log "${fqdn} resolves to ${expected_ip}."
  else
    warn "${fqdn} resolves to ${resolved_ips//$'\n'/, }, but LOAD_BALANCER_IP is ${expected_ip}. Browser access may fail after redirect."
  fi
}

check_login_url() {
  local url="https://${PCE_FQDN}:8443/login"

  if ! command -v curl >/dev/null 2>&1; then
    warn "curl is not available; skipping login URL smoke check for ${url}."
    return 0
  fi

  if curl -kfsSI --connect-timeout 10 "$url" >/dev/null; then
    log "Login URL responded: ${url}"
  else
    warn "Login URL did not respond cleanly: ${url}. Check DNS, firewall policy, certificate state, and PCE web services."
  fi
}

verify_checksum_manifest() {
  local manifest=$1
  local manifest_dir manifest_file

  [[ -n "$manifest" ]] || return 0
  require_command sha256sum
  require_file "$manifest"

  manifest_dir="$(cd "$(dirname "$manifest")" && pwd)"
  manifest_file="$(basename "$manifest")"
  log "Verifying staged files with checksum manifest: ${manifest}"
  (cd "$manifest_dir" && sha256sum --check --strict "$manifest_file")
}

validate_rpm_package() {
  local file=$1
  local label=$2

  require_file "$file"
  rpm -qp --queryformat '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}\n' "$file" >/dev/null 2>&1 ||
    fatal "${label} is not a readable RPM package: ${file}"
}

is_container_environment() {
  if command -v systemd-detect-virt >/dev/null 2>&1 && systemd-detect-virt --quiet --container; then
    return 0
  fi

  if [[ -f /.dockerenv || -f /run/.containerenv ]]; then
    return 0
  fi

  if grep -qaE 'container=|lxc|docker|kubepods|libpod' /proc/1/environ /proc/self/cgroup 2>/dev/null; then
    return 0
  fi

  return 1
}

check_supported_host() {
  if ! is_container_environment; then
    return 0
  fi

  if ((DRY_RUN)); then
    warn "Container/LXC environment detected. Dry-run will continue, but real install requires a VM or bare-metal host unless Illumio approves this platform."
    return 0
  fi

  if [[ "${ALLOW_CONTAINER_INSTALL:-0}" == "1" ]]; then
    warn "Container/LXC environment detected and ALLOW_CONTAINER_INSTALL=1 is set. Continuing despite likely kernel/module/sysctl failures."
    return 0
  fi

  fatal "Container/LXC environment detected. Illumio PCE install needs host-level kernel, module, and sysctl controls; use a VM or bare-metal host, or set ALLOW_CONTAINER_INSTALL=1 only with vendor approval."
}

trap 'fatal "An unexpected error occurred near line ${LINENO}"' ERR

# File paths. Defaults match historical staging names, but can be overridden.
ILLUMIO_RPM_KEY="${ILLUMIO_RPM_KEY:-/usr/local/src/illumio-pce-ui-24.5.0.UI1-2981.x86_64.signingkey}"
ILLUMIO_PCE_RPM="${ILLUMIO_PCE_RPM:-/usr/local/src/illumio-pce-24.5.0-2379.el9.x86_64.rpm}"
ILLUMIO_UI_RPM="${ILLUMIO_UI_RPM:-/usr/local/src/illumio-pce-ui-24.5.0.UI1-2981.x86_64.rpm}"
SERVER_CERT_PATH="${SERVER_CERT_PATH:-/usr/local/src/illumio.dev.crt}"
SERVER_KEY_PATH="${SERVER_KEY_PATH:-/usr/local/src/illumio.dev.key}"
CA_CERT="${CA_CERT:-/usr/local/src/ca.crt}"
RUN_ENV_FILE="${RUN_ENV_FILE:-/etc/illumio-pce/runtime_env.yml}"
CHECKSUM_MANIFEST="${CHECKSUM_MANIFEST:-}"

# Site configuration. Intentionally no safe defaults for customer-specific data.
PCE_FQDN="${PCE_FQDN:-}"
LOGIN_BANNER="${LOGIN_BANNER:-No unauthorized access!}"
EMAIL_ADDR="${EMAIL_ADDR:-}"
SERVICE_DISCOVERY_FQDN="${SERVICE_DISCOVERY_FQDN:-$PCE_FQDN}"
LOAD_BALANCER_IP="${LOAD_BALANCER_IP:-}"

# Admin details. Password is prompted or read from a file to avoid hardcoding.
ADMIN_EMAIL="${ADMIN_EMAIL:-}"
FULL_NAME="${FULL_NAME:-}"
ORG_NAME="${ORG_NAME:-}"
ADMIN_PASSWORD_FILE="${ADMIN_PASSWORD_FILE:-}"
unset ADMIN_PASSWORD ADMIN_PASSWORD2
ADMIN_PASSWORD=""

if [[ $EUID -ne 0 ]]; then
  fatal "This script must be run as root. Use --dry-run on a non-production workstation only if root is available."
fi

require_command openssl
require_command rpm
require_command dnf
require_command systemctl
require_command sudo
require_command update-ca-trust
require_command modprobe
require_command sysctl
validate_not_placeholder PCE_FQDN "$PCE_FQDN"
validate_not_placeholder SERVICE_DISCOVERY_FQDN "$SERVICE_DISCOVERY_FQDN"
validate_not_placeholder LOAD_BALANCER_IP "$LOAD_BALANCER_IP"
validate_not_placeholder EMAIL_ADDR "$EMAIL_ADDR"
check_fqdn_resolution "$PCE_FQDN" "$LOAD_BALANCER_IP"

required_files=("$ILLUMIO_RPM_KEY" "$ILLUMIO_PCE_RPM" "$SERVER_CERT_PATH" "$SERVER_KEY_PATH" "$CA_CERT")
for file in "${required_files[@]}"; do
  require_file "$file"
done

validate_rpm_package "$ILLUMIO_PCE_RPM" "ILLUMIO_PCE_RPM"
if [[ -f "$ILLUMIO_UI_RPM" ]]; then
  validate_rpm_package "$ILLUMIO_UI_RPM" "ILLUMIO_UI_RPM"
fi

if [[ -n "$ADMIN_PASSWORD_FILE" ]]; then
  require_file "$ADMIN_PASSWORD_FILE"
  [[ -r "$ADMIN_PASSWORD_FILE" ]] || fatal "ADMIN_PASSWORD_FILE is not readable by root: ${ADMIN_PASSWORD_FILE}"
fi

verify_checksum_manifest "$CHECKSUM_MANIFEST"

if ((DRY_RUN)); then
  log "Dry run selected; no host changes will be made."
elif ((ASSUME_YES)); then
  log "Install confirmation received via --yes."
else
  fatal "Refusing to mutate this host without --yes. Re-run with --dry-run first, then --yes when ready."
fi

check_supported_host

SERVICE_DISCOVERY_KEY="$(openssl rand -base64 32)"

log "Updating CA trust store..."
run cp "$CA_CERT" /etc/pki/ca-trust/source/anchors/
run update-ca-trust

log "Installing prerequisite packages..."
run dnf install -y \
  bind-utils bzip2 ca-certificates chkconfig initscripts ipset logrotate \
  net-tools openssh-clients patch postfix procps-ng tcpdump traceroute \
  util-linux expect

log "Configuring systemd limits..."
run mkdir -p /etc/systemd/system/illumio-pce.service.d
write_file /etc/systemd/system/illumio-pce.service.d/override.conf 0644 root:root <<'EOF'
[Service]
LimitCORE=0
LimitNOFILE=65535
LimitNPROC=65535
EOF

log "Configuring system limits and kernel parameters..."
run mkdir -p /etc/sysctl.d
write_file /etc/sysctl.d/99-illumio.conf 0644 root:root <<'EOF'
fs.file-max = 2000000
net.core.somaxconn = 16384
EOF

run sysctl -p /etc/sysctl.d/99-illumio.conf
run modprobe nf_conntrack

if ((DRY_RUN)); then
  log "Would set nf_conntrack hashsize to 262144"
else
  echo 262144 >/sys/module/nf_conntrack/parameters/hashsize
fi
run mkdir -p /etc/modprobe.d
write_file /etc/modprobe.d/illumio.conf 0644 root:root <<'EOF'
options nf_conntrack hashsize=262144
EOF

run systemctl daemon-reload

log "Importing Illumio GPG key..."
run rpm --import "$ILLUMIO_RPM_KEY"

log "Installing Illumio PCE RPM..."
run rpm -Uvh "$ILLUMIO_PCE_RPM"

if [[ -f "$ILLUMIO_UI_RPM" ]]; then
  log "Installing Illumio PCE UI RPM..."
  run rpm -Uvh "$ILLUMIO_UI_RPM"
else
  warn "Illumio UI RPM not found at ${ILLUMIO_UI_RPM}; skipping optional UI package."
fi

log "Setting up certificates..."
run mkdir -p /var/lib/illumio-pce/cert
run cp "$SERVER_CERT_PATH" /var/lib/illumio-pce/cert/server.crt
run cp "$SERVER_KEY_PATH" /var/lib/illumio-pce/cert/server.key
run chmod 400 /var/lib/illumio-pce/cert/server.crt /var/lib/illumio-pce/cert/server.key
run chown ilo-pce:ilo-pce /var/lib/illumio-pce/cert/server.crt /var/lib/illumio-pce/cert/server.key
run chown root:ilo-pce /etc/illumio-pce

log "Generating runtime environment file..."
run mkdir -p "$(dirname "$RUN_ENV_FILE")"
write_file "$RUN_ENV_FILE" 0640 root:ilo-pce <<EOF
install_root: "/opt/illumio-pce"
runtime_data_root: "/var/lib/illumio-pce/runtime"
persistent_data_root: "/var/lib/illumio-pce/data"
ephemeral_data_root: "/var/lib/illumio-pce/tmp"
log_dir: "/var/log/illumio-pce"
private_key_cache_dir: "/var/lib/illumio-pce/keys"
pce_fqdn: $(yaml_escape "$PCE_FQDN")
login_banner: $(yaml_escape "$LOGIN_BANNER")
service_discovery_fqdn: $(yaml_escape "$SERVICE_DISCOVERY_FQDN")
cluster_public_ips:
  cluster_fqdn:
  - $(yaml_escape "$LOAD_BALANCER_IP")
node_type: snc0
web_service_private_key: $(yaml_escape "/var/lib/illumio-pce/cert/server.key")
web_service_certificate: $(yaml_escape "/var/lib/illumio-pce/cert/server.crt")
email_address: $(yaml_escape "$EMAIL_ADDR")
service_discovery_encryption_key: $(yaml_escape "$SERVICE_DISCOVERY_KEY")
insecure_tls_weak_ciphers_enabled: false
expose_user_invitation_link: true
EOF

log "Validating runtime environment..."
run illumio-pce-env setup --list --test

log "Starting PCE at runlevel 1..."
run sudo -u ilo-pce illumio-pce-ctl start --runlevel 1
if ((DRY_RUN)); then
  log "Would wait 120 seconds for PCE startup"
else
  sleep 120
fi

log "Initializing PCE database..."
run sudo -u ilo-pce illumio-pce-db-management setup

log "Setting PCE runlevel to 5..."
run sudo -u ilo-pce illumio-pce-ctl set-runlevel 5
if ((DRY_RUN)); then
  log "Would wait 120 seconds for PCE runlevel transition"
else
  sleep 120
fi

log "Checking cluster status..."
run sudo -u ilo-pce illumio-pce-ctl cluster-status

if ((DRY_RUN)); then
  log "Dry run complete before initial admin creation."
  exit 0
fi

log "Checking administrative details..."
if [[ -z "$ADMIN_EMAIL" ]]; then
  read -r -p "Enter initial admin email address: " ADMIN_EMAIL
fi
if [[ -z "$FULL_NAME" ]]; then
  read -r -p "Enter full name: " FULL_NAME
fi
if [[ -z "$ORG_NAME" ]]; then
  read -r -p "Enter Organization Name: " ORG_NAME
fi

validate_not_placeholder ADMIN_EMAIL "$ADMIN_EMAIL"
validate_not_placeholder FULL_NAME "$FULL_NAME"
validate_not_placeholder ORG_NAME "$ORG_NAME"

admin_password_tmp=""
cleanup_admin_password_tmp() {
  if [[ -n "$admin_password_tmp" && -f "$admin_password_tmp" ]]; then
    rm -f "$admin_password_tmp"
  fi
}
trap cleanup_admin_password_tmp EXIT

if [[ -n "$ADMIN_PASSWORD_FILE" ]]; then
  ADMIN_PASSWORD_PATH="$ADMIN_PASSWORD_FILE"
else
  read -r -s -p "Enter admin password: " ADMIN_PASSWORD
  echo
  read -r -s -p "Re-enter admin password: " ADMIN_PASSWORD2
  echo
  if [[ "$ADMIN_PASSWORD" != "$ADMIN_PASSWORD2" ]]; then
    fatal "Passwords do not match."
  fi
  [[ -n "$ADMIN_PASSWORD" ]] || fatal "Admin password must not be empty"
  admin_password_tmp="$(mktemp /tmp/illumio-admin-password.XXXXXX)"
  chmod 600 "$admin_password_tmp"
  printf '%s' "$ADMIN_PASSWORD" >"$admin_password_tmp"
  unset ADMIN_PASSWORD ADMIN_PASSWORD2
  ADMIN_PASSWORD_PATH="$admin_password_tmp"
fi

[[ -s "$ADMIN_PASSWORD_PATH" ]] || fatal "Admin password file must not be empty"

log "Creating initial PCE user account..."
export ADMIN_EMAIL FULL_NAME ORG_NAME ADMIN_PASSWORD_PATH
/usr/bin/expect <<'EOF'
set timeout -1
set password_file [open $env(ADMIN_PASSWORD_PATH) r]
set admin_password [read $password_file]
close $password_file
set admin_password [string trimright $admin_password "\r\n"]
spawn sudo -u ilo-pce illumio-pce-db-management create-domain --user-name $env(ADMIN_EMAIL) --full-name $env(FULL_NAME) --org-name $env(ORG_NAME)
expect "Enter Password:"
log_user 0
send -- "$admin_password\r"
expect "Re-enter Password:"
send -- "$admin_password\r"
expect eof
log_user 1
EOF
unset ADMIN_PASSWORD_PATH
cleanup_admin_password_tmp
trap - EXIT

log "Checking browser login URL..."
check_login_url

log "Installation complete. You should now be able to access the PCE via https://${PCE_FQDN}:8443"
