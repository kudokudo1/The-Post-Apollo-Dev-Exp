#!/usr/bin/env python3
"""B38-D: disposable Linux OS evidence for fake credential/tool isolation.

Reuses the existing EXEC-S1 Bubblewrap launcher; no real provider, Hermes,
auth token, production credentials, live Hospital data or local installation.
Requires a trusted root-owned /usr/bin/bwrap; missing isolation fails CLOSED.
"""
import argparse
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


class Refused(RuntimeError):
    pass


def denied(code):
    raise Refused("B38D_REFUSED_" + code)


def load_s1():
    path = Path(__file__).resolve().with_name("test-pxd-exec-s1-isolation.py")
    if not path.is_file():
        denied("ACCEPTED_S1_MISSING")
    loader = importlib.machinery.SourceFileLoader("b38d_accepted_s1", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:
        denied("ACCEPTED_S1_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


PROBE = r'''
import json, os, pathlib, socket
p = pathlib.Path
checks = {}
checks["different_net_namespace"] = os.readlink("/proc/self/ns/net") != HOST_NET_NS
checks["different_pid_namespace"] = os.readlink("/proc/self/ns/pid") != HOST_PID_NS
checks["private_home"] = os.environ.get("HOME") == "/tmp"
checks["cwd_in_scratch"] = os.getcwd() == "/scratch"
checks["host_secret_path_hidden"] = not p(HOST_FAKE_SECRET_PATH).exists()
checks["private_mount_hidden"] = not p("/private/fake-provider-auth.json").exists()
checks["host_socket_hidden"] = not p("/run/user").exists()
checks["fake_hospital_hidden"] = not p("/private/fake-hospital.db").exists()
checks["scratch_only_writable"] = True
try:
    p("/patient/unauthorized.txt").write_text("bad")
except OSError:
    pass
else:
    checks["scratch_only_writable"] = False
checks["patient_readable"] = p("/patient/fixture.txt").read_text() == "FAKE-PATIENT-READONLY"
p("/scratch/child-proof.txt").write_text("FAKE-CHILD-SCRATCH")
checks["scratch_write"] = p("/scratch/child-proof.txt").read_text() == "FAKE-CHILD-SCRATCH"
for name in ("OPENAI_API_KEY", "GH_TOKEN", "CODEX_HOME", "PX_HOSPITAL_DB",
             "XDG_RUNTIME_DIR", "PARENT_CANARY"):
    checks["env_" + name + "_absent"] = name not in os.environ
checks["parent_auth_fd_absent"] = True
for fd in p("/proc/self/fd").iterdir():
    try:
        target = os.readlink(str(fd))
    except OSError:
        continue
    if "fake-provider-auth.json" in target or HOST_FAKE_SECRET_PATH in target:
        checks["parent_auth_fd_absent"] = False
try:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    checks["direct_ipv4_egress_denied"] = sock.connect_ex(("1.1.1.1", 443)) != 0
    sock.close()
except OSError:
    checks["direct_ipv4_egress_denied"] = True
print(json.dumps(checks, sort_keys=True))
raise SystemExit(0 if all(value is True for value in checks.values()) else 7)
'''

EXPECTED = frozenset((
    "different_net_namespace", "different_pid_namespace", "private_home",
    "cwd_in_scratch", "host_secret_path_hidden", "private_mount_hidden",
    "host_socket_hidden", "fake_hospital_hidden", "scratch_only_writable",
    "patient_readable", "scratch_write", "parent_auth_fd_absent",
    "direct_ipv4_egress_denied",
    "env_OPENAI_API_KEY_absent", "env_GH_TOKEN_absent",
    "env_CODEX_HOME_absent", "env_PX_HOSPITAL_DB_absent",
    "env_XDG_RUNTIME_DIR_absent", "env_PARENT_CANARY_absent",
))


def validate_evidence(raw):
    if type(raw) is not dict or set(raw) != EXPECTED or any(
        value is not True for value in raw.values()
    ):
        denied("KERNEL_OBSERVATION_INVALID")
    return raw


def smoke():
    s1 = load_s1()
    try:
        s1.trusted_bwrap_binary()
    except s1.IsolationUnavailable:
        denied("TRUSTED_SANDBOX_UNAVAILABLE")
    with tempfile.TemporaryDirectory(prefix="b38d-disposable-") as tmp:
        root = Path(tmp).resolve(strict=True)
        root.chmod(0o700)
        for name in ("patient", "scratch", "private"):
            (root / name).mkdir(mode=0o700)
        (root / "patient" / "fixture.txt").write_text("FAKE-PATIENT-READONLY")
        private = root / "private" / "fake-provider-auth.json"
        private.write_text('{"kind":"SYNTHETIC_ONLY","token":"FAKE-B38D-NOT-A-KEY"}')
        private.chmod(0o600)
        fake_host_path = str(private)
        program = (
            "HOST_NET_NS = " + repr(os.readlink("/proc/self/ns/net")) + "\n"
            + "HOST_PID_NS = " + repr(os.readlink("/proc/self/ns/pid")) + "\n"
            + "HOST_FAKE_SECRET_PATH = " + repr(fake_host_path) + "\n"
            + PROBE
        )
        try:
            cmd = s1.build_command(root, program)
        except s1.IsolationUnavailable:
            denied("SANDBOX_COMMAND_REFUSED")
        # Only disposable canaries are placed into the parent process env.
        # The fixed S1 Bubblewrap command clears them before the child runs.
        poisoned_parent = {
            "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8",
            "OPENAI_API_KEY": "FAKE-B38D-PARENT-CANARY",
            "GH_TOKEN": "FAKE-GH-CANARY",
            "CODEX_HOME": str(root / "private"),
            "PX_HOSPITAL_DB": str(root / "private" / "fake-hospital.db"),
            "XDG_RUNTIME_DIR": str(root / "private"),
            "PARENT_CANARY": "FAKE-PARENT-VALUE",
        }
        if cmd[0] != "/usr/bin/bwrap" or "--clearenv" not in cmd:
            denied("SANDBOX_PROFILE_REFUSED")
        try:
            with private.open("rb") as held_fd:
                if not held_fd.read(1):
                    denied("FAKE_AUTH_EMPTY")
                run = subprocess.run(
                    cmd, env=poisoned_parent, text=True, capture_output=True,
                    close_fds=True, timeout=25, check=False,
                )
        except (OSError, subprocess.TimeoutExpired):
            denied("SANDBOX_EXECUTION_FAILED")
        if run.returncode != 0:
            denied("SANDBOX_EXIT_NONZERO")
        try:
            checks = validate_evidence(json.loads(run.stdout))
        except (ValueError, TypeError):
            denied("EVIDENCE_PARSE_FAILED")
        if (run.stderr.strip() or
                (root / "patient" / "unauthorized.txt").exists() or
                (root / "scratch" / "child-proof.txt").read_text() !=
                "FAKE-CHILD-SCRATCH" or
                private.read_text() !=
                '{"kind":"SYNTHETIC_ONLY","token":"FAKE-B38D-NOT-A-KEY"}'):
            denied("POST_CHILD_FIXTURE_INVARIANT")
        return {
            "state": "OFFLINE_KERNEL_PROBE_PASS",
            "checks": checks,
            "providerCalls": 0,
            "realCredentialsUsed": False,
            "liveHospitalAccess": False,
            "productionReady": False,
            "verifiedRealCredentialIsolation": False,
            "verifiedRealModelRuntimeIsolation": False,
        }


class StaticRegressionTests(unittest.TestCase):
    def test_exact_observation_keys_and_true_boolean_only(self):
        valid = {key: True for key in EXPECTED}
        self.assertEqual(validate_evidence(valid), valid)
        for bad in ({}, {**valid, "extra": True},
                    {**valid, "direct_ipv4_egress_denied": False},
                    {**valid, "scratch_write": 1},
                    {k: True for k in EXPECTED if k != "parent_auth_fd_absent"}):
            with self.assertRaisesRegex(Refused, "KERNEL_OBSERVATION_INVALID"):
                validate_evidence(bad)

    def test_missing_sandbox_refuses_no_fallback(self):
        s1 = load_s1()
        with mock.patch.object(s1, "trusted_bwrap_binary",
                               side_effect=s1.IsolationUnavailable("missing")):
            # smoke loads a fresh module; simulate rejection through loader.
            with mock.patch(__name__ + ".load_s1", return_value=s1):
                with self.assertRaisesRegex(Refused, "TRUSTED_SANDBOX_UNAVAILABLE"):
                    smoke()

    def test_accepted_launcher_has_kernel_namespace_and_env_guards(self):
        s1 = load_s1()
        with tempfile.TemporaryDirectory(prefix="b38d-unit-") as tmp:
            root = Path(tmp).resolve(strict=True)
            for n in ("patient", "scratch", "private"):
                (root / n).mkdir()
            cmd = s1.build_command(root, PROBE)
        self.assertEqual(cmd[0], "/usr/bin/bwrap")
        for flag in ("--unshare-all", "--clearenv", "--die-with-parent",
                     "--new-session", "--cap-drop", "--tmpfs"):
            self.assertIn(flag, cmd)
        self.assertNotIn(str(root / "private"), cmd)
        self.assertNotIn("FAKE-B38D-NOT-A-KEY", repr(cmd))

    def test_probe_never_contains_real_auth_or_network_client(self):
        self.assertNotIn("api.openai.com", PROBE)
        self.assertNotIn("hermes", PROBE.lower())
        self.assertNotIn("FAKE-B38D-NOT-A-KEY", PROBE)


def main():
    ap = argparse.ArgumentParser()
    modes = ap.add_mutually_exclusive_group(required=True)
    modes.add_argument("--unit", action="store_true")
    modes.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    if args.unit:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(StaticRegressionTests)
        return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1
    try:
        outcome = smoke()
    except Refused as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(outcome, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
