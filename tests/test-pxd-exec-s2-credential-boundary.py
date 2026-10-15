#!/usr/bin/env python3
"""EXEC-S2: offline fake client/tool credential boundary. NEVER a real AI provider.

Models trusted-parent fake authentication and a separate Bubblewrap tool process.
No actual Codex, login, network model service, or live Hospital accessed.
"""
import argparse
import hmac
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import secrets
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

S1_PATH = Path(__file__).resolve().with_name("test-pxd-exec-s1-isolation.py")
TASK = "READ_SYNTHETIC_PATIENT_AND_WRITE_SCRATCH"
FAKE_AUTH_FILENAME = "fake-provider-auth.json"

class BoundaryRefusal(RuntimeError):
    """Fail closed on a fake client or tool boundary violation."""

def load_accepted_s1():
    """Reuse the accepted S1 launcher rather than inventing a weaker sandbox."""
    loader = importlib.machinery.SourceFileLoader("px_exec_s1_accepted", str(S1_PATH))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:
        raise BoundaryRefusal("EXEC-S2: accepted S1 module unavailable")
    module = importlib.util.module_from_spec(spec)
    try:
        loader.exec_module(module)
    except (OSError, ImportError) as exc:
        raise BoundaryRefusal("EXEC-S2: accepted S1 module unavailable") from exc
    return module

def checked_auth_path(root: Path) -> Path:
    private = root / "private"
    auth = private / FAKE_AUTH_FILENAME
    if (not root.is_absolute() or root.is_symlink() or not root.is_dir()
            or private.is_symlink() or not private.is_dir()):
        raise BoundaryRefusal("EXEC-S2: private fixture invalid")
    if auth.is_symlink():
        raise BoundaryRefusal("EXEC-S2: credential symlink rejected")
    try:
        st = auth.lstat()
    except OSError as exc:
        raise BoundaryRefusal("EXEC-S2: fake credential unavailable") from exc
    if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid()
            or (st.st_mode & 0o077) != 0 or st.st_nlink != 1):
        raise BoundaryRefusal("EXEC-S2: credential ownership or mode invalid")
    if auth.resolve(strict=True).parent != private.resolve(strict=True):
        raise BoundaryRefusal("EXEC-S2: credential escaped private fixture")
    return auth

class FakeModelService:
    """OFFLINE in-process stub, not a production API, server, or transport."""
    def __init__(self, expected_token: str):
        self._expected_token = expected_token
        self.calls = 0

    def request(self, token: str, context: str) -> str:
        if not hmac.compare_digest(token, self._expected_token):
            raise BoundaryRefusal("EXEC-S2: fake model authentication rejected")
        if context != "synthetic Room R-A, READ and TEST only":
            raise BoundaryRefusal("EXEC-S2: unexpected synthetic model input")
        self.calls += 1
        return TASK

class TrustedFakeClient:
    """Trusted parent holds fake auth and converts fake service reply to task."""
    def __init__(self, root: Path, service: FakeModelService):
        self.root = root
        self.service = service

    def get_task(self) -> str:
        auth_path = checked_auth_path(self.root)
        try:
            record = json.loads(auth_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise BoundaryRefusal("EXEC-S2: invalid fake credential fixture") from exc
        if not isinstance(record, dict) or record.get("kind") != "SYNTHETIC_ONLY":
            raise BoundaryRefusal("EXEC-S2: credential fixture type rejected")
        token = record.get("token")
        if not isinstance(token, str) or not token:
            raise BoundaryRefusal("EXEC-S2: missing fake authentication token")
        return self.service.request(token, "synthetic Room R-A, READ and TEST only")

def only_permitted_task(task: str) -> str:
    if task != TASK:
        raise BoundaryRefusal("EXEC-S2: unapproved tool action rejected")
    return task

def child_environment() -> dict[str, str]:
    """Poison only with fake values, never copy real host os.environ."""
    return {
        "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
        "OPENAI_API_KEY": "FAKE-OPENAI-PARENT-CANARY",
        "GH_TOKEN": "FAKE-GH-PARENT-CANARY",
        "CODEX_HOME": "/private/fake-codex-parent",
        "PX_HOSPITAL_DB": "/private/fake-hospital.db",
        "XDG_RUNTIME_DIR": "/private/fake-runtime",
    }

TOOL_PROGRAM = r'''
import json, os, pathlib, socket
p = pathlib.Path
checks = {}
checks["read_patient"] = p("/patient/fixture.txt").read_text() == "OFFLINE-PATIENT"
try:
    p("/patient/unapproved.txt").write_text("bad")
except OSError:
    checks["patient_write_denied"] = True
else:
    checks["patient_write_denied"] = False
p("/scratch/tool-output.txt").write_text("OFFLINE-TOOL-COMPLETED")
checks["scratch_write"] = p("/scratch/tool-output.txt").read_text() == "OFFLINE-TOOL-COMPLETED"
checks["private_auth_not_mounted"] = not p("/private/fake-provider-auth.json").exists()
checks["host_auth_path_hidden"] = not p(AUTH_FILE_HOST_PATH).exists()
checks["host_parent_fd_hidden"] = True
for fd in p("/proc/self/fd").iterdir():
    try:
        if "fake-provider-auth.json" in os.readlink(str(fd)):
            checks["host_parent_fd_hidden"] = False
    except OSError:
        pass
for name in ("OPENAI_API_KEY", "GH_TOKEN", "CODEX_HOME",
             "PX_HOSPITAL_DB", "XDG_RUNTIME_DIR"):
    checks["env_" + name + "_absent"] = name not in os.environ
checks["network_namespace_unshared"] = os.readlink("/proc/self/ns/net") != PARENT_NET_NS
try:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    checks["direct_egress_denied"] = sock.connect_ex(("1.1.1.1", 443)) != 0
    sock.close()
except OSError:
    checks["direct_egress_denied"] = True
print(json.dumps(checks, sort_keys=True))
raise SystemExit(0 if all(checks.values()) else 9)
'''

EXPECTED_CHECKS = frozenset({
    "read_patient", "patient_write_denied", "scratch_write",
    "private_auth_not_mounted", "host_auth_path_hidden", "host_parent_fd_hidden",
    "env_OPENAI_API_KEY_absent", "env_GH_TOKEN_absent", "env_CODEX_HOME_absent",
    "env_PX_HOSPITAL_DB_absent", "env_XDG_RUNTIME_DIR_absent",
    "network_namespace_unshared", "direct_egress_denied",
})

def validated_tool_evidence(parsed: object) -> dict[str, bool]:
    if (not isinstance(parsed, dict) or set(parsed) != EXPECTED_CHECKS
            or not all(value is True for value in parsed.values())):
        raise BoundaryRefusal("EXEC-S2: tool isolation assertion failed")
    return parsed

def execute_tool(root: Path, task: str, parent_auth_path: Path) -> dict[str, bool]:
    only_permitted_task(task)
    s1 = load_accepted_s1()
    try:
        s1.validated_fixture(root)
        s1.trusted_bwrap_binary()
    except s1.IsolationUnavailable as exc:
        raise BoundaryRefusal("EXEC-S2: S1 isolation prerequisite refused") from exc
    program = ("AUTH_FILE_HOST_PATH = " + repr(str(parent_auth_path)) + "\n"
               + "PARENT_NET_NS = " + repr(os.readlink("/proc/self/ns/net")) + "\n"
               + TOOL_PROGRAM)
    command = s1.build_command(root, program)
    # Keep fake credential fd open in trusted parent, then prove noninheritance.
    try:
        with parent_auth_path.open("rb") as held_auth_fd:
            if not held_auth_fd.read(1):
                raise BoundaryRefusal("EXEC-S2: empty fake auth fixture")
            result = subprocess.run(
                command, env=child_environment(), text=True, capture_output=True,
                check=False, timeout=20, close_fds=True,
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BoundaryRefusal("EXEC-S2: sandbox launch failed closed") from exc
    if result.returncode != 0:
        raise BoundaryRefusal("EXEC-S2: child refused or failed (exit %s)" % result.returncode)
    try:
        parsed = json.loads(result.stdout)
    except (TypeError, ValueError) as exc:
        raise BoundaryRefusal("EXEC-S2: malformed tool evidence") from exc
    validated_tool_evidence(parsed)
    if (root / "scratch" / "tool-output.txt").read_text() != "OFFLINE-TOOL-COMPLETED":
        raise BoundaryRefusal("EXEC-S2: scratch output unavailable")
    return parsed

def smoke() -> dict:
    with tempfile.TemporaryDirectory(prefix="px-exec-s2-") as tmp:
        root = Path(tmp).resolve(strict=True)
        root.chmod(0o700)
        for name in ("patient", "private", "scratch"):
            (root / name).mkdir(mode=0o700)
        (root / "patient" / "fixture.txt").write_text("OFFLINE-PATIENT")
        token = "FAKE-S2-" + secrets.token_urlsafe(24)
        auth_file = root / "private" / FAKE_AUTH_FILENAME
        auth_file.write_text(json.dumps({"kind": "SYNTHETIC_ONLY", "token": token}))
        auth_file.chmod(0o600)
        service = FakeModelService(token)
        task = TrustedFakeClient(root, service).get_task()
        checks = execute_tool(root, task, auth_file)
        if service.calls != 1 or task != TASK:
            raise BoundaryRefusal("EXEC-S2: fake client transaction incomplete")
        if (root / "patient" / "unapproved.txt").exists():
            raise BoundaryRefusal("EXEC-S2: synthetic Patient mutated")
        return {
            "state": "PASS", "profile": "EXEC-S2-OFFLINE-FAKE-CLIENT-TOOL",
            "fakeClientAuthenticated": True, "fakeClientCalls": service.calls,
            "toolIsolated": True, "checks": checks, "realModelCalls": 0,
            "realCredentialsUsed": False, "liveHospitalAccess": False,
            "productionReady": False,
        }

class S2PolicyTests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory(prefix="px-exec-s2-unit-")
        self.addCleanup(self.t.cleanup)
        self.root = Path(self.t.name).resolve(strict=True)
        for name in ("patient", "private", "scratch"):
            (self.root / name).mkdir()
        self.auth = self.root / "private" / FAKE_AUTH_FILENAME
        self.token = "FAKE-UNIT-ONLY"
        self.auth.write_text(json.dumps({"kind": "SYNTHETIC_ONLY", "token": self.token}))
        self.auth.chmod(0o600)

    def test_trusted_client_receives_fake_task(self):
        service = FakeModelService(self.token)
        self.assertEqual(TrustedFakeClient(self.root, service).get_task(), TASK)
        self.assertEqual(service.calls, 1)

    def test_wrong_fake_credential_refused(self):
        service = FakeModelService("OTHER-FAKE-TOKEN")
        with self.assertRaisesRegex(BoundaryRefusal, "authentication rejected"):
            TrustedFakeClient(self.root, service).get_task()
        self.assertEqual(service.calls, 0)

    def test_missing_credential_refused_before_tools(self):
        self.auth.unlink()
        with mock.patch(__name__ + ".execute_tool", side_effect=AssertionError("tool launched")):
            with self.assertRaisesRegex(BoundaryRefusal, "credential unavailable"):
                TrustedFakeClient(self.root, FakeModelService(self.token)).get_task()

    def test_weak_credential_permissions_refused(self):
        self.auth.chmod(0o644)
        with self.assertRaisesRegex(BoundaryRefusal, "ownership or mode invalid"):
            TrustedFakeClient(self.root, FakeModelService(self.token)).get_task()

    def test_symlink_credential_refused(self):
        self.auth.unlink()
        self.auth.symlink_to(self.root / "patient" / "fixture.txt")
        with self.assertRaisesRegex(BoundaryRefusal, "symlink rejected"):
            TrustedFakeClient(self.root, FakeModelService(self.token)).get_task()

    def test_unapproved_model_task_never_reaches_sandbox(self):
        for command in ("sh -c 'cat /private/fake-provider-auth.json'",
                        TASK + "; whoami", ""):
            with self.assertRaisesRegex(BoundaryRefusal, "unapproved tool action"):
                only_permitted_task(command)

    def test_child_env_is_explicit_fake_fixture_not_host_copy(self):
        with mock.patch.dict(os.environ, {"REAL_HOST_SECRET": "do-not-copy"}):
            env = child_environment()
            self.assertNotIn("REAL_HOST_SECRET", env)
            self.assertEqual(env["OPENAI_API_KEY"], "FAKE-OPENAI-PARENT-CANARY")
            self.assertNotIn(self.token, repr(env))

    def test_sandbox_bad_result_fails_closed(self):
        with self.assertRaisesRegex(BoundaryRefusal, "unapproved tool action"):
            execute_tool(self.root, "UNAPPROVED", self.auth)

    def test_forged_or_incomplete_tool_evidence_refused(self):
        positive = {key: True for key in EXPECTED_CHECKS}
        self.assertEqual(validated_tool_evidence(positive), positive)
        for bad in (None, {"fake": True}, dict(positive, direct_egress_denied=False),
                    {k: True for k in EXPECTED_CHECKS if k != "host_parent_fd_hidden"}):
            with self.assertRaisesRegex(BoundaryRefusal, "tool isolation assertion failed"):
                validated_tool_evidence(bad)

    def test_fake_credential_never_appears_in_tool_program(self):
        self.assertNotIn(self.token, TOOL_PROGRAM)
        self.assertNotIn(self.token, repr(child_environment()))
        self.assertEqual(len(EXPECTED_CHECKS), 13)

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--unit", action="store_true")
    modes.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    if args.unit:
        result = unittest.TextTestRunner(verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(S2PolicyTests)
        )
        return 0 if result.wasSuccessful() else 1
    try:
        result = smoke()
    except BoundaryRefusal as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
