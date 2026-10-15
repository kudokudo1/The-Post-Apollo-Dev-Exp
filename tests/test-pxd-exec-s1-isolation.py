#!/usr/bin/env python3
"""PX EXEC-S1: offline fake-secret OS sandbox probe, never an AI provider.

Only disposable synthetic fixtures. NOT a production provider launcher, an
authentication broker, or a certified security sandbox.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ENVIRONMENT = {
    "HOME": "/tmp", "PATH": "/usr/bin:/bin", "TMPDIR": "/tmp",
    "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
    "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
}
# No inherited HOME, PX_HOSPITAL_DB, CODEX_HOME, XDG_RUNTIME_DIR or API tokens.

class IsolationUnavailable(RuntimeError):
    """Fail closed when a required isolation boundary cannot be established."""

def validated_fixture(root: Path) -> tuple[Path, Path, Path]:
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise IsolationUnavailable("EXEC-S1: fixture root must be an absolute real directory")
    root = root.resolve(strict=True)
    patient, scratch, private = (root / n for n in ("patient", "scratch", "private"))
    for path in (patient, scratch, private):
        if path.is_symlink() or not path.is_dir() or path.resolve(strict=True) != path:
            raise IsolationUnavailable("EXEC-S1: invalid fixture directory " + path.name)
        if path.parent != root:
            raise IsolationUnavailable("EXEC-S1: fixture escaped private root")
    return patient, scratch, private

def build_command(root: Path, program: str, *, bwrap_binary: str = "/usr/bin/bwrap") -> list[str]:
    """Build a fixed, test-only sandbox command. Never uses a shell interpreter."""
    patient, scratch, _ = validated_fixture(root)
    if not Path(bwrap_binary).is_absolute():
        raise IsolationUnavailable("EXEC-S1: bwrap path must be absolute")
    if not isinstance(program, str) or not program:
        raise IsolationUnavailable("EXEC-S1: explicit probe required")
    args = [
        bwrap_binary,
        "--unshare-all", "--die-with-parent", "--new-session",
        "--cap-drop", "ALL",
        "--ro-bind", "/usr", "/usr",
        "--symlink", "usr/bin", "/bin",
        "--symlink", "usr/lib", "/lib",
        "--symlink", "usr/lib64", "/lib64",
        "--symlink", "usr/sbin", "/sbin",
        "--proc", "/proc", "--dev", "/dev",
        "--dir", "/var", "--dir", "/home",
        "--tmpfs", "/tmp",
        "--ro-bind", str(patient), "/patient",
        "--bind", str(scratch), "/scratch",
        "--clearenv",
    ]
    for key, value in ENVIRONMENT.items():
        args.extend(("--setenv", key, value))
    args.extend(("--chdir", "/scratch", "/usr/bin/python3", "-B", "-c", program))
    return args

PROBE = r'''
import json, os, pathlib, socket
p = pathlib.Path
checks = {}
checks["patient_read"] = p("/patient/sentinel.txt").read_text() == "SAFE-PATIENT-FIXTURE"
try:
    p("/patient/unwanted.txt").write_text("DENIED")
except OSError:
    checks["patient_write_denied"] = True
else:
    checks["patient_write_denied"] = False
p("/scratch/probe-result.txt").write_text("SCRATCH-WRITE")
checks["scratch_write"] = p("/scratch/probe-result.txt").read_text() == "SCRATCH-WRITE"
checks["fake_secret_unreadable"] = not p("/private/canary.txt").exists()
checks["fake_codex_auth_unreadable"] = not p("/private/.codex/auth.json").exists()
checks["host_tmp_hidden"] = not p(FAKE_CANARY_LOCATION).exists()
checks["different_network_namespace"] = os.readlink("/proc/self/ns/net") != PARENT_NETWORK_NAMESPACE
checks["other_host_paths_hidden"] = not p("/run/user").exists() and not p("/etc/passwd").exists()
for name in ("OPENAI_API_KEY", "GITHUB_TOKEN", "GH_TOKEN", "CODEX_HOME",
             "PX_HOSPITAL_DB", "XDG_RUNTIME_DIR", "HOST_FAKE_CANARY"):
    checks["env_" + name + "_absent"] = name not in os.environ
checks["home_is_private"] = os.environ.get("HOME") == "/tmp"
try:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    status = sock.connect_ex(("1.1.1.1", 443))
    checks["direct_network_denied"] = status != 0
    sock.close()
except OSError:
    checks["direct_network_denied"] = True
print(json.dumps(checks, sort_keys=True))
raise SystemExit(0 if all(checks.values()) else 7)
'''

def smoke() -> dict:
    binary = shutil.which("bwrap")
    if not binary:
        raise IsolationUnavailable("EXEC-S1: bwrap missing; no unrestricted fallback")
    if not Path("/usr/bin/python3").exists() or not Path("/usr").is_dir():
        raise IsolationUnavailable("EXEC-S1: read-only system runtime missing")
    with tempfile.TemporaryDirectory(prefix="px-exec-s1-") as temp:
        root = Path(temp).resolve(strict=True)
        os.chmod(root, 0o700)
        for name in ("patient", "scratch", "private"):
            (root / name).mkdir(mode=0o700)
        (root / "patient" / "sentinel.txt").write_text("SAFE-PATIENT-FIXTURE")
        (root / "private" / "canary.txt").write_text("FAKE-SECRET-NOT-A-REAL-CREDENTIAL")
        (root / "private" / ".codex").mkdir(mode=0o700)
        (root / "private" / ".codex" / "auth.json").write_text('{"fake":"no-real-credential"}')
        fake_path = str(root / "private" / "canary.txt")
        poisoned_parent = {
            "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8",
            "OPENAI_API_KEY": "FAKE-OPENAI-KEY",
            "GITHUB_TOKEN": "FAKE-GITHUB-TOKEN", "GH_TOKEN": "FAKE-GH-TOKEN",
            "CODEX_HOME": str(root / "private" / ".codex"),
            "PX_HOSPITAL_DB": str(root / "private" / "fake-hospital.db"),
            "XDG_RUNTIME_DIR": str(root / "private"),
            "HOST_FAKE_CANARY": fake_path,
        }
        # Pass the fake canary's path, but never its content, to the child.
        probe = ("FAKE_CANARY_LOCATION = " + repr(fake_path) + "\n"
                 + "PARENT_NETWORK_NAMESPACE = " + repr(os.readlink("/proc/self/ns/net")) + "\n"
                 + PROBE)
        cmd = build_command(root, probe, bwrap_binary=str(Path(binary).resolve()))
        try:
            result = subprocess.run(cmd, env=poisoned_parent, text=True,
                                    capture_output=True, timeout=20, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise IsolationUnavailable("EXEC-S1: sandbox did not complete: " + str(exc)) from exc
        if result.returncode:
            raise IsolationUnavailable(
                "EXEC-S1: sandbox failed closed, exit " + str(result.returncode)
                + ": " + (result.stderr.strip() or result.stdout.strip())[-1000:]
            )
        try:
            checks = json.loads(result.stdout.strip())
        except json.JSONDecodeError as exc:
            raise IsolationUnavailable("EXEC-S1: invalid probe evidence") from exc
        if not checks or not all(value is True for value in checks.values()):
            raise IsolationUnavailable("EXEC-S1: negative assertion failed: " + repr(checks))
        if (root / "patient" / "unwanted.txt").exists():
            raise IsolationUnavailable("EXEC-S1: Patient unexpectedly mutated")
        if (root / "private" / "canary.txt").read_text() != "FAKE-SECRET-NOT-A-REAL-CREDENTIAL":
            raise IsolationUnavailable("EXEC-S1: private fixture unexpectedly mutated")
        if (root / "scratch" / "probe-result.txt").read_text() != "SCRATCH-WRITE":
            raise IsolationUnavailable("EXEC-S1: scratch write not observed")
        return {
            "state": "PASS", "checks": checks,
            "realProviderCalls": 0, "realSecretsUsed": False,
            "liveHospitalAccess": False, "profile": "EXEC-S1-OFFLINE-FIXTURE",
        }

class TestPolicy(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="px-exec-s1-unit-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve(strict=True)
        for name in ("patient", "scratch", "private"):
            (self.root / name).mkdir()

    def test_confined_mounts_and_namespaces(self):
        args = build_command(self.root, "print('probe')")
        for flag in ("--unshare-all", "--die-with-parent", "--new-session",
                     "--cap-drop", "--clearenv", "--tmpfs"):
            self.assertIn(flag, args)
        self.assertEqual(args.count("--ro-bind"), 2)
        triplets = [args[i:i + 3] for i in range(len(args) - 2)]
        self.assertIn(["--ro-bind", str(self.root / "patient"), "/patient"], triplets)
        self.assertIn(["--bind", str(self.root / "scratch"), "/scratch"], triplets)
        self.assertNotIn(["--ro-bind", "/", "/"], triplets)
        self.assertNotIn(str(self.root / "private"), args)
        for secret in ("OPENAI_API_KEY", "GITHUB_TOKEN", "GH_TOKEN",
                       "CODEX_HOME", "PX_HOSPITAL_DB"):
            self.assertNotIn(secret, args)

    def test_symlink_mount_rejected(self):
        (self.root / "patient").rmdir()
        (self.root / "patient").symlink_to(self.root / "private", target_is_directory=True)
        with self.assertRaises(IsolationUnavailable):
            build_command(self.root, "print('probe')")

    def test_missing_mount_rejected(self):
        (self.root / "scratch").rmdir()
        with self.assertRaises(IsolationUnavailable):
            build_command(self.root, "print('probe')")

    def test_relative_bwrap_rejected(self):
        with self.assertRaises(IsolationUnavailable):
            build_command(self.root, "print('probe')", bwrap_binary="bwrap")

    def test_fake_secrets_not_in_allowlist(self):
        self.assertEqual(ENVIRONMENT["HOME"], "/tmp")
        for key in ("CODEX_HOME", "PX_HOSPITAL_DB", "OPENAI_API_KEY", "GITHUB_TOKEN"):
            self.assertNotIn(key, ENVIRONMENT)

    def test_missing_bwrap_fails_closed(self):
        from unittest import mock
        with mock.patch.object(shutil, "which", return_value=None):
            with self.assertRaisesRegex(IsolationUnavailable, "no unrestricted fallback"):
                smoke()

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    modes = ap.add_mutually_exclusive_group(required=True)
    modes.add_argument("--unit", action="store_true")
    modes.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    if args.unit:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestPolicy)
        return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1
    try:
        result = smoke()
    except IsolationUnavailable as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
