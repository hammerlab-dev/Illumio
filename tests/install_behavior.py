#!/usr/bin/env python3
"""Exercise install failure paths without modifying the host or using real secrets."""

import http.server
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import tempfile
import threading
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "install_illumio.sh").read_text(encoding="utf-8")
FUNCTIONS = SCRIPT.split("trap 'fatal", 1)[0]
EXPECT = SCRIPT.split("/usr/bin/expect <<'EOF'\n", 1)[1].split("\nEOF", 1)[0]


class InstallerBehavior(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.bin = self.directory / "bin"
        self.bin.mkdir()
        self.env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}")

    def command(self, name, source):
        path = self.bin / name
        path.write_text(source, encoding="utf-8")
        path.chmod(0o700)

    def shell(self, source, **env):
        return subprocess.run(
            ["bash", "-c", FUNCTIONS + "\n" + source],
            env=dict(self.env, **env), capture_output=True, text=True, timeout=10,
        )

    def test_service_readiness_returns_without_fixed_sleep(self):
        self.command("sudo", '#!/bin/sh\ncase "$4" in status) echo "Illumio Runtime System RUNNING [1]"; exit 1;; get-runlevel) echo "Current PCE runlevel is 1";; esac\n')
        result = self.shell("PCE_STARTUP_TIMEOUT_SECONDS=1; wait_for_pce 1; echo ready")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ready", result.stdout)

    def test_full_runlevel_requires_standard_success_and_matching_level(self):
        self.command("sudo", '#!/bin/sh\ncase "$4" in status) echo "Illumio Runtime System RUNNING 3.20s"; exit 0;; get-runlevel) echo "Current PCE runlevel is 5";; esac\n')
        result = self.shell("PCE_STARTUP_TIMEOUT_SECONDS=1; wait_for_pce 5")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_configured_wait_reaches_vendor_command(self):
        self.command("sudo", '#!/bin/sh\ncase "$4" in status) [ "$6" = --wait ] && [ "$7" = 7 ] && [ "$8" = --stdexit ] || exit 2; echo "Illumio Runtime System RUNNING 3.20s";; get-runlevel) echo "Current PCE runlevel is 5";; esac\n')
        result = self.shell("PCE_STARTUP_TIMEOUT_SECONDS=7; wait_for_pce 5")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_full_runlevel_rejects_success_without_running_summary(self):
        self.command("sudo", '#!/bin/sh\ncase "$4" in status) echo "Illumio Runtime System PARTIAL 3.20s";; get-runlevel) echo "Current PCE runlevel is 5";; esac\n')
        result = self.shell("PCE_STARTUP_TIMEOUT_SECONDS=1; wait_for_pce 5")
        self.assertNotEqual(result.returncode, 0)

    def test_cluster_check_uses_standard_exit_semantics(self):
        self.command("sudo", '#!/bin/sh\n[ "$4" = cluster-status ] && [ "$5" = --stdexit ] && exit 0\nexit 1\n')
        self.command("systemctl", '#!/bin/sh\nprintf "%s\\n" "$*" >> "$BOOT_CALLS"\ncase "$*" in daemon-reload|"enable illumio-pce") exit 0;; *) exit 1;; esac\n')
        command = SCRIPT.split('log "Checking cluster status..."', 1)[1].split('if ((DRY_RUN))', 1)[0]
        calls = self.directory / "boot-calls"
        result = self.shell(command, BOOT_CALLS=str(calls))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls.read_text().splitlines(), ["daemon-reload", "enable illumio-pce"])

    def test_failed_cluster_check_does_not_enable_boot(self):
        self.command("sudo", '#!/bin/sh\nexit 2\n')
        self.command("systemctl", '#!/bin/sh\ntouch "$BOOT_CALLS"\n')
        command = SCRIPT.split('log "Checking cluster status..."', 1)[1].split('if ((DRY_RUN))', 1)[0]
        calls = self.directory / "boot-calls"
        result = self.shell(command, BOOT_CALLS=str(calls))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(calls.exists())

    def test_boot_enablement_is_planned_without_execution_in_dry_run(self):
        self.command("systemctl", '#!/bin/sh\ntouch "$BOOT_CALLS"\nexit 1\n')
        command = SCRIPT.split('log "Checking cluster status..."', 1)[1].split('if ((DRY_RUN))', 1)[0]
        calls = self.directory / "boot-calls"
        result = self.shell('DRY_RUN=1\n' + command, BOOT_CALLS=str(calls))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(calls.exists())
        self.assertIn("systemctl daemon-reload", result.stdout)
        self.assertIn("systemctl enable illumio-pce", result.stdout)

    def test_healthy_status_at_wrong_runlevel_is_rejected(self):
        self.command("sudo", '#!/bin/sh\ncase "$4" in status) echo "Illumio Runtime System RUNNING [1]"; exit 1;; get-runlevel) echo "Current PCE runlevel is 5";; esac\n')
        result = self.shell("PCE_STARTUP_TIMEOUT_SECONDS=1; wait_for_pce 1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unexpected runlevel", result.stderr)

    def test_exit_one_without_running_summary_is_rejected(self):
        self.command("sudo", '#!/bin/sh\ncase "$4" in status) exit 1;; get-runlevel) echo "Current PCE runlevel is 1";; esac\n')
        result = self.shell("PCE_STARTUP_TIMEOUT_SECONDS=1; wait_for_pce 1")
        self.assertNotEqual(result.returncode, 0)

    def test_partial_or_stopped_status_is_rejected(self):
        for status in (2, 3, 127):
            with self.subTest(status=status):
                self.command("sudo", f'#!/bin/sh\nexit {status}\n')
                result = self.shell("PCE_STARTUP_TIMEOUT_SECONDS=1; wait_for_pce 1")
                self.assertNotEqual(result.returncode, 0)

    def test_service_timeout_stops_before_next_step(self):
        self.command("sudo", "#!/bin/sh\nexec sleep 30\n")
        result = self.shell("PCE_STARTUP_TIMEOUT_SECONDS=1; wait_for_pce 5; echo continued")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("continued", result.stdout)
        self.assertIn("exit 124", result.stderr)

    def test_invalid_timeout_is_rejected(self):
        for value in ("0", "-1", "1.5", "forever"):
            with self.subTest(value=value):
                result = self.shell('validate_timeout PCE_STARTUP_TIMEOUT_SECONDS "$VALUE"', VALUE=value)
                self.assertNotEqual(result.returncode, 0)

    def test_snc_configuration_covers_direct_sessions_and_database_memory(self):
        result = self.shell('''run() { :; }
write_file() { printf 'FILE %s\\n' "$1"; cat; }
configure_snc_host_limits
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('FILE /etc/security/limits.d/99-illumio-pce.conf', result.stdout)
        for kind in ('soft', 'hard'):
            for resource, value in (('core', 0), ('nofile', 65535), ('nproc', 65535)):
                self.assertIn(f'ilo-pce {kind} {resource} {value}\n', result.stdout)
        for setting in ('vm.overcommit_memory = 1', 'fs.file-max = 2000000', 'net.core.somaxconn = 16384'):
            self.assertIn(setting + '\n', result.stdout)

    def bootstrap(self, mode):
        self.command("sudo", """#!/usr/bin/env python3
import os, sys, time
mode = os.environ['TEST_MODE']
if mode == 'early':
    sys.exit(17)
print('Enter Password:', flush=True)
first = input()
print('Re-enter Password:', flush=True)
second = input()
if mode == 'timeout':
    time.sleep(30)
sys.exit(37 if mode == 'failure' else (0 if first == second else 38))
""")
        password = self.directory / "password"
        password.write_text("synthetic-test-password\n", encoding="utf-8")
        env = dict(self.env, ADMIN_PASSWORD_PATH=str(password), ADMIN_EMAIL="test@example.invalid",
                   FULL_NAME="Test User", ORG_NAME="Test", ADMIN_BOOTSTRAP_TIMEOUT_SECONDS="1",
                   TEST_MODE=mode)
        result = subprocess.run(["expect"], input=EXPECT, env=env, capture_output=True,
                                text=True, timeout=5)
        self.assertNotIn("synthetic-test-password", result.stdout + result.stderr)
        return result

    def test_bootstrap_success(self):
        result = self.bootstrap("success")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_bootstrap_child_failure_is_not_success(self):
        self.assertEqual(self.bootstrap("failure").returncode, 37)

    def test_bootstrap_early_exit_is_not_success(self):
        self.assertNotEqual(self.bootstrap("early").returncode, 0)

    def test_bootstrap_timeout_is_not_success(self):
        self.assertEqual(self.bootstrap("timeout").returncode, 124)

    def test_login_requires_trusted_hostname_and_http_success(self):
        cert = self.directory / "server.crt"
        key = self.directory / "server.key"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                        "-keyout", str(key), "-out", str(cert), "-days", "1",
                        "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost"],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        class Handler(http.server.BaseHTTPRequestHandler):
            status = 200

            def do_HEAD(self):
                self.send_response(self.status)
                self.end_headers()

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        curl = shutil.which("curl")
        source = '''curl() { "$REAL_CURL" "$@" --noproxy '*' --connect-to "${PCE_FQDN}:8443:127.0.0.1:${TEST_PORT}"; }
check_login_url
'''
        env = dict(REAL_CURL=curl, TEST_PORT=str(server.server_port), CA_CERT=str(cert))
        valid = self.shell(source, PCE_FQDN="localhost", **env)
        self.assertEqual(valid.returncode, 0, valid.stderr)
        wrong_hostname = self.shell(source, PCE_FQDN="wrong.example.invalid", **env)
        self.assertNotEqual(wrong_hostname.returncode, 0)
        self.assertIn("verification failed", wrong_hostname.stderr)
        Handler.status = 500
        http_error = self.shell(source, PCE_FQDN="localhost", **env)
        self.assertNotEqual(http_error.returncode, 0)


if __name__ == "__main__":
    unittest.main()
